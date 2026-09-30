"""Stochastic control-first rollout and the user's seven-feature evaluator.

Movement distance is exact for movement-only actions on a fixed occupied board:
light cavalry can take two open steps per action. It does not predict clearing
blockers, future draws, or assistance from another unit.
"""
from collections import Counter, deque
from functools import lru_cache
import math

from .board import HEXES, distance, neighbors

NEIGHBORS = {p: neighbors(p) for p in HEXES}


def clamp(value):
    return max(-1.0, min(1.0, value))


@lru_cache(maxsize=8192)
def position_values(fast, blocked, targets):
    """Reverse shortest-action BFS from each useful, reachable location."""
    open_cells = HEXES - set(blocked)
    adjacent = {p: set(NEIGHBORS[p]) & open_cells for p in open_cells}
    if fast:
        adjacent = {p: (ends | {q for mid in ends for q in adjacent[mid]}) - {p}
                    for p, ends in adjacent.items()}
    values = {p: 0.0 for p in open_cells}
    distances = {p: 99 for p in open_cells}
    for target, importance in targets:
        if target not in open_cells:
            continue
        seen = {target: 0}
        queue = deque([target])
        while queue:
            pos = queue.popleft()
            d = seen[pos]
            values[pos] = max(values[pos], importance / (1 + d))
            distances[pos] = min(distances[pos], d)
            for end in adjacent[pos]:
                if end not in seen:
                    seen[end] = d + 1
                    queue.append(end)
    return values, distances


class Context:
    def __init__(self, state):
        self.state = state
        self.control = [sum(v == who for v in state.controls.values()) for who in (0, 1)]
        self.hands = [Counter(p.hand) for p in state.players]
        self.cycles = [Counter(p.hand + p.bag + [c for c, _ in p.discard]) for p in state.players]
        self.units = [{u: [pos for pos, st in state.board.items() if st.owner == who and st.unit == u]
                       for u in state.players[who].supply} for who in (0, 1)]
        self.threats = [set() for _ in (0, 1)]
        for pos, stack in state.board.items():
            if pos in state.controls and state.controls[pos] != stack.owner:
                if self.hands[stack.owner][stack.unit]:
                    self.threats[stack.owner].add(pos)
        # Free pending maneuvers can control without another coin in hand.
        if state.pending and state.pending[0]['type'] in ('footman', 'mercenary', 'berserk'):
            task = state.pending[0]
            pos = task.get('source')
            if pos in state.board and state.controls.get(pos, state.current) != state.current:
                if task['type'] != 'berserk' or state.board[pos].count > 1:
                    self.threats[state.current].add(pos)
        self.targets = [tuple(sorted((pos, 1.5 if owner == 1-who else 1.0)
                                    for pos, owner in state.controls.items() if owner != who))
                        + tuple((pos, 1.2) for pos in sorted(self.threats[1-who])
                                if state.controls[pos] == who) for who in (0, 1)]
        self.maps = {}

    def route(self, pos):
        if pos not in self.maps:
            stack = self.state.board[pos]
            self.maps[pos] = position_values(stack.unit == 'light_cavalry',
                tuple(sorted(p for p in self.state.board if p != pos)), self.targets[stack.owner])
        return self.maps[pos]

    def useful(self, who):
        return {u for u, positions in self.units[who].items() if any(
            self.route(pos)[0].get(pos, 0) >= .3 or any(
                enemy.owner != who and distance(pos, q) <= 2
                for q, enemy in self.state.board.items()) for pos in positions)}


def action_scores(state, actions):
    """Score actual legal destinations/targets, without peeking at future draws."""
    ctx = Context(state)
    who = state.current
    enemy = 1 - who
    useful = ctx.useful(who)
    threatened = ctx.threats[enemy] if ctx.control[enemy] == 5 else set()
    hand = ctx.hands[who]
    cycle = ctx.cycles[who]
    scores = {}
    free = bool(state.pending and state.pending[0]['type'] != 'coin')
    for action in actions:
        pos = action.source
        if pos is None:
            pos = next(iter(ctx.units[who].get(action.coin, [])), None)
        stack = state.board.get(pos)
        effect = action.effect or action.kind
        end = action.after or (action.path[-1] if action.path else pos)
        score = -5.0 if action.kind == 'pass' else 0.0
        if action.kind == 'defend_supply':
            score = 35
        elif action.kind == 'defend_unit':
            score = -55 if stack and stack.count == 1 else -15
        elif action.kind == 'recruit':
            unit = action.recruit
            need = (min(1.0, 2 / max(1, cycle[unit])) if unit in useful else 0.0)
            dilution = (0 if unit in useful else 1) + max(0, sum(cycle.values()) - 9) / 18
            score = 30 * need - 25 * dilution
            if unit == 'royal_guard' and state.players[who].supply[unit] <= 1:
                score -= 20  # Keep the last supply defense when possible.
        elif action.kind == 'bolster':
            key = pos in state.controls and (state.controls[pos] != who or pos in ctx.threats[enemy]
                       or any(st.owner != who and distance(pos, p) <= 2 for p, st in state.board.items()))
            score = 35 if key else 15
            if stack.count >= 2:
                score -= 15
            score -= 45 * max(0, 2 - (cycle[action.coin] - 1))
        elif action.kind == 'deploy':
            targets = ctx.targets[who]
            values, _ = position_values(action.coin == 'light_cavalry',
                                       tuple(sorted(state.board)), targets)
            score = 20 + 20 * values.get(action.target, 0)
            if cycle[action.coin] <= 1:
                score -= 25
            if action.target in state.controls and state.controls[action.target] != who:
                score += 35
        elif action.kind == 'initiative':
            tempo = any(ctx.route(p)[1].get(p, 99) <= 1
                        for p, st in state.board.items() if st.owner == who and cycle[st.unit] >= 2)
            score = 5 + (45 if tempo and len(state.players[who].hand) >= 2 else 0)
            if max(ctx.control) == 5:
                score += 10
        if effect == 'control' and stack:
            if ctx.control[who] == 5:
                scores[action] = 1000.0
                continue
            score += 180 if state.controls[pos] == enemy else 120
            if threatened and state.controls[pos] == enemy:
                score += 500  # Opponent falls below five controls.
        if action.path or action.after:
            values, distances = ctx.route(pos)
            score += 20 * max(-3, min(3, distances.get(pos, 99) - distances.get(end, 99)))
            score += 20 * (values.get(end, 0) - values.get(pos, 0))
            if end in state.controls and state.controls[end] != who:
                commands = hand[stack.unit] - (0 if free or action.coin != stack.unit else 1)
                score += 70 if commands > 0 else 35
            if end == pos:
                score -= 10
        if action.target is not None and action.kind in ('attack', 'tactic'):
            victim = state.board[action.target]
            guarded = victim.unit == 'royal_guard' and state.players[victim.owner].supply['royal_guard'] > 0
            kill = victim.count == 1 and not guarded
            score += 30 + 55 * kill
            if action.target in state.controls or any(distance(action.target, p) <= 1 for p, _ in ctx.targets[enemy]):
                score += 25
            if kill and threatened == {action.target}:
                score += 500
            if victim.unit == 'pikeman' and distance(action.path[-1] if action.path else pos, action.target) == 1:
                score -= 55 if stack.count == 1 else 15
        scores[action] = score
    return scores


def rollout_action(state, actions, rng):
    scores = action_scores(state, actions)
    best = max(scores.values())
    # Forced tactical wins/blocks take precedence; otherwise use epsilon randomness.
    if best < 500 and rng.random() < .2:
        return rng.choice(actions)
    return rng.choice([a for a in actions if scores[a] == best])


def _useful_draw(player, useful):
    """Expected useful fraction and P(at least one), including a partial refill."""
    expected, none, left, drawn = 0.0, 1.0, 3, 0
    for pool in (player.bag, [c for c, _ in player.discard]):
        n = min(left, len(pool))
        if n:
            count = sum(c in useful for c in pool)
            expected += n * count / len(pool)
            none *= math.comb(len(pool) - count, n) / math.comb(len(pool), n) if len(pool)-count >= n else 0
            left -= n
            drawn += n
    return .5 * (expected / max(1, drawn) + 1 - none)


def features(state, root_player):
    ctx = Context(state)
    threat, position, bag, ability = [], [], [], []
    for who in (0, 1):
        useful = ctx.useful(who)
        t, p = 0.0, 0.0
        for pos, stack in state.board.items():
            if stack.owner != who or not ctx.cycles[who][stack.unit]:
                continue
            values, distances = ctx.route(pos)
            p += values.get(pos, 0)
            if pos in ctx.threats[who]:
                t += 2
            elif ctx.hands[who][stack.unit] >= 2 and distances.get(pos, 99) == 1:
                t += 1
        threat.append(t)
        position.append(p)
        bag.append(_useful_draw(state.players[who], useful))
        ability.append(sum(coin in useful or (coin != 'royal' and not ctx.units[who].get(coin))
                           for coin in state.players[who].hand))
    me, opp = root_player, 1-root_player
    g = lambda c: c + .8 * max(0, c - 3)**2
    urgency = 1 if max(ctx.control) == 5 or any(ctx.threats) else .1
    raw = dict(C=(g(ctx.control[me])-g(ctx.control[opp]))/g(6),
               T=(threat[me]-threat[opp])/8, P=(position[me]-position[opp])/7.5,
               M=(len(state.players[opp].removed)-len(state.players[me].removed))/20,
               B=bag[me]-bag[opp], I=(1 if state.initiative == me else -1)*urgency,
               A=(ability[me]-ability[opp])/4)
    return {key: clamp(value) for key, value in raw.items()}


def evaluate(state, root_player):
    if state.winner is not None:
        return 1.0 if state.winner == root_player else -1.0
    f = features(state, root_player)
    return math.tanh(2.5 * sum(weight*f[key] for key, weight in
                    dict(C=.45, T=.15, P=.12, M=.10, B=.08, I=.05, A=.05).items()))
