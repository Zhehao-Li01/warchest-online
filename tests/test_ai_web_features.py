import random

from warchest import apply_action, legal_actions, observe, new_game, validate_state
from warchest.ai import choose_basic_action
from warchest.presentation import combat_effects
from warchest.web import create_app
from test_base_units import A, B, position


def test_basic_ai_controls_and_uses_only_observation():
    s = position(A, B, board=(((-2, 0), 0, 'footman', 1),), hands=(('footman',), ('royal',)))
    view = observe(s, 0)
    action = choose_basic_action(view, legal_actions(s), random.Random(1))
    assert action.kind == 'control' or action.effect == 'control'
    assert view['players'][1]['hand'] is None
    assert action == choose_basic_action(view, legal_actions(s), random.Random(1))


def test_basic_ai_full_armies_runs_and_preserves_state():
    for seed in range(4):
        s = new_game(seed, (A, B))
        rng = random.Random(seed)
        for _ in range(250):
            if s.winner is not None:
                break
            actions = legal_actions(s)
            action = choose_basic_action(observe(s, s.current), actions, rng)
            assert action in actions
            s, _ = apply_action(s, action)
            validate_state(s)


def test_public_attack_and_damage_cues():
    s = position(A, B, board=(((0, 0), 0, 'footman', 1), ((1, 0), 1, 'mercenary', 1)),
                 hands=(('footman',), ('royal',)))
    action = next(a for a in legal_actions(s) if a.kind == 'attack')
    after, events = apply_action(s, action)
    cues = combat_effects(s, action, events)
    assert cues[0]['unit'] == 'footman'
    assert cues[0]['source'] == (0, 0)
    assert cues[1] == dict(kind='hit', unit='mercenary', owner=1, pos=(1, 0), remaining=0)
    assert (1, 0) not in after.board


def test_ai_room_turn_restart_rematch_and_privacy(tmp_path):
    app = create_app(tmp_path / 'ai.sqlite3')
    app.extensions['rooms'].ai_delay = 0
    client = app.test_client()
    seat = client.post('/api/rooms', json=dict(name='我', mode='intro', opponent='ai', ai_level='basic')).get_json()
    url = '/api/rooms/' + seat['code']
    auth = {'Authorization': 'Bearer ' + seat['token']}
    assert client.post(url + '/join', json={'name': '第三人'}).status_code == 409
    snap = client.get(url, headers=auth).get_json()
    assert snap['status'] == 'playing' and snap['seats'][1]['bot']
    act = next(a for a in snap['actions'] if a['kind'] == 'pass')
    snap = client.post(url + '/actions', headers=auth, json={'revision': snap['revision'], 'action_id': act['id']}).get_json()
    rev = snap['revision']
    restarted = create_app(app.extensions['rooms'].path)
    with restarted.extensions['rooms'].room(seat['code']) as room:
        room['ai_ready_at'] = 0
    snap = restarted.test_client().get(url, headers=auth).get_json()
    assert snap['revision'] == rev + 1 and snap['view']['current'] == 0
    assert snap['view']['players'][1]['hand'] is None
    assert 'ai_seed' not in snap
    snap = client.post(url + '/resign', headers=auth, json={'revision': snap['revision']}).get_json()
    snap = client.post(url + '/rematch', headers=auth, json={'revision': snap['revision']}).get_json()
    assert snap['status'] == 'playing' and snap['game'] == 2
