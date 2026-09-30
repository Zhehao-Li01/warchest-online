"""Full-information UCT with sampled chance outcomes and heuristic rollouts and exact subtree reuse.

Current hands are known. Bag order, game seed and engine random stream are not.
Every action has a chance node (a singleton distribution for deterministic moves).
"""
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
import multiprocessing
import os
from copy import deepcopy
from dataclasses import dataclass, field, replace
import math
import random
import time
from threading import Lock

from .engine import apply_action, legal_actions
from .model import RULES_VERSION
from .units import UNITS
from .rollout_policy import rollout_action, evaluate

DEFAULT_NUM_SIMULATIONS = 512
DEFAULT_ROLLOUT_DEPTH = 16
C_UCT = 1.4
MAX_SEARCH_WORKERS = min(16, len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1))
_POOL = None
_POOL_LOCK = Lock()
_CANONICAL_RNG_STATE = random.Random(0).getstate()


def canonical_state(state):
    """Independent snapshot containing compositions, never the real future stream."""
    result = deepcopy(state, {id(state.history): (), id(state.rng_state): ()})
    result.seed = 0
    result.history = ()
    result.rng_state = _CANONICAL_RNG_STATE
    for player in result.players:
        player.bag.sort()
        player.hand.sort()
        player.discard.sort()
        player.removed.sort()
    return result


def _freeze(value):
    if isinstance(value, dict):
        return tuple((k, _freeze(v)) for k, v in sorted(value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


def state_key(state):
    return (tuple((tuple(sorted(p.supply.items())), tuple(sorted(p.hand)),
                   tuple(sorted(p.bag)), tuple(sorted(p.discard)), tuple(sorted(p.removed)))
                  for p in state.players),
            tuple((pos, st.owner, st.unit, st.count) for pos, st in sorted(state.board.items())),
            tuple(sorted(state.controls.items())), state.current, state.initiative,
            state.initiative_claimed, _freeze(state.pending), state.turn_owner,
            state.winner, state.round, state.version)


def sample_transition(state, action, rng):
    """Uniform permutations implement draws without replacement, including refills.

    The authoritative engine handles when/how many coins are drawn. Shuffling a
    remaining bag afresh is conditional sampling of its unknown order, not a
    replacement draw. A fresh independent engine stream handles discard refills.
    """
    players = []
    for player in state.players:
        bag = sorted(player.bag)
        rng.shuffle(bag)
        players.append(replace(player, bag=bag))
    sample = replace(state, players=players, seed=0, history=(),
                     rng_state=random.Random(rng.getrandbits(128)).getstate())
    result, _ = apply_action(sample, action)
    result.history = ()
    return result


@dataclass
class ChanceNode:
    action: object
    visits: int = 0
    total: float = 0.0
    outcomes: dict = field(default_factory=dict)
    in_flight: int = 0

    def sample(self, state, rng):
        # No UCT and no outcome maximization here: sample the rule distribution.
        result = sample_transition(state, self.action, rng)
        result = canonical_state(result)
        key = state_key(result)
        fresh = key not in self.outcomes
        if fresh:
            self.outcomes[key] = PlayerNode(result)
        return self.outcomes[key], fresh


@dataclass
class PlayerNode:
    state: object
    visits: int = 0
    total: float = 0.0
    edges: dict = field(default_factory=dict)
    in_flight: int = 0

    def expand(self, actions=None):
        if not self.edges and self.state.winner is None:
            self.edges = {a: ChanceNode(a) for a in
                          (legal_actions(self.state) if actions is None else actions)}

    def select(self, root_player, rng, exploration):
        unvisited = [e for e in self.edges.values() if not (e.visits + e.in_flight)]
        if unvisited:
            return rng.choice(unvisited)
        sign = 1 if self.state.current == root_player else -1
        def uct(edge):
            count = edge.visits + edge.in_flight
            return ((sign * edge.total - edge.in_flight) / count
                    + exploration * math.sqrt(math.log(max(1, self.visits + self.in_flight)) / count))
        best = max(map(uct, self.edges.values()))
        return rng.choice([edge for edge in self.edges.values() if uct(edge) == best])


class SearchMemory:
    """Exact successor subtree reuse, bounded and isolated by root player/config."""
    def __init__(self, max_nodes=4000):
        self.root = None
        self.index = {}
        self.signature = None
        self.max_nodes = max_nodes
        self.lock = Lock()

    def prepare(self, state, signature):
        key = state_key(state)
        self.root = self.index.get(key) if self.signature == signature else None
        if self.root is None:
            self.root = PlayerNode(canonical_state(state))
        self.signature = signature
        self.trim()
        return self.root

    def trim(self):
        self.index = {}
        if self.root is None:
            return
        self.index[state_key(self.root.state)] = self.root
        queue = [self.root]
        for node in queue:
            for edge in node.edges.values():
                for key, child in list(edge.outcomes.items()):
                    if len(queue) >= self.max_nodes:
                        del edge.outcomes[key]
                    else:
                        queue.append(child)
                        self.index.setdefault(key, child)


def choose_cheat_mcts_action(state, actions, rng, *, player=None, num_simulations=DEFAULT_NUM_SIMULATIONS,
                             rollout_depth=DEFAULT_ROLLOUT_DEPTH, c_uct=C_UCT, memory=None, stats=None,
                             cancelled=None, simulations=None, max_rollout_steps=None, workers=1):
    """Add a fixed number of simulations; retain exact matching successor trees.

    Legacy keyword aliases are kept for diagnostic scripts. rollout_depth counts
    rollout actions AFTER tree selection; nonterminal leaves use the evaluator.
    """
    if simulations is not None:
        num_simulations = simulations
    if max_rollout_steps is not None:
        rollout_depth = max_rollout_steps
    active = memory if memory is not None else SearchMemory()
    if not active.lock.acquire(blocking=False):
        active = SearchMemory()
        active.lock.acquire()
    try:
        return _search(state, actions, rng, player, num_simulations, rollout_depth,
                       c_uct, active, stats, cancelled, workers)
    finally:
        active.lock.release()


def _search(state, actions, rng, player, num_simulations, rollout_depth, c_uct, memory, stats, cancelled, workers):
    started = time.monotonic()
    if state.extras or state.version != RULES_VERSION or any(
            UNITS[u].expansion != 'base' for p in state.players for u in p.supply):
        raise ValueError('cheating MCTS supports base games only')
    if state.winner is not None or not actions or (player is not None and state.current != player):
        raise ValueError('AI needs its own live turn and legal actions')
    if (type(num_simulations) is not int or num_simulations < 0
            or type(rollout_depth) is not int or rollout_depth < 1 or c_uct != C_UCT
            or type(workers) is not int or not 1 <= workers <= MAX_SEARCH_WORKERS):
        raise ValueError('invalid search budget or c_uct (must be 1.4)')
    root_player = state.current
    signature = (root_player, rollout_depth, c_uct)
    root = memory.prepare(state, signature)
    supplied = list(dict.fromkeys(actions))
    if not set(supplied) <= set(legal_actions(root.state)):
        raise ValueError('illegal root action')
    root.expand(supplied)
    root.edges = {a: root.edges.get(a, ChanceNode(a)) for a in supplied}
    reused = sum(edge.visits for edge in root.edges.values())
    def stopped():
        return cancelled is not None and cancelled()
    completed = attempted = truncated = terminals = rollout_steps = 0
    if len(supplied) > 1 and workers > 1 and num_simulations:
        attempted, completed, truncated, terminals, rollout_steps = _async_simulations(
            root, root_player, rng, num_simulations, rollout_depth, c_uct, workers, stopped)
    elif len(supplied) > 1:
        for _ in range(num_simulations):
            if stopped():
                break
            attempted += 1
            node = root
            path = [root]
            while node.state.winner is None and not stopped():
                node.expand()
                if not node.edges:
                    break
                edge = node.select(root_player, rng, c_uct)
                node, fresh = edge.sample(node.state, rng)
                path.extend((edge, node))
                if fresh:
                    break
            rollout = node.state
            for _ in range(rollout_depth):
                if rollout.winner is not None or stopped():
                    break
                choices = legal_actions(rollout)
                if not choices:
                    break
                rollout = sample_transition(rollout, rollout_action(rollout, choices, rng), rng)
                rollout_steps += 1
            if stopped():
                break
            if rollout.winner is None:
                truncated += 1
            else:
                terminals += 1
            reward = evaluate(rollout, root_player)
            for item in path:
                item.visits += 1
                item.total += reward
            completed += 1
    memory.trim()
    if stats is not None:
        stats.update(iterations=attempted, completed=completed, truncated=truncated, terminals=terminals,
                     rollout_steps=rollout_steps, reused_visits=reused, tree_nodes=len(memory.index),
                     elapsed=time.monotonic() - started, workers=workers,
                     actions={a: dict(visits=e.visits, total=e.total) for a, e in root.edges.items()})
    visited = [e for e in root.edges.values() if e.visits]
    if not visited:
        return rng.choice(supplied)
    best = max((e.visits, e.total / e.visits) for e in visited)
    return rng.choice([e.action for e in visited if (e.visits, e.total / e.visits) == best])


def _rollout_job(state, root_player, seed, depth):
    """Worker receives a canonical snapshot, never owns or mutates search nodes."""
    rng = random.Random(seed)
    steps = 0
    while state.winner is None and steps < depth:
        actions = legal_actions(state)
        if not actions:
            break
        state = sample_transition(state, rollout_action(state, actions, rng), rng)
        steps += 1
    return evaluate(state, root_player), state.winner is not None, steps


def _rollout_pool():
    # One bounded, lazy pool per server process, shared across rooms. Spawn is
    # safe when called from the web server's background threads.
    global _POOL
    with _POOL_LOCK:
        if _POOL is not None and getattr(_POOL, "_broken", False):
            _POOL.shutdown(wait=False, cancel_futures=True)
            _POOL = None
        if _POOL is None:
            _POOL = ProcessPoolExecutor(max_workers=MAX_SEARCH_WORKERS,
                                        mp_context=multiprocessing.get_context('spawn'))
        return _POOL


def _async_simulations(root, root_player, rng, budget, depth, exploration, workers, stopped):
    pending = {}
    attempted = completed = truncated = terminals = steps = 0
    try:
        while (attempted < budget or pending) and not stopped():
            while attempted < budget and len(pending) < workers and not stopped():
                node = root
                path = [root]
                while node.state.winner is None and not stopped():
                    node.expand()
                    if not node.edges:
                        break
                    edge = node.select(root_player, rng, exploration)
                    node, fresh = edge.sample(node.state, rng)
                    path.extend((edge, node))
                    if fresh:
                        break
                if stopped():
                    break
                # Reserve before selecting another path. A virtual loss is
                # pessimistic for the ACTUAL acting player at each node.
                for item in path:
                    item.in_flight += 1
                try:
                    future = _rollout_pool().submit(_rollout_job, node.state, root_player,
                                                    rng.getrandbits(128), depth)
                except BaseException:
                    for item in path:
                        item.in_flight -= 1
                    raise
                pending[future] = path
                attempted += 1
            if not pending or stopped():
                break
            ready, _ = wait(pending, timeout=0.05, return_when=FIRST_COMPLETED)
            for future in ready:
                if stopped():
                    break
                path = pending.pop(future)
                try:
                    reward, terminal, rollout_steps = future.result()
                finally:
                    for item in path:
                        item.in_flight -= 1
                for item in path:
                    item.visits += 1
                    item.total += reward
                completed += 1
                terminals += int(terminal)
                truncated += int(not terminal)
                steps += rollout_steps
            # Immediately refill available slots; never wait for a whole batch.
    finally:
        # Running workers may finish their bounded rollout, but have no tree
        # references or callbacks. Their abandoned results cannot update it.
        for future, path in pending.items():
            future.cancel()
            for item in path:
                item.in_flight -= 1
    return attempted, completed, truncated, terminals, steps
