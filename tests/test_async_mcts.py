from concurrent.futures import ThreadPoolExecutor
from threading import Event
import random

import pytest
from warchest import new_game, legal_actions, serialize
from warchest import cheat_mcts as mcts


def assert_unreserved(memory):
    for node in memory.index.values():
        assert node.in_flight == 0
        assert all(edge.in_flight == 0 for edge in node.edges.values())


def test_real_process_budget_reuse_and_input_isolation():
    state = new_game(31)
    before = serialize(state)
    memory = mcts.SearchMemory()
    try:
        for repeat in range(2):
            stats = {}
            action = mcts.choose_cheat_mcts_action(state, legal_actions(state), random.Random(31),
                num_simulations=17, rollout_depth=3, workers=2, memory=memory, stats=stats)
            assert action in legal_actions(state)
            assert stats['iterations'] == stats['completed'] == 17
            assert stats['terminals'] + stats['truncated'] == 17
            assert stats['reused_visits'] == repeat * 17
            assert sum(r['visits'] for r in stats['actions'].values()) == (repeat+1)*17
            assert serialize(state) == before
            assert_unreserved(memory)
    finally:
        if mcts._POOL is not None:
            mcts._POOL.shutdown()
            mcts._POOL = None


def test_refills_before_slowest_job_returns(monkeypatch):
    third_submitted = Event()
    pool = ThreadPoolExecutor(max_workers=2)
    class Executor:
        count = 0
        def submit(self, fn, *args):
            self.count += 1
            index = self.count
            if index == 3:
                third_submitted.set()
            def run():
                if index == 1:
                    assert third_submitted.wait(3), 'Scheduler waited for a whole batch'
                return (1.0, True, 1)
            return pool.submit(run)
    executor = Executor()
    monkeypatch.setattr(mcts, '_rollout_pool', lambda: executor)
    state = new_game(31)
    stats = {}
    try:
        mcts.choose_cheat_mcts_action(state, legal_actions(state), random.Random(1),
                                    workers=2, num_simulations=5, stats=stats)
        assert executor.count == stats['completed'] == 5
    finally:
        third_submitted.set()
        pool.shutdown()


def test_cancellation_discards_pending_and_cleans_reservations(monkeypatch):
    from concurrent.futures import Future
    cancelled = Event()
    class Executor:
        count = 0
        def submit(self, *args):
            self.count += 1
            if self.count == 2:
                cancelled.set()
            return Future()
    monkeypatch.setattr(mcts, '_rollout_pool', lambda: ExecutorInstance)
    ExecutorInstance = Executor()
    state = new_game(31)
    memory = mcts.SearchMemory()
    stats = {}
    mcts.choose_cheat_mcts_action(state, legal_actions(state), random.Random(1),
        workers=2, num_simulations=10, memory=memory, stats=stats, cancelled=cancelled.is_set)
    assert stats['iterations'] == 2 and stats['completed'] == 0
    assert_unreserved(memory)


def test_worker_failure_does_not_leak_virtual_visits(monkeypatch):
    from concurrent.futures import Future
    class Executor:
        def submit(self, *args):
            f = Future()
            f.set_exception(RuntimeError('worker failed'))
            return f
    monkeypatch.setattr(mcts, '_rollout_pool', lambda: Executor())
    state = new_game(31)
    memory = mcts.SearchMemory()
    with pytest.raises(RuntimeError, match='worker failed'):
        mcts.choose_cheat_mcts_action(state, legal_actions(state), random.Random(1),
                                     workers=2, num_simulations=10, memory=memory)
    memory.trim()
    assert_unreserved(memory)


def test_virtual_loss_uses_actual_actor_and_avoids_busy_unvisited_edge():
    state = new_game(31)
    node = mcts.PlayerNode(state)
    node.expand(legal_actions(state)[:2])
    first, second = node.edges.values()
    first.in_flight = 1
    assert node.select(0, random.Random(1), 1.4) is second
    first.visits = second.visits = 10
    first.total = second.total = 0
    node.visits = 20
    for actor in (0,1):
        node.state.current = actor
        assert node.select(0, random.Random(1), 1.4) is second


@pytest.mark.parametrize('workers', [0, -1, True, 1.5, mcts.MAX_SEARCH_WORKERS+1])
def test_invalid_parallel_budget(workers):
    state = new_game(31)
    with pytest.raises(ValueError):
        mcts.choose_cheat_mcts_action(state, legal_actions(state), random.Random(1), workers=workers)


def test_async_terminal_rewards_back_up_to_shared_root(monkeypatch):
    from dataclasses import replace
    state = new_game(31)
    actions = legal_actions(state)[:2]
    def terminal(state, action, rng):
        return replace(state, winner=0 if action == actions[0] else 1)
    monkeypatch.setattr(mcts, 'sample_transition', terminal)
    with ThreadPoolExecutor(max_workers=2) as pool:
        monkeypatch.setattr(mcts, '_rollout_pool', lambda: pool)
        stats = {}
        action = mcts.choose_cheat_mcts_action(state, actions, random.Random(2),
                                             workers=2, num_simulations=40, stats=stats)
    assert action == actions[0]
    assert stats['terminals'] == stats['completed'] == 40
    assert stats['actions'][actions[0]]['total'] == stats['actions'][actions[0]]['visits']
    assert stats['actions'][actions[1]]['total'] == -stats['actions'][actions[1]]['visits']


def test_web_uses_shared_async_budget():
    from warchest.web import Rooms
    assert Rooms.cheat_mcts_options == dict(num_simulations=5000, rollout_depth=120,
                                          workers=mcts.MAX_SEARCH_WORKERS)
