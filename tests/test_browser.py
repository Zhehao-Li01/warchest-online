"""Real Chromium tests. Run with WC_BROWSER=1; separate from fast engine tests."""
import json
import os
from pathlib import Path
import threading

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("WC_BROWSER") != "1", reason="set WC_BROWSER=1 for Chromium")


@pytest.fixture
def live(tmp_path):
    from werkzeug.serving import make_server
    from warchest.web import create_app
    app = create_app(tmp_path / "browser.sqlite3")
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield app, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join()


@pytest.fixture
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


def test_two_browsers_deploy_bolster_reload_and_resign(live, browser, tmp_path):
    from playwright.sync_api import expect
    from warchest import new_game, serialize
    app, url = live
    ca, cb = browser.new_context(viewport={"width": 1440, "height": 1100}), browser.new_context()
    a, b = ca.new_page(), cb.new_page()
    errors = []
    a.on("pageerror", lambda e: errors.append(str(e)))
    b.on("pageerror", lambda e: errors.append(str(e)))
    a.goto(url)
    a.locator("#player-name").fill("红方指挥官")
    a.locator("#army-mode").select_option("intro")
    a.locator("#create-room").click()
    expect(a.locator(".room-code")).to_be_visible()
    code = a.locator(".room-code").inner_text()
    # Fix the deal: A has two swordsmen, allowing a real bolster interaction.
    with app.extensions["rooms"].room(code) as room:
        room["state"] = serialize(new_game(2))
        room["revision"] += 1
    b.goto(f"{url}/?room={code}")
    b.locator("#join-name").fill("蓝方指挥官")
    b.locator("#join-form button").click()
    expect(a.locator("#turn-banner")).to_contain_text("轮到你")
    a.locator('[data-coin="swordsman"]').first.click()
    expect(a.locator("#action-dialog")).to_be_visible()
    a.locator('[data-group="deploy"]').click()
    expect(a.locator(".hex.available")).to_have_count(2)
    target = a.locator(".hex.available").first.get_attribute("data-pos")
    a.locator(".hex.available").first.click()
    expect(b.locator(f'[data-pos="{target}"] .unit-token')).to_be_visible()
    expect(a.locator("#action-dialog")).not_to_be_visible()
    b.locator(".hand-coin").first.click()
    b.locator('[data-group="pass"]').click()
    expect(a.locator("#turn-banner")).to_contain_text("轮到你")
    a.locator('[data-coin="swordsman"]').click()
    a.locator('[data-group="bolster"]').click()
    expect(a.locator(f'[data-pos="{target}"] .stack-number')).to_have_text("2")
    expect(a.locator("#action-dialog")).not_to_be_visible()
    expect(b.locator(f'[data-pos="{target}"] .stack-number')).to_have_text("2")
    a.reload()
    expect(a.locator(".room-code")).to_have_text(code)
    expect(a.locator(f'[data-pos="{target}"] .stack-number')).to_have_text("2")
    ca.set_offline(True)
    expect(a.locator("#save-status")).to_contain_text("连接中断")
    ca.set_offline(False)
    expect(a.locator("#save-status")).to_contain_text("局面已自动保存", timeout=10000)
    a.close()
    a = ca.new_page()
    a.on("pageerror", lambda e: errors.append(str(e)))
    a.goto(f"{url}/?room={code}")
    expect(a.locator(".room-code")).to_have_text(code)
    expect(a.locator(f'[data-pos="{target}"] .stack-number')).to_have_text("2")
    a.locator("#resign-game").click()
    a.locator("#confirm-resign").click()
    expect(b.locator("#turn-banner")).to_contain_text("你赢得")
    a.locator("#rematch-game").click()
    expect(b.locator("#rematch-game")).to_be_visible()
    b.locator("#rematch-game").click()
    expect(a.locator(".unit-token")).to_have_count(0)
    expect(a.locator("#room-badge")).to_have_text("第 2 局")
    assert errors == []
    ca.close()
    cb.close()


def test_mobile_layout_encyclopedia_and_menu(live, browser):
    from playwright.sync_api import expect
    app, url = live
    context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    page = context.new_page()
    page.goto(url)
    expect(page.locator(".hex")).to_have_count(37)
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    page.locator("#nav-units").click()
    expect(page.locator("[data-encyclopedia]")).to_have_count(35)
    page.locator('[data-encyclopedia="warrior_priest"]').click()
    expect(page.locator("#encyclopedia-detail")).to_contain_text("立即")
    page.locator('[data-close="general-dialog"]').click()
    page.locator("#toggle-coords").click()
    expect(page.locator(".coord")).to_have_count(37)
    artifacts = Path("docs/screenshots")
    artifacts.mkdir(exist_ok=True)
    page.screenshot(path=str(artifacts / "mobile.png"), full_page=True)
    page.set_viewport_size({"width": 1440, "height": 1150})
    page.locator("#toggle-coords").click()
    page.screenshot(path=str(artifacts / "desktop.png"), full_page=True)
    context.close()


def test_movement_and_priest_bolster_single_result(live, browser):
    from playwright.sync_api import expect
    from test_base_units import A, B, position
    from warchest import serialize
    app, url = live
    client = app.test_client()
    seat = client.post("/api/rooms", json={"name": "牧师玩家"}).get_json()
    client.post(f"/api/rooms/{seat['code']}/join", json={"name": "对手"})
    s = position(A, B, board=(((0, 0), 0, "warrior_priest", 1),),
                 hands=(("warrior_priest", "warrior_priest"), ("royal",)))
    with app.extensions["rooms"].room(seat["code"]) as room:
        room["state"] = serialize(s)
    page = browser.new_page()
    page.add_init_script(f"sessionStorage.setItem('wc.session', {json.dumps(json.dumps(seat))});")
    page.goto(url)
    page.locator('[data-coin="warrior_priest"]').first.click()
    page.locator('[data-group="bolster"]').click()
    expect(page.locator('[data-pos="0,0"] .stack-number')).to_have_text("2")
    expect(page.locator("#action-dialog")).not_to_be_visible()
    # Give back the turn through a legal opponent pass, then test board selection.
    rooms = app.extensions["rooms"]
    with rooms.room(seat["code"]) as room:
        from warchest import apply_action, deserialize, Action
        state, _ = apply_action(deserialize(room["state"]), Action("pass", "royal"))
        room["state"] = serialize(state)
        room["revision"] += 1
    expect(page.locator("#turn-banner")).to_contain_text("轮到你")
    page.locator('[data-coin="warrior_priest"]').click()
    page.locator('[data-group="maneuver"]').click()
    expect(page.locator(".hex.available")).to_have_count(6)
    page.locator('[data-pos="1,0"]').click()
    expect(page.locator('[data-pos="1,0"] .stack-number')).to_have_text("2")
    expect(page.locator('[data-pos="0,0"] .unit-token')).to_have_count(0)
    page.close()


def test_priest_chain_and_guard_defense_browsers(live, browser):
    from playwright.sync_api import expect
    from test_base_units import A, B, position
    from warchest import serialize
    app, url = live
    c = app.test_client()
    a = c.post("/api/rooms", json={"name": "牧师"}).get_json()
    b = c.post(f"/api/rooms/{a['code']}/join", json={"name": "卫队"}).get_json()
    s = position(A, B, board=(((0, 0), 0, "warrior_priest", 1), ((1, 0), 1, "royal_guard", 1)),
                 hands=(("warrior_priest",), ("royal",)))
    with app.extensions["rooms"].room(a["code"]) as room:
        room["state"] = serialize(s)
    ca, cb = browser.new_context(), browser.new_context()
    pa, pb = ca.new_page(), cb.new_page()
    for page, seat in ((pa, a), (pb, b)):
        page.add_init_script(f"sessionStorage.setItem('wc.session', {json.dumps(json.dumps(seat))});")
        page.goto(url)
    pa.locator('[data-coin="warrior_priest"]').click()
    pa.locator('[data-group="maneuver"]').click()
    pa.locator('[data-pos="1,0"]').click()
    expect(pb.locator('[data-group="defend_supply"]')).to_be_visible()
    pb.locator('[data-close="action-dialog"]').click()
    pb.locator('#resume-skill').click()
    expect(pb.locator('[data-group="defend_supply"]')).to_be_visible()
    pb.locator('[data-group="defend_supply"]').click()
    expect(pa.locator("#action-dialog")).to_be_visible()
    expect(pa.locator("#action-content")).to_contain_text("皇家币")
    pa.locator('[data-group="pass"]').click()
    expect(pb.locator("#turn-banner")).to_contain_text("轮到你")
    expect(pa.locator('[data-pos="1,0"] .unit-token')).to_be_visible()
    ca.close()
    cb.close()


def test_control_inside_maneuver_and_combat_animation(live, browser):
    from playwright.sync_api import expect
    from test_base_units import A, B, position
    from warchest import serialize
    app, url = live
    c = app.test_client()
    a = c.post('/api/rooms', json={'name': '测试'}).get_json()
    c.post(f"/api/rooms/{a['code']}/join", json={'name': '对手'})
    s = position(A, B, board=(((-2, 0), 0, 'footman', 1), ((-1, 0), 1, 'mercenary', 1)),
                 hands=(('footman', 'footman'), ('royal',)))
    with app.extensions['rooms'].room(a['code']) as room:
        room['state'] = serialize(s)
    page = browser.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.add_init_script(f"sessionStorage.setItem('wc.session', {json.dumps(json.dumps(a))});")
    page.goto(url)
    page.locator('[data-coin="footman"]').first.click()
    expect(page.locator('[data-group="control"]')).to_have_count(0)
    page.locator('[data-group="maneuver"]').click()
    expect(page.locator('[data-pos="-2,0"].controllable')).to_be_visible()
    page.locator('[data-pos="-2,0"]').click()
    with app.extensions['rooms'].room(a['code']) as room:
        from warchest import deserialize, apply_action, Action
        state = deserialize(room['state'])
        assert state.controls[(-2, 0)] == 0
        state, _ = apply_action(state, Action('pass', 'royal'))
        room['state'] = serialize(state)
        room['revision'] += 1
    expect(page.locator('#turn-banner')).to_contain_text('轮到你')
    page.locator('[data-coin="footman"]').click()
    page.locator('[data-group="maneuver"]').click()
    page.locator('[data-pos="-1,0"]').click()
    expect(page.locator('.attack-fx')).to_be_visible()
    expect(page.locator('.hit-fx')).to_be_visible()
    expect(page.locator('[data-pos="-1,0"] .unit-token')).to_have_count(0)
    expect(page.locator('.combat-layer')).to_have_count(0, timeout=4000)
    assert errors == []
    page.close()


def test_ai_room_browser(live, browser):
    from playwright.sync_api import expect
    app, url = live
    app.extensions['rooms'].ai_delay = 0
    page = browser.new_page()
    page.goto(url)
    page.locator('#player-name').fill('练习')
    page.locator('#army-mode').select_option('intro')
    page.locator('#ai-room').click()
    page.locator('#start-ai').click()
    expect(page.locator('#turn-banner')).to_contain_text('轮到你')
    expect(page.locator('#invite-friend')).to_have_count(0)
    page.locator('.hand-coin').first.click()
    page.locator('[data-group="pass"]').click()
    expect(page.locator('#turn-banner')).to_contain_text('轮到你', timeout=6000)
    expect(page.locator('.unit-token')).to_have_count(1)
    page.close()


@pytest.mark.parametrize('width,height', [(1440, 900), (1366, 768), (1024, 768), (820, 1180), (390, 844), (375, 667)])
def test_game_fits_viewport(live, browser, width, height):
    from playwright.sync_api import expect
    app, url = live
    c = app.test_client()
    seat = c.post('/api/rooms', json={'name': '布局测试', 'mode': 'intro'}).get_json()
    c.post(f"/api/rooms/{seat['code']}/join", json={'name': '对手'})
    page = browser.new_page(viewport={'width': width, 'height': height})
    page.add_init_script(f"sessionStorage.setItem('wc.session', {json.dumps(json.dumps(seat))});")
    page.goto(url)
    expect(page.locator('.hand-coin')).to_have_count(3)
    def fits():
        assert page.evaluate('document.documentElement.scrollWidth') <= width
        assert page.evaluate('document.documentElement.scrollHeight') <= height
        for selector in ['#board', '.hand-row', '#turn-banner']:
            bounds = page.locator(selector).bounding_box()
            assert bounds['y'] >= 0 and bounds['y'] + bounds['height'] <= height
        assert page.locator('#board').bounding_box()['height'] >= 200
    fits()
    if width <= 900:
        page.locator('#toggle-room').click()
        expect(page.locator('.room-code')).to_be_visible()
        page.locator('#room-sidebar [data-close-sidebar]').click()
        page.locator('#toggle-info').click()
        expect(page.locator('#unit-detail')).to_be_visible()
        expect(page.locator('#battle-log')).to_be_visible()
        page.locator('#info-sidebar [data-close-sidebar]').click()
        fits()
    # Choosing a board destination must keep the hand and decision controls visible.
    page.locator('.hand-coin').filter(has=page.locator('.coin:not(.royal)')).first.click()
    page.locator('[data-group="deploy"]').click()
    expect(page.locator('#decision-strip')).to_be_visible()
    fits()
    page.screenshot(path=f'/tmp/warchest-layout-{width}-{height}.png')
    page.close()


def test_desktop_piece_readability(live, browser):
    from playwright.sync_api import expect
    from test_base_units import A, B, position
    from warchest import serialize
    app, url = live
    c = app.test_client()
    seat = c.post('/api/rooms', json={'name': '辨识测试'}).get_json()
    c.post(f"/api/rooms/{seat['code']}/join", json={'name': '对手'})
    with app.extensions['rooms'].room(seat['code']) as room:
        room['state'] = serialize(position(A, B, board=(((0, 0), 0, 'warrior_priest', 2),),
                                          hands=(('warrior_priest',), ('royal',))))
    page = browser.new_page(viewport={'width': 1366, 'height': 768})
    page.add_init_script(f"sessionStorage.setItem('wc.session', {json.dumps(json.dumps(seat))});")
    page.goto(url)
    expect(page.locator('.unit-token')).to_have_count(1)
    assert page.locator('.token-base').bounding_box()['width'] >= 55
    assert page.locator('.unit-token .icon').bounding_box()['width'] >= 30
    assert page.locator('.unit-label').bounding_box()['height'] >= 10
    assert page.locator('#board').bounding_box()['height'] >= 540
    assert page.evaluate('document.documentElement.scrollHeight') <= 768
    page.screenshot(path='/tmp/warchest-readable-desktop.png')
    page.close()


def test_host_selects_expansions_and_both_armies_then_friend_joins(live,browser):
    from playwright.sync_api import expect
    app,url=live
    ca,cb=browser.new_context(viewport={'width':1440,'height':900}),browser.new_context()
    a,b=ca.new_page(),cb.new_page(); errors=[]
    a.on('pageerror',lambda e:errors.append(str(e)))
    a.goto(url); a.locator('#player-name').fill('扩展房主')
    a.locator('#configure-armies').click()
    a.locator('[data-expansion="nobility"]').check(); a.locator('[data-expansion="siege"]').check()
    a.locator('#setup-mode').select_option('custom')
    for _ in range(4): a.locator('[data-remove^="0:"]').first.click()
    for unit in ('bannerman','bishop','earl','herald'): a.locator(f'[data-pick="{unit}"]').click()
    a.locator('[data-side="1"]').click()
    for _ in range(4): a.locator('[data-remove^="1:"]').first.click()
    for unit in ('sapper','siege_tower','trebuchet','war_wagon'): a.locator(f'[data-pick="{unit}"]').click()
    expect(a.locator('[data-pick="bishop"]')).to_be_disabled()
    a.locator('#save-setup').click()
    expect(a.locator('#setup-summary')).to_contain_text('贵族')
    a.locator('#create-room').click(); expect(a.locator('.room-code')).to_be_visible()
    code=a.locator('.room-code').inner_text()
    b.goto(f'{url}/?room={code}'); b.locator('#join-name').fill('扩展好友'); b.locator('#join-form button').click()
    expect(a.locator('#turn-banner')).to_contain_text('轮到你')
    expect(a.locator('.fort-ring')).to_have_count(4)
    expect(a.locator('#show-decrees')).to_be_visible()
    a.locator('#show-decrees').click(); expect(a.locator('.decree-card')).to_have_count(3)
    a.locator('#general-dialog .dialog-close').click()
    expect(a.locator('#self-zone [data-unit="herald"]')).to_be_visible()
    expect(b.locator('#self-zone [data-unit="trebuchet"]')).to_be_visible()
    assert not errors
    ca.close();cb.close()


def test_expansion_proclaim_and_spy_continue_in_browser(live,browser):
    from playwright.sync_api import expect
    from warchest import serialize
    from test_expansions import position
    app,url=live; context=browser.new_context(viewport={'width':1280,'height':800}); page=context.new_page()
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(url);page.locator('#player-name').fill('法令测试');page.locator('#create-room').click()
    expect(page.locator('.room-code')).to_be_visible();code=page.locator('.room-code').inner_text()
    app.test_client().post(f'/api/rooms/{code}/join',json={'name':'对手'})
    with app.extensions['rooms'].room(code) as room:
        room['state']=serialize(position(('earl',),hands=(('royal',),('archer','archer','royal'))));room['revision']+=1
    page.reload();expect(page.locator('#turn-banner')).to_contain_text('轮到你')
    page.locator('[data-coin="royal"]').click();page.locator('[data-group="proclaim"]').click()
    page.locator('#action-dialog .action-option').filter(has_text='侦察').click()
    expect(page.locator('[data-group="spy"]')).to_be_visible();page.locator('[data-group="spy"]').click()
    expect(page.locator('[data-group="spy_discard"]')).to_be_visible()
    expect(page.locator('.spy-hand')).to_contain_text('弓箭手、弓箭手、皇家币')
    page.locator('[data-group="spy_discard"]').click()
    expect(page.locator('#action-dialog')).to_contain_text('弓箭手')
    page.locator('#action-dialog .action-option').filter(has_text='弓箭手').click()
    expect(page.locator('#turn-banner')).to_contain_text('对手正在思考')
    assert not errors
    context.close()
