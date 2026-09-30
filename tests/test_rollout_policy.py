from copy import deepcopy
import random
import pytest

from warchest import Action, legal_actions, new_game, apply_action, validate_state
from warchest.board import LOCATIONS
from warchest.cheat_mcts import SearchMemory, choose_cheat_mcts_action, state_key
from warchest.rollout_policy import action_scores, evaluate, features, position_values, rollout_action, _useful_draw
from warchest.model import Player
from test_base_units import A, B, position


def test_control_priority_and_forced_win():
    s = position(A, B, board=(((-2, 0), 0, 'footman', 2), ((-1, 0), 1, 'knight', 1)),
                 hands=(('footman', 'royal'), ('royal',)))
    scores = action_scores(s, legal_actions(s))
    control = next(a for a in scores if a.kind == 'control')
    attack = next(a for a in scores if a.kind == 'attack')
    assert scores[control] > scores[attack]
    s.controls = dict.fromkeys(LOCATIONS)
    for p in sorted(LOCATIONS - {(-2, 0)})[:5]:
        s.controls[p] = 0
    validate_state(s)
    for seed in range(20):
        assert rollout_action(s, legal_actions(s), random.Random(seed)).kind in ('control', 'tactic')
        action = rollout_action(s, legal_actions(s), random.Random(seed))
        assert action_scores(s, [action])[action] == 1000


def test_stops_immediate_loss_and_guard_is_not_assumed_to_die():
    s = position(A, B, board=(((-1, 0), 0, 'footman', 1), ((-2, 0), 1, 'mercenary', 1)),
                 hands=(('footman',), ('mercenary',)))
    s.controls = dict.fromkeys(LOCATIONS)
    for p in sorted(LOCATIONS - {(-2, 0)})[:5]:
        s.controls[p] = 1
    scores = action_scores(s, legal_actions(s))
    attack = next(a for a in scores if a.kind == 'attack')
    assert scores[attack] >= 500
    s.board[(-2, 0)].unit = 'royal_guard'
    s.players[1].hand = ['royal_guard']
    scores = action_scores(s, legal_actions(s))
    assert scores[attack] < 500


def test_stochastic_policy_explores_lower_scoring_actions():
    s = new_game(0)
    actions = legal_actions(s)
    rng = random.Random(1)
    scores = action_scores(s, actions)
    results = [rollout_action(s, actions, rng) for _ in range(150)]
    assert any(scores[a] < max(scores.values()) for a in results)
    assert sum(scores[a] == max(scores.values()) for a in results) > 90


def test_bag_dilution_and_bolster_preserves_commands():
    assert _useful_draw(Player({}, bag=['a']*3+['b']*6), {'a'}) > _useful_draw(Player({}, bag=['a']*3+['b']*12), {'a'})
    s = position(A, B, board=(((0, 0), 0, 'footman', 2),), hands=(('footman',), ('royal',)))
    actions = legal_actions(s)
    scores = action_scores(s, actions)
    assert max(scores[a] for a in actions if a.kind == 'bolster') < 0
    assert max(scores[a] for a in actions if a.kind == 'recruit' and a.recruit == 'footman') > max(
        scores[a] for a in actions if a.kind == 'recruit' and a.recruit == 'marshall')


def test_action_distance_and_blockers():
    targets = (((2, 0), 1.0),)
    assert position_values(False, (), targets)[1][(0, 0)] == 2
    assert position_values(True, (), targets)[1][(0, 0)] == 1
    blocked = ((1, 0), (1, -1), (0, 1), (-1, 1), (-1, 0), (0, -1))
    assert position_values(True, blocked, targets)[1][(0, 0)] == 99


def test_evaluator_symmetry_bounds_and_control_nonlinearity():
    s = new_game(2)
    assert evaluate(s, 0) == pytest.approx(-evaluate(s, 1))
    assert all(-1 <= value <= 1 for value in features(s, 0).values())
    s.controls = dict.fromkeys(LOCATIONS)
    points = sorted(LOCATIONS)
    values = []
    for count in (3, 4, 5):
        s.controls = {p: 0 if p in points[:count] else None for p in LOCATIONS}
        values.append(features(s, 0)['C'])
    assert values[2]-values[1] > values[1]-values[0]
    s.winner = 1
    assert evaluate(s, 0) == -1 and evaluate(s, 1) == 1


def test_reuse_actual_successor_and_reset_other_player():
    s = position(A, B)
    memory = SearchMemory()
    choose_cheat_mcts_action(s, legal_actions(s), random.Random(0),
                             num_simulations=150, rollout_depth=2, memory=memory)
    child = next(n for n in memory.index.values() if n.state.current == s.current
                 and state_key(n.state) != state_key(s) and any(e.visits for e in n.edges.values()))
    stats = {}
    prior = sum(e.visits for e in child.edges.values())
    choose_cheat_mcts_action(child.state, legal_actions(child.state), random.Random(2),
                             num_simulations=2, rollout_depth=2, memory=memory, stats=stats)
    assert memory.root is child
    assert stats['reused_visits'] == prior > 0
    assert sum(e.visits for e in memory.root.edges.values()) == prior + 2
    other = deepcopy(s)
    other.current = 1-s.current
    choose_cheat_mcts_action(other, legal_actions(other), random.Random(0),
                             num_simulations=0, rollout_depth=2, memory=memory, stats=stats)
    assert stats['reused_visits'] == 0


def test_reuse_bounded_cache_and_fixed_c():
    s = new_game(0)
    memory = SearchMemory(max_nodes=8)
    choose_cheat_mcts_action(s, legal_actions(s), random.Random(0), num_simulations=30,
                             rollout_depth=2, memory=memory)
    assert len(memory.index) <= 8
    with pytest.raises(ValueError):
        choose_cheat_mcts_action(s, legal_actions(s), random.Random(0), c_uct=1.5)


def test_known_hand_threat_and_dynamic_initiative():
    s = position(A, B, board=(((-2, 0), 0, 'footman', 1),),
                 hands=(('footman', 'royal'), ('royal',)))
    before = features(s, 0)
    s.players[0].hand.remove('footman')
    s.players[0].bag.append('footman')
    after = features(s, 0)
    assert before['T'] > after['T']
    s = position(A, B, board=(((-1, 0), 1, 'mercenary', 1),),
                 hands=(('royal',), ('mercenary', 'mercenary')), current=1)
    actions = legal_actions(s)
    take = next(a for a in actions if a.kind == 'initiative')
    high = action_scores(s, actions)[take]
    s.board.clear()
    assert high > action_scores(s, legal_actions(s))[take]


def test_web_reuses_memory_per_game_and_clears_on_resign(tmp_path, monkeypatch):
    import time
    from warchest import serialize
    from warchest.web import create_app
    memories = []
    def choose(state, actions, rng, **kwargs):
        memories.append(kwargs['memory'])
        return next(a for a in actions if a.kind == 'pass')
    monkeypatch.setattr('warchest.web.choose_cheat_mcts_action', choose)
    rooms = create_app(tmp_path / 'reuse.sqlite3').extensions['rooms']
    rooms.ai_delay = 0
    seat = rooms.create('玩家', 'intro', 'ai', 'cheat_mcts')
    with rooms.room(seat['code']) as room:
        room['state'] = serialize(new_game(0, initiative=1))
    def advance(revision):
        deadline = time.monotonic()+10
        while time.monotonic() < deadline:
            snapshot = rooms.get(seat['code'], seat['token'])
            if snapshot['revision'] >= revision:
                return snapshot
            time.sleep(.01)
        raise AssertionError('background move did not complete')
    snap = advance(1)
    action = next(a for a in snap['actions'] if a['kind'] == 'pass')
    rooms.change(seat['code'], seat['token'], 'actions', dict(revision=1, action_id=action['id']))
    snap = advance(3)
    assert len(memories) == 2 and memories[0] is memories[1]
    rooms.change(seat['code'], seat['token'], 'resign', dict(revision=snap['revision']))
    assert not rooms._ai_memories
