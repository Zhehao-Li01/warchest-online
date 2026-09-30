from concurrent.futures import ThreadPoolExecutor
import json

import pytest

pytest.importorskip("flask")
from warchest import new_game, serialize
from warchest.web import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path / "rooms.sqlite3")


def auth(seat):
    return {"Authorization": "Bearer " + seat["token"]}


def seated(app):
    c = app.test_client()
    a = c.post("/api/rooms", json={"name": "红方", "mode": "intro"}).get_json()
    b = c.post(f"/api/rooms/{a['code']}/join", json={"name": "蓝方"}).get_json()
    return c, a, b


def test_static_and_bootstrap(app):
    c = app.test_client()
    assert c.get("/").status_code == 200
    assert c.get("/static/app.js").status_code == 200
    data = c.get("/api/bootstrap").get_json()
    assert len(data["units"]) == 47 and len(data["hexes"]) == 37
    assert "rng_state" not in data["preview"]
    assert c.get("/static/../web.py").status_code == 404


def test_waiting_join_and_seat_privacy(app):
    c = app.test_client()
    a = c.post("/api/rooms", json={"name": "A", "mode": "random"}).get_json()
    url = f"/api/rooms/{a['code']}"
    waiting = c.get(url, headers=auth(a)).get_json()
    assert waiting["status"] == "waiting" and waiting["actions"] == []
    assert c.get(url).status_code == 401
    b = c.post(url + "/join", json={"name": "B"}).get_json()
    assert c.post(url + "/join", json={"name": "third"}).status_code == 409
    sa = c.get(url, headers=auth(a)).get_json()
    sb = c.get(url, headers=auth(b)).get_json()
    assert sa["status"] == sb["status"] == "playing"
    assert sa["view"]["players"][1]["hand"] is None
    assert sb["view"]["players"][0]["hand"] is None
    assert (sa if sa["view"]["current"] == 1 else sb)["actions"] == []
    for secret in ("rng_state", '"seed"', '"hash"', '"token"'):
        assert secret not in json.dumps(sa)


def test_authoritative_actions_stale_and_out_of_turn(app):
    c, a, b = seated(app)
    url = f"/api/rooms/{a['code']}"
    snap = c.get(url, headers=auth(a)).get_json()
    action = next(x for x in snap["actions"] if x["kind"] == "pass")
    data = {"revision": snap["revision"], "action_id": action["id"]}
    assert c.post(url + "/actions", json=data, headers=auth(b)).status_code == 403
    assert c.post(url + "/actions", json={**data, "action_id": -1}, headers=auth(a)).status_code == 400
    after = c.post(url + "/actions", json=data, headers=auth(a))
    assert after.status_code == 200
    assert c.post(url + "/actions", json=data, headers=auth(a)).status_code == 409
    other = c.get(url, headers=auth(b)).get_json()
    assert other["view"]["players"][0]["discard"] == [None]
    public_actions = [dict(e["data"]) for e in other["view"]["history"] if e["kind"] == "action"]
    assert public_actions[-1]["coin"] is None


def test_concurrent_duplicate_submission_commits_once(app):
    c, a, _ = seated(app)
    url = f"/api/rooms/{a['code']}"
    snap = c.get(url, headers=auth(a)).get_json()
    data = {"revision": snap["revision"], "action_id": snap["actions"][0]["id"]}
    def submit(_):
        return app.test_client().post(url + "/actions", json=data, headers=auth(a)).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, range(2))) == [200, 409]
    assert c.get(url, headers=auth(a)).get_json()["revision"] == snap["revision"] + 1


def test_restart_preserves_game_and_credentials(app):
    c, a, _ = seated(app)
    url = f"/api/rooms/{a['code']}"
    before = c.get(url, headers=auth(a)).get_json()
    restarted = create_app(app.extensions["rooms"].path).test_client()
    after = restarted.get(url, headers=auth(a)).get_json()
    assert before == after


def test_resign_and_mutually_agreed_rematch(app):
    c, a, b = seated(app)
    url = f"/api/rooms/{a['code']}"
    s = c.get(url, headers=auth(a)).get_json()
    s = c.post(url + "/resign", json={"revision": s["revision"]}, headers=auth(a)).get_json()
    assert s["winner"] == 1 and s["status"] == "finished" and not s["actions"]
    s = c.post(url + "/rematch", json={"revision": s["revision"]}, headers=auth(a)).get_json()
    assert s["status"] == "finished" and s["rematch"] == [0]
    s = c.post(url + "/rematch", json={"revision": s["revision"]}, headers=auth(b)).get_json()
    assert s["game"] == 2 and s["status"] == "playing" and s["view"]["board"] == []


def test_invalid_requests(app):
    c = app.test_client()
    assert c.post("/api/rooms", json={"name": ""}).status_code == 400
    assert c.post("/api/rooms", json={"name": "a" * 17}).status_code == 400
    assert c.post("/api/rooms", json=[]).status_code == 400
    assert c.post("/api/rooms", json={"name": "A"}, headers={"Origin": "https://attacker.example"}).status_code == 403
    assert c.get("/api/rooms/NOEXST").status_code == 404
    assert c.post("/api/rooms", data="x" * 9000, content_type="application/json").status_code == 413


def test_simultaneous_rematch_votes_are_game_scoped(app):
    c, a, b = seated(app)
    url = f"/api/rooms/{a['code']}"
    s = c.get(url, headers=auth(a)).get_json()
    s = c.post(url + "/resign", json={"revision": s["revision"]}, headers=auth(a)).get_json()
    vote = {"revision": s["revision"], "game": s["game"]}
    assert c.post(url + "/rematch", json=vote, headers=auth(a)).status_code == 200
    response = c.post(url + "/rematch", json=vote, headers=auth(b))
    assert response.status_code == 200 and response.get_json()["game"] == 2
    assert c.post(url + "/rematch", json=vote, headers=auth(a)).status_code == 409


def test_online_random_armies_are_disjoint_four_each(app):
    c, a, _ = seated(app)
    random_room = c.post("/api/rooms", json={"name": "A", "mode": "random"}).get_json()
    data = c.get(f"/api/rooms/{random_room['code']}", headers=auth(random_room)).get_json()
    units = [list(p["supply"]) for p in data["view"]["players"]]
    assert len(units[0]) == len(units[1]) == 4 and not set(units[0]) & set(units[1])


def test_host_custom_expansions_validation_persistence_and_rematch(app):
    armies=[['bannerman','bishop','earl','herald'],['sapper','siege_tower','trebuchet','war_wagon']]
    payload={'name':'房主','mode':'custom','armies':armies,'expansions':['base','nobility','siege'],'initiative':1,'opponent':'ai','ai_level':'random'}
    c=app.test_client()
    for bad in ({'expansions':['base']},{'armies':[armies[0],armies[0]]},{'expansions':['base','equipment']},{'initiative':True}):
        assert c.post('/api/rooms',json={**payload,**bad}).status_code==400
    a=c.post('/api/rooms',json=payload).get_json(); url=f"/api/rooms/{a['code']}"
    snap=c.get(url,headers=auth(a)).get_json()
    assert snap['config']['armies']==armies and len(snap['view']['extras']['forts'])==4
    assert len(snap['view']['extras']['decrees'])==3
    restarted=create_app(app.extensions['rooms'].path).test_client()
    assert restarted.get(url,headers=auth(a)).get_json()['config']==snap['config']
    ended=c.post(url+'/resign',headers=auth(a),json={'revision':snap['revision']}).get_json()
    again=c.post(url+'/rematch',headers=auth(a),json={'revision':ended['revision'],'game':ended['game']}).get_json()
    assert again['game']==2 and again['config']==snap['config']
    assert [list(p['supply']) for p in again['view']['players']]==[sorted(a) for a in armies]


def test_random_all_expansions_never_share_alternate_coin_family(app):
    from warchest.units import EXPANSIONS, unit_family
    from warchest.web import Rooms
    for _ in range(30):
        s=Rooms.fresh_state('random',{'expansions':list(EXPANSIONS)})
        assert len({unit_family(u) for p in s.players for u in p.supply})==8
        assert s.extras['enabled']==sorted(EXPANSIONS)


def test_server_rejects_alternate_base_conflict(app):
    c=app.test_client()
    response=c.post('/api/rooms',json={'name':'A','mode':'custom','expansions':['base','shock'],
      'armies':[['warlord','swordsman','pikeman','knight'],['marshall','archer','cavalry','scout']]})
    assert response.status_code==400 and '替代' in response.get_json()['error']


def test_public_activity_hides_payments_and_resets_on_rematch(app):
    c, a, b = seated(app)
    url = f"/api/rooms/{a['code']}"
    snap = c.get(url, headers=auth(a)).get_json()
    assert snap['activity'] == []
    for kind, seat in [('recruit', a), ('initiative', b), ('pass', a)]:
        snap = c.get(url, headers=auth(seat)).get_json()
        action = next(item for item in snap['actions'] if item['kind'] == kind)
        after = c.post(url+'/actions', headers=auth(seat), json={'revision':snap['revision'], 'action_id':action['id']}).get_json()
        public = after['activity'][-1]
        assert public['revision'] == after['revision']
        assert public['action']['kind'] == kind and public['action']['player'] == seat['player']
        assert public['action']['coin'] is None
        if kind == 'recruit':
            assert public['action']['recruit'] == action['recruit']
    # Both seats get the same public feed; polling does not add duplicate events.
    for seat in (a,b):
        assert c.get(url, headers=auth(seat)).get_json()['activity'] == after['activity']
    restarted = create_app(app.extensions['rooms'].path).test_client()
    assert restarted.get(url, headers=auth(b)).get_json()['activity'] == after['activity']
    ended = c.post(url+'/resign', headers=auth(a), json={'revision':after['revision']}).get_json()
    vote = {'revision':ended['revision'], 'game':ended['game']}
    c.post(url+'/rematch', headers=auth(a), json=vote)
    again = c.post(url+'/rematch', headers=auth(b), json=vote).get_json()
    assert again['activity'] == []


@pytest.mark.parametrize('mode,enabled', [('bp',['nobility','siege','nightfall']),('random',['nobility','siege'])])
def test_base_optional_for_expansion_only_rooms(app,mode,enabled):
    c=app.test_client()
    response=c.post('/api/rooms',json={'name':'纯扩展','mode':mode,'expansions':enabled})
    assert response.status_code==201
    seat=response.get_json()
    snap=c.get('/api/rooms/'+seat['code'],headers=auth(seat)).get_json()
    assert snap['config']['expansions']==sorted(enabled)
    from warchest.units import UNITS
    units=snap['draft']['pool'] if mode=='bp' else [u for p in snap['view']['players'] for u in p['supply']]
    assert all(UNITS[u].expansion in enabled for u in units)


@pytest.mark.parametrize('mode,enabled,minimum', [('bp',['nobility','siege'],10),('random',['shock'],8),('custom',['siege'],8)])
def test_expansion_only_pool_must_be_large_enough(app,mode,enabled,minimum):
    response=app.test_client().post('/api/rooms',json={'name':'不足','mode':mode,'expansions':enabled})
    assert response.status_code==400
    assert str(minimum) in response.get_json()['error']


def test_custom_armies_can_exclude_base(app):
    c=app.test_client()
    response=c.post('/api/rooms',json={'name':'自选扩展','mode':'custom','expansions':['nobility','siege'],
        'armies':[['bannerman','bishop','earl','herald'],['sapper','siege_tower','trebuchet','war_wagon']]})
    assert response.status_code==201
    seat=response.get_json()
    snap=c.get('/api/rooms/'+seat['code'],headers=auth(seat)).get_json()
    assert snap['view']['extras']['enabled']==['nobility','siege']
