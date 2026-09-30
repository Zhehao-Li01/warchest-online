"""Server-authoritative BP, persistence, concurrency and AI integration."""
from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from warchest import deserialize, validate_state
from warchest.units import EXPANSIONS, UNITS, unit_family
from warchest.web import create_app


def auth(seat):
    return {'Authorization': 'Bearer ' + seat['token']}


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path / 'draft.sqlite3')


def setup(app, **options):
    client = app.test_client()
    a = client.post('/api/rooms', json={'name': '房主', **options}).get_json()
    url = '/api/rooms/' + a['code']
    b = None if options.get('opponent') == 'ai' else client.post(url + '/join', json={'name': '好友'}).get_json()
    return client, url, [a, b]


def test_default_waits_for_opponent_and_does_not_deal(app):
    c = app.test_client()
    a = c.post('/api/rooms', json={'name': 'A'}).get_json()
    url = '/api/rooms/' + a['code']
    snap = c.get(url, headers=auth(a)).get_json()
    assert snap['mode'] == 'bp' and snap['status'] == 'waiting'
    assert snap['view'] is None and snap['actions'] == []
    assert len(snap['draft']['pool']) == 10
    assert c.get(url).status_code == 401
    assert c.post(url + '/draft', headers=auth(a), json={'revision': 0, 'units': snap['draft']['pool'][:1]}).status_code == 409
    for secret in ('"seed"', '"ai_seed"', '"hash"', '"token"', 'rng_state'):
        assert secret not in json.dumps(snap)


@pytest.mark.parametrize('first', [0, 1])
def test_exact_order_restart_deal_and_rematch(app, first):
    c, url, seats = setup(app, expansions=list(EXPANSIONS))
    with app.extensions['rooms'].room(seats[0]['code']) as room:
        room['draft']['first'] = first
    initial_setup = c.get(url, headers=auth(seats[0])).get_json()["draft"]["setup"]
    assert len(initial_setup["forts"]) == 4 and len(initial_setup["decrees"]) == 3
    assert c.get(url, headers=auth(seats[1])).get_json()["draft"]["setup"] == initial_setup
    expected_picks, expected_bans = [[], []], [[], []]
    for step, (relative, kind, count) in enumerate([(0,'ban',1),(1,'ban',1),(0,'pick',1),(1,'pick',2),(0,'pick',2),(1,'pick',2),(0,'pick',1)]):
        who = first ^ relative
        snap = c.get(url, headers=auth(seats[who])).get_json()
        draft = snap['draft']
        assert draft['setup'] == initial_setup
        assert snap['status'] == 'drafting' and snap['view'] is None and snap['actions'] == []
        assert (draft['step'], draft['current'], draft['kind'], draft['count']) == (step, who, kind, count)
        units = draft['available'][:count]
        (expected_bans if kind == 'ban' else expected_picks)[who].extend(units)
        response = c.post(url + '/draft', headers=auth(seats[who]), json={'revision': snap['revision'], 'units': units})
        assert response.status_code == 200
        after = response.get_json()
        assert after['revision'] == snap['revision'] + 1
        # Every intermediate BP state survives a new app instance and seat authentication.
        restarted = create_app(app.extensions['rooms'].path).test_client()
        assert restarted.get(url, headers=auth(seats[who])).get_json()['draft'] == after['draft']
        c = restarted
    assert after['view']['extras']['forts'] == initial_setup['forts']
    assert after['view']['extras']['decrees'] == initial_setup['decrees']
    assert after['status'] == 'playing'
    assert after['view']['initiative'] == after['view']['current'] == first
    assert after['draft']['picks'] == expected_picks
    assert after['draft']['bans'] == expected_bans
    assert after['draft']['available'] == [] and after['draft']['current'] is None
    assert [set(p['supply']) for p in after['view']['players']] == [set(a) for a in expected_picks]
    assert after['view']['players'][1-first]['hand'] is None
    with app.extensions['rooms'].room(seats[0]['code']) as room:
        validate_state(deserialize(room['state']))
    assert c.post(url + '/draft', headers=auth(seats[first]), json={'revision': after['revision'], 'units': []}).status_code == 409
    ended = c.post(url + '/resign', headers=auth(seats[0]), json={'revision': after['revision']}).get_json()
    vote = {'revision': ended['revision'], 'game': ended['game']}
    assert c.post(url + '/rematch', headers=auth(seats[0]), json=vote).status_code == 200
    again = c.post(url + '/rematch', headers=auth(seats[1]), json=vote).get_json()
    assert again['game'] == 2 and again['status'] == 'drafting' and again['view'] is None
    assert again['draft']['step'] == 0 and again['draft']['picks'] == [[], []] and again['draft']['bans'] == [[], []]
    assert again['config']['expansions'] == sorted(EXPANSIONS)


def test_invalid_and_concurrent_bp_cannot_advance_twice(app):
    c, url, seats = setup(app)
    snap = c.get(url, headers=auth(seats[0])).get_json()
    who = snap['draft']['current']
    data = {'revision': snap['revision'], 'units': snap['draft']['available'][:1]}
    assert c.post(url + '/draft', json=data).status_code == 401
    assert c.post(url + '/draft', headers=auth(seats[1-who]), json=data).status_code == 403
    assert c.post(url + '/actions', headers=auth(seats[who]), json={'revision':snap['revision'], 'action_id':0}).status_code == 409
    for invalid in (None, [], 'archer', [None], [{}], ['unknown'], snap['draft']['available'][:2]):
        assert c.post(url + '/draft', headers=auth(seats[who]), json={**data, 'units':invalid}).status_code == 400
    def submit(_):
        return app.test_client().post(url + '/draft', headers=auth(seats[who]), json=data).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, range(2))) == [200, 409]
    snap = c.get(url, headers=auth(seats[0])).get_json()
    assert snap['revision'] == data['revision']+1 and snap['draft']['step'] == 1
    assert c.post(url+'/draft', headers=auth(seats[1-who]), json={**data, 'revision':snap['revision']}).status_code == 400
    # Advance to the first two-pick turn and reject duplicate or incomplete batches.
    for _ in range(2):
        d = snap['draft']
        snap = c.post(url+'/draft', headers=auth(seats[d['current']]), json={'revision':snap['revision'], 'units':d['available'][:d['count']]}).get_json()
    d = snap['draft']
    assert d['count'] == 2
    for units in ([d['available'][0]], [d['available'][0]]*2):
        assert c.post(url+'/draft', headers=auth(seats[d['current']]), json={'revision':snap['revision'], 'units':units}).status_code == 400


@pytest.mark.parametrize('enabled', [['base'], ['base','shock'], list(EXPANSIONS)])
def test_candidate_pool_respects_expansions_and_alternate_families(app, enabled):
    for _ in range(20):
        c, url, seats = setup(app, expansions=enabled)
        pool = c.get(url, headers=auth(seats[0])).get_json()['draft']['pool']
        assert len(pool) == len(set(pool)) == len({unit_family(u) for u in pool}) == 10
        assert all(UNITS[u].expansion in enabled for u in pool)


@pytest.mark.parametrize('first', [0, 1])
@pytest.mark.parametrize('level', ['mcts', 'basic', 'random'])
def test_ai_completes_bp_and_can_rematch_from_bp(app, first, level):
    rooms = app.extensions['rooms']
    rooms.ai_delay = 0
    c, url, seats = setup(app, opponent='ai', ai_level=level)
    with rooms.room(seats[0]['code']) as room:
        room['draft']['first'] = first
    for _ in range(12):
        snap = c.get(url, headers=auth(seats[0])).get_json()
        if snap['status'] == 'playing':
            break
        if snap['draft']['current'] == 0:
            d = snap['draft']
            response = c.post(url+'/draft', headers=auth(seats[0]), json={'revision':snap['revision'], 'units':d['available'][:d['count']]})
            assert response.status_code == 200
            snap = response.get_json()
            if snap['status'] == 'playing':
                break
    assert snap['status'] == 'playing' and snap['draft']['step'] == 7
    assert [len(a) for a in snap['draft']['picks']] == [4,4]
    ended = c.post(url+'/resign', headers=auth(seats[0]), json={'revision':snap['revision']}).get_json()
    again = c.post(url+'/rematch', headers=auth(seats[0]), json={'revision':ended['revision'], 'game':ended['game']}).get_json()
    assert again['status'] == 'drafting' and again['game'] == 2
    ended = c.post(url+'/resign', headers=auth(seats[0]), json={'revision':again['revision']}).get_json()
    assert ended['status'] == 'finished' and ended['view'] is None and ended['winner'] == 1
    assert c.get(url, headers=auth(seats[0])).get_json()['draft']['step'] == 0
