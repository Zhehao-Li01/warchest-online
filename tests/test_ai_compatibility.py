import json
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from warchest import new_game
from warchest.board import LOCATIONS
from warchest.serialization import serialize
from warchest.web import create_app
from test_base_units import A, B


def ai_room(tmp_path):
    app = create_app(tmp_path / 'ai.sqlite3')
    rooms = app.extensions['rooms']
    rooms.ai_delay = 0
    seat = rooms.create('人类', 'intro', 'ai')
    with rooms.room(seat['code']) as room:
        room['state'] = serialize(new_game(0, initiative=1))
    return app, rooms, seat


@pytest.mark.parametrize('level', ['mcts', 'basic'])
def test_legacy_requests_use_random_for_base_and_expansions(tmp_path, level):
    app = create_app(tmp_path / 'scope.sqlite3')
    c = app.test_client()
    for mode in ('intro', 'random', 'bp', 'custom'):
        payload = dict(name='人类', mode=mode, opponent='ai', ai_level=level,
                       expansions=['base'], armies=[list(A), list(B)])
        result = c.post('/api/rooms', json=payload)
        assert result.status_code == 201
        seat = result.get_json()
        with app.extensions['rooms'].room(seat['code']) as room:
            assert room['ai_level'] == 'random' and room['seats'][1]['name'] == '随机 AI'
    payload = dict(name='人类', mode='random', opponent='ai', ai_level=level, expansions=['base', 'shock'])
    assert c.post('/api/rooms', json=payload).status_code == 201
    assert c.post('/api/rooms', json={**payload, 'ai_level': 'random'}).status_code == 201


@pytest.mark.parametrize('legacy', ['basic', 'mcts', None])
@pytest.mark.parametrize('expanded', [False, True])
def test_legacy_rooms_migrate_on_load(tmp_path, expanded, legacy):
    app, rooms, seat = ai_room(tmp_path)
    # Write the legacy representation directly, without triggering migration.
    with rooms.connection() as conn:
        data = json.loads(conn.execute('SELECT payload FROM rooms WHERE code=?', (seat['code'],)).fetchone()[0])
        data['ai_level'] = legacy
        if legacy is None:
            del data['ai_level']
        data['seats'][1]['name'] = '基础 AI'
        data['config']['expansions'] = ['base', 'shock'] if expanded else ['base']
        conn.execute('UPDATE rooms SET payload=? WHERE code=?', (json.dumps(data), seat['code']))
    restarted = create_app(rooms.path).extensions['rooms']
    with restarted.room(seat['code']) as room:
        assert room['ai_level'] == 'random'
        assert room['seats'][1]['name'] == '随机 AI'


def test_concurrent_decisions_commit_once_without_database_lock(tmp_path, monkeypatch):
    app, rooms, seat = ai_room(tmp_path)
    barrier = threading.Barrier(3)
    release = threading.Event()
    def searching(view, actions, rng, **kwargs):
        barrier.wait(timeout=5)
        assert release.wait(timeout=5)
        return actions[0]
    monkeypatch.setattr('warchest.web.choose_action', searching)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(rooms.get, seat['code'], seat['token']) for _ in range(2)]
        try:
            barrier.wait(timeout=5)
            # Creating another room requires SQLite's writer lock.
            other = pool.submit(rooms.create, '另一个房间', 'intro').result(timeout=3)
            assert other['code'] != seat['code']
        finally:
            release.set()
        for f in futures:
            assert f.result(timeout=5)['revision'] == 1
    with rooms.room(seat['code']) as room:
        assert room['revision'] == 1


@pytest.mark.parametrize('change', ['revision', 'game', 'resign', 'current', 'winner'])
def test_stale_decision_discarded(tmp_path, monkeypatch, change):
    app, rooms, seat = ai_room(tmp_path)
    def searching(view, actions, rng, **kwargs):
        with rooms.room(seat['code']) as room:
            if change in ('revision', 'game'):
                room[change] += 1
            elif change == 'resign':
                room['resigned'] = 0
            else:
                state = new_game(0, initiative=0 if change == 'current' else 1)
                if change == 'winner':
                    state.controls = dict.fromkeys(state.controls)
                    for p in sorted(LOCATIONS)[:6]:
                        state.controls[p] = 0
                    state.winner = 0
                room['state'] = serialize(state)
        return actions[0]
    monkeypatch.setattr('warchest.web.choose_action', searching)
    result = rooms.get(seat['code'], seat['token'])
    assert result['revision'] == (1 if change == 'revision' else 0)


