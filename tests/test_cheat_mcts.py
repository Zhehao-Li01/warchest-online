from collections import Counter
from copy import deepcopy
from dataclasses import replace
import random
import time
import pytest

from warchest import Action, new_game, legal_actions, validate_state, serialize
from warchest.board import LOCATIONS
from warchest.cheat_mcts import (canonical_state, state_key, sample_transition,
                                 ChanceNode, PlayerNode, choose_cheat_mcts_action)
from warchest.web import create_app
from test_base_units import A, B, position


def test_current_hands_known_but_order_seed_stream_ignored():
    state = new_game(4)
    other = deepcopy(state)
    other.seed = 999
    other.rng_state = random.Random(999).getstate()
    for p in other.players:
        p.bag.reverse()
        p.hand.reverse()
    assert state_key(canonical_state(state)) == state_key(canonical_state(other))
    before = serialize(state)
    actions = legal_actions(state)
    results = []
    for s in (state, other):
        stats = {}
        action = choose_cheat_mcts_action(s, actions, random.Random(2), 
                                         simulations=3, max_rollout_steps=12, stats=stats)
        results.append((action, stats['actions']))
    assert results[0] == results[1]
    assert serialize(state) == before
    other.players[1].hand[0] = 'royal'
    if other.players[1].hand == state.players[1].hand:
        other.players[1].hand[0] = 'footman'
    assert state_key(canonical_state(other)) != state_key(canonical_state(state))


def priest_state():
    s = position(A, B, board=(((-2, 0), 0, 'warrior_priest', 1),),
                 hands=(('warrior_priest', 'royal'), ('royal',)))
    s.players[0].bag = ['berserker', 'berserker', 'footman', 'marshall']
    for coin in s.players[0].bag:
        s.players[0].supply[coin] -= 1
    validate_state(s)
    return s


def test_chance_samples_true_multiplicity_and_groups_outcomes():
    s = priest_state()
    before = serialize(s)
    edge = ChanceNode(Action('control', 'warrior_priest'))
    rng = random.Random(22)
    counts = Counter()
    for _ in range(1200):
        node, _ = edge.sample(s, rng)
        validate_state(node.state)
        assert node.state.current == 0
        counts[node.state.pending[0]['coin']] += 1
    assert len(edge.outcomes) == 3
    assert 540 < counts['berserker'] < 660
    assert 240 < counts['footman'] < 360
    assert 240 < counts['marshall'] < 360
    assert edge.visits == 0  # Sampling chance outcomes never selects by visit count.
    assert serialize(s) == before


def test_round_draws_without_replacement_and_refills():
    s = new_game(0)
    for p in s.players:
        p.discard.extend((c, False) for c in p.hand)
        p.hand.clear()
        p.discard.extend((c, False) for c in p.bag[1:])
        p.bag = p.bag[:1]
    s.players[0].hand.append(s.players[0].discard.pop()[0])
    s.current = 0
    validate_state(s)
    a = Action('pass', s.players[0].hand[0])
    for seed in range(20):
        result = sample_transition(s, a, random.Random(seed))
        validate_state(result)
        assert result.round == s.round + 1
        assert all(len(p.hand) == 3 for p in result.players)
        assert all(s.players[i].bag[0] in p.hand for i, p in enumerate(result.players))


def test_uct_uses_actual_actor_not_depth_parity():
    s = new_game(0)
    actions = legal_actions(s)[:2]
    node = PlayerNode(s, visits=20, edges={
        actions[0]: ChanceNode(actions[0], visits=10, total=8),
        actions[1]: ChanceNode(actions[1], visits=10, total=-8)})
    assert node.select(0, random.Random(0), 0).action == actions[0]
    node.state = replace(s, current=1)
    assert node.select(0, random.Random(0), 0).action == actions[1]
    node.state = replace(s, current=0)
    assert node.select(0, random.Random(0), 0).action == actions[0]


def test_guard_defense_and_berserker_continuation():
    s = position(A, B, board=(((0, 0), 0, 'warrior_priest', 1), ((1, 0), 1, 'royal_guard', 1)),
                 hands=(('warrior_priest',), ('royal',)))
    result = sample_transition(s, Action('attack', 'warrior_priest', target=(1, 0)), random.Random(0))
    validate_state(result)
    assert result.current == 1 and result.turn_owner == 0
    result = sample_transition(result, Action('defend_supply', 'royal_guard', source=(1, 0)), random.Random(1))
    validate_state(result)
    assert result.current == 0 and result.pending[0]['type'] == 'coin'
    s = position(A, B, board=(((0, 0), 0, 'berserker', 3),), hands=(('berserker',), ('royal',)))
    result = sample_transition(s, Action('move', 'berserker', path=((1, 0),)), random.Random(0))
    validate_state(result)
    assert result.current == 0 and result.pending[0]['type'] == 'berserk'


def test_immediate_win_terminal_rewards_and_final_visits():
    s = position(A, B, board=(((-2, 0), 0, 'footman', 1),), hands=(('footman',), ('royal',)))
    s.controls = dict.fromkeys(LOCATIONS)
    for pos in sorted(LOCATIONS - {(-2, 0)})[:5]:
        s.controls[pos] = 0
    validate_state(s)
    choices = [next(a for a in legal_actions(s) if a.kind == 'control'), Action('pass', 'footman')]
    stats = {}
    action = choose_cheat_mcts_action(s, choices, random.Random(2), 
                                     simulations=20, max_rollout_steps=1, stats=stats)
    assert action == choices[0]
    assert stats['completed'] > 0
    assert stats['actions'][choices[0]]['total'] == stats['actions'][choices[0]]['visits']
    assert stats['actions'][choices[1]]['total'] < stats['actions'][choices[1]]['visits']
    assert stats['completed'] == 20
    assert stats['terminals'] + stats['truncated'] == 20


def test_boundaries_and_cancellation():
    s = new_game(0)
    actions = legal_actions(s)
    for kw in [dict(player=1), dict(simulations=-1), dict(max_rollout_steps=0)]:
        with pytest.raises(ValueError):
            choose_cheat_mcts_action(s, actions, random.Random(0), **kw)
    with pytest.raises(ValueError):
        choose_cheat_mcts_action(s, [], random.Random(0))
    with pytest.raises(ValueError):
        choose_cheat_mcts_action(s, [Action('nonsense', 'royal')], random.Random(0))
    assert choose_cheat_mcts_action(s, [actions[0]], random.Random(0)) == actions[0]
    assert choose_cheat_mcts_action(s, actions, random.Random(0), simulations=0) in actions
    stats = {}
    assert choose_cheat_mcts_action(s, actions, random.Random(0), cancelled=lambda: True, stats=stats) in actions
    assert stats['completed'] == 0
    expanded = new_game(0, expansions=['base', 'shock'])
    with pytest.raises(ValueError, match='base'):
        choose_cheat_mcts_action(expanded, legal_actions(expanded), random.Random(0))


def test_web_cheat_room_restart_privacy_and_rematch(tmp_path):
    app = create_app(tmp_path / 'cheat.sqlite3')
    rooms = app.extensions['rooms']
    rooms.ai_delay = 0
    rooms.cheat_mcts_options = dict(simulations=0)
    seat = rooms.create('玩家', 'intro', 'ai', 'cheat_mcts')
    with rooms.room(seat['code']) as room:
        room['state'] = serialize(new_game(0, initiative=1))
    snap = rooms.get(seat['code'], seat['token'])
    deadline = time.monotonic() + 5
    while snap['revision'] == 0 and time.monotonic() < deadline:
        time.sleep(.01)
        snap = rooms.get(seat['code'], seat['token'])
    assert snap['revision'] == 1
    assert snap['ai_level'] == 'cheat_mcts'
    assert snap['seats'][1]['name'] == '作弊 MCTS AI'
    assert snap['view']['players'][1]['hand'] is None
    restarted = create_app(rooms.path).extensions['rooms']
    with restarted.room(seat['code']) as room:
        assert room['ai_level'] == 'cheat_mcts'
    snap = rooms.change(seat['code'], seat['token'], 'resign', dict(revision=snap['revision']))
    snap = rooms.change(seat['code'], seat['token'], 'rematch', dict(revision=snap['revision']))
    assert snap['game'] == 2 and snap['ai_level'] == 'cheat_mcts'
    response = app.test_client().post('/api/rooms', json=dict(name='人类', mode='random', opponent='ai',
                      ai_level='cheat_mcts', expansions=['base', 'shock']))
    assert response.status_code == 400


def test_background_deduplicates_and_discards_stale_result(tmp_path, monkeypatch):
    from threading import Event
    entered, release = Event(), Event()
    calls = []
    def slow(state, actions, rng, **kwargs):
        calls.append(state.current)
        entered.set()
        assert release.wait(5)
        return actions[0]
    monkeypatch.setattr('warchest.web.choose_cheat_mcts_action', slow)
    rooms = create_app(tmp_path / 'jobs.sqlite3').extensions['rooms']
    rooms.ai_delay = 0
    seat = rooms.create('玩家', 'intro', 'ai', 'cheat_mcts')
    with rooms.room(seat['code']) as room:
        room['state'] = serialize(new_game(0, initiative=1))
    try:
        rooms.get(seat['code'], seat['token'])
        assert entered.wait(5)
        for _ in range(5):
            assert rooms.get(seat['code'], seat['token'])['revision'] == 0
        assert calls == [1]
        assert rooms.create('其他房间', 'intro')['code'] != seat['code']
        rooms.change(seat['code'], seat['token'], 'resign', dict(revision=0))
        assert rooms._ai_jobs[seat['code']][1].is_set()
    finally:
        release.set()
    deadline = time.monotonic() + 5
    while rooms._ai_jobs and time.monotonic() < deadline:
        time.sleep(.01)
    with rooms.room(seat['code']) as room:
        assert room['revision'] == 1 and room['resigned'] == 0
    assert not rooms._ai_jobs


@pytest.mark.parametrize('mode', ['intro', 'random', 'custom', 'bp'])
def test_cheat_creation_modes(tmp_path, mode):
    rooms = create_app(tmp_path / 'modes.sqlite3').extensions['rooms']
    seat = rooms.create('玩家', mode, 'ai', 'cheat_mcts', armies=[list(A), list(B)])
    with rooms.room(seat['code']) as room:
        assert room['ai_level'] == 'cheat_mcts'


def test_exact_thousand_backups_win_loss_and_final_selection(monkeypatch):
    s = new_game(0)
    actions = legal_actions(s)[:2]
    def terminal(state, action, rng):
        return replace(state, winner=0 if action == actions[0] else 1)
    monkeypatch.setattr('warchest.cheat_mcts.sample_transition', terminal)
    stats = {}
    chosen = choose_cheat_mcts_action(s, actions, random.Random(9), num_simulations=1000, stats=stats)
    assert chosen == actions[0]
    assert stats['completed'] == stats['terminals'] == 1000
    assert stats['truncated'] == 0
    assert sum(v['visits'] for v in stats['actions'].values()) == 1000
    assert stats['actions'][actions[0]]['total'] == stats['actions'][actions[0]]['visits']
    assert stats['actions'][actions[1]]['total'] == -stats['actions'][actions[1]]['visits']


def test_truncated_simulations_use_bounded_evaluation():
    s = new_game(0)
    stats = {}
    chosen = choose_cheat_mcts_action(s, legal_actions(s), random.Random(1),
                                     simulations=25, max_rollout_steps=1, stats=stats)
    assert chosen in legal_actions(s)
    assert stats['completed'] == stats['truncated'] == 25
    assert stats['terminals'] == 0
    assert sum(v['visits'] for v in stats['actions'].values()) == 25
    assert all(abs(v['total']) < v['visits'] for v in stats['actions'].values() if v['visits'])
