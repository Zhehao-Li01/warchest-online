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
    expect(page.locator("[data-encyclopedia]")).to_have_count(47)
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
    seat = client.post("/api/rooms", json={"name": "牧师玩家", "mode": "intro"}).get_json()
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
    a = c.post("/api/rooms", json={"name": "牧师", "mode": "intro"}).get_json()
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
    a = c.post('/api/rooms', json={'name': '测试', 'mode': 'intro'}).get_json()
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
    expect(page.locator('#ai-level')).to_have_value('random')
    expect(page.locator('#ai-level option')).to_have_count(2)
    page.locator('#start-ai').click()
    expect(page.locator('#turn-banner')).to_contain_text('轮到你')
    expect(page.locator('#invite-friend')).to_have_count(0)
    page.locator('.hand-coin').first.click()
    with page.expect_response(lambda r: r.request.method == 'GET' and '/api/rooms/' in r.url
                              and r.status == 200 and r.json().get('revision', 0) >= 2, timeout=15000):
        page.locator('[data-group="pass"]').click()
    expect(page.locator('#turn-banner')).to_contain_text('轮到你', timeout=6000)
    expect(page.locator('#seats-container')).to_contain_text('随机 AI')
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
    seat = c.post('/api/rooms', json={'name': '辨识测试', 'mode': 'intro'}).get_json()
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


@pytest.mark.parametrize('first', [0, 1])
def test_default_bp_two_browsers_mobile_reload_and_start(live, browser, first):
    from playwright.sync_api import expect
    app, url = live
    contexts = [browser.new_context(viewport={'width':1440,'height':900}),
                browser.new_context(viewport={'width':390,'height':844}, is_mobile=True, has_touch=True)]
    pages = [context.new_page() for context in contexts]
    errors = []
    for page in pages:
        page.on('pageerror', lambda e: errors.append(str(e)))
    a, b = pages
    a.goto(url)
    expect(a.locator('#army-mode')).to_have_value('bp')
    a.locator('#player-name').fill('BP 房主')
    a.locator('#configure-armies').click()
    expect(a.locator('#setup-mode')).to_have_value('bp')
    a.locator('[data-expansion="shock"]').check()
    a.locator('[data-expansion="base"]').uncheck()
    a.locator('#save-setup').click()
    expect(a.locator('#setup-error')).to_contain_text('至少需要 10 种')
    a.locator('[data-expansion="nobility"]').check()
    a.locator('[data-expansion="siege"]').check()
    a.locator('#save-setup').click()
    expect(a.locator('#setup-summary')).not_to_contain_text('基础版')
    a.locator('#create-room').click()
    expect(a.locator('#draft-panel')).to_be_visible()
    expect(a.locator('[data-draft-unit]')).to_have_count(10)
    expect(a.locator('.draft-decrees li')).to_have_count(3)
    expect(a.locator('.draft-map')).to_be_visible()
    from warchest.units import UNITS
    for card in a.locator('[data-draft-unit]').all():
        unit = card.get_attribute('data-draft-unit')
        expect(card.locator('.draft-coin-count')).to_have_text(f'共 {UNITS[unit].coins} 枚币')
    expect(a.locator('#confirm-draft')).to_be_disabled()
    code = a.locator('.room-code').inner_text()
    with app.extensions['rooms'].room(code) as room:
        room['draft']['first'] = first
        room['revision'] += 1
    b.goto(f'{url}/?room={code}')
    b.locator('#join-name').fill('BP 好友')
    b.locator('#join-form button').click()
    expect(b.locator('#draft-panel')).to_be_visible()
    assert b.evaluate('document.documentElement.scrollWidth') <= 390
    b.screenshot(path=f'/tmp/warchest-bp-mobile-{first}.png')
    a.screenshot(path=f'/tmp/warchest-bp-desktop-{first}.png')
    picks = [[], []]
    phases = [(0,'Ban',1),(1,'Ban',1),(0,'Pick',1),(1,'Pick',2),(0,'Pick',2),(1,'Pick',2),(0,'Pick',1)]
    for step, (relative, kind, count) in enumerate(phases):
        who = first ^ relative
        actor, other = pages[who], pages[1-who]
        label = f"{'先手' if relative == 0 else '后手'} {kind} {count}"
        expect(actor.locator('.draft-phases [aria-current]')).to_have_text(label)
        expect(other.locator('.draft-phases [aria-current]')).to_have_text(label)
        expect(other.locator('[data-draft-unit]:enabled')).to_have_count(0)
        expect(actor.locator('#confirm-draft')).to_be_disabled()
        with app.extensions['rooms'].room(code) as room:
            units = app.extensions['rooms'].draft_available(room['draft'])[:count]
        for index, unit in enumerate(units):
            actor.locator(f'[data-draft-unit="{unit}"]').click()
            if index+1 < count:
                expect(actor.locator('#confirm-draft')).to_be_disabled()
        expect(actor.locator('#confirm-draft')).to_be_enabled()
        actor.locator('#confirm-draft').click()
        if kind == 'Pick':
            picks[who].extend(units)
        if step == 2:
            # Persist committed bans and picks across browser refresh.
            actor.reload()
            expect(actor.locator(f'[data-draft-roster="{who}"]')).to_contain_text('已选 1/4')
    for side, page in enumerate(pages):
        expect(page.locator('#draft-panel')).not_to_be_visible()
        expect(page.locator('#board')).to_be_visible()
        for unit in picks[side]:
            expect(page.locator(f'#self-zone [data-unit="{unit}"]')).to_be_visible()
    expect(pages[first].locator('#turn-banner')).to_contain_text('轮到你')
    pages[first].locator('.hand-coin').first.click()
    pages[first].locator('[data-group="pass"]').click()
    expect(pages[1-first].locator('#turn-banner')).to_contain_text('轮到你')
    assert not errors
    for context in contexts:
        context.close()


def test_opponent_action_notice_centered_private_and_not_replayed(live, browser):
    from playwright.sync_api import expect
    from warchest import new_game, serialize
    app, url = live
    c = app.test_client()
    a = c.post('/api/rooms', json={'name':'红方','mode':'intro'}).get_json()
    b = c.post(f"/api/rooms/{a['code']}/join", json={'name':'蓝方'}).get_json()
    with app.extensions['rooms'].room(a['code']) as room:
        room['state'] = serialize(new_game(2))
    contexts = [browser.new_context(viewport={'width':1440,'height':900}),
                browser.new_context(viewport={'width':390,'height':844}, is_mobile=True, has_touch=True)]
    pages = []
    errors = []
    for context, seat in zip(contexts, (a,b)):
        context.add_init_script(f"sessionStorage.setItem('wc.session', {json.dumps(json.dumps(seat))});")
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url)
        expect(page.locator('#save-status')).to_contain_text('局面已自动保存')
        pages.append(page)
    pa,pb = pages
    pa.locator('[data-coin="swordsman"]').first.click()
    pa.locator('[data-group="deploy"]').click()
    pa.locator('.hex.available').first.click()
    notice = pb.locator('#opponent-notice')
    expect(notice).to_have_class('opponent-notice visible')
    expect(notice.locator('strong')).to_have_text('对手部署')
    expect(notice.locator('span')).to_have_text('剑士')
    expect(pa.locator('#opponent-notice')).not_to_have_class('opponent-notice visible')
    box, field = notice.bounding_box(), pb.locator('.battlefield').bounding_box()
    assert abs(box['x']+box['width']/2 - field['x']-field['width']/2) < 2
    assert abs(box['y']+box['height']/2 - field['y']-field['height']/2) < 8
    assert notice.evaluate('el => getComputedStyle(el).pointerEvents') == 'none'
    assert notice.locator('strong').evaluate('el => parseFloat(getComputedStyle(el).fontSize)') >= 28
    pb.screenshot(path='/tmp/warchest-opponent-notice-mobile.png')
    # The opponent can act immediately; the overlay never blocks game input.
    pb.locator('.hand-coin').first.click()
    pb.locator('[data-group="pass"]').click()
    expect(pa.locator('#opponent-notice strong')).to_have_text('对手跳过行动')
    expect(pa.locator('#opponent-notice span')).to_have_text('暗弃一枚指令币')
    expect(notice).not_to_have_class('opponent-notice visible', timeout=5000)
    # Keep polling after fade-out, then reload: neither should replay old actions.
    pb.wait_for_timeout(1400)
    expect(notice).not_to_have_class('opponent-notice visible')
    pb.reload()
    expect(pb.locator('#save-status')).to_contain_text('局面已自动保存')
    expect(pb.locator('#opponent-notice strong')).to_have_text('')
    assert not errors
    for context in contexts:
        context.close()


@pytest.mark.parametrize('unit,source,other', [('knight','0,0','1,-1'),('pikeman','1,-1','0,0')])
def test_march_selects_unit_before_shared_destination(live, browser, unit, source, other):
    from playwright.sync_api import expect
    from test_expansions import position
    from warchest import serialize
    app,url = live
    client=app.test_client()
    seat=client.post('/api/rooms',json={'name':'行军测试','mode':'intro'}).get_json()
    client.post(f"/api/rooms/{seat['code']}/join",json={'name':'对手'})
    state=position(('knight','pikeman'), board=(((0,0),0,'knight',2),((1,-1),0,'pikeman',2)),
                   decrees=('march','guard','reinforce'))
    with app.extensions['rooms'].room(seat['code']) as room:
        room['state']=serialize(state)
    page=browser.new_page()
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.add_init_script(f"sessionStorage.setItem('wc.session', {json.dumps(json.dumps(seat))});")
    page.goto(url)
    page.locator('[data-coin="royal"]').click()
    page.locator('[data-group="proclaim"]').click()
    # Guard and reinforce are unavailable in this position, so March is automatic.
    expect(page.locator('[data-group="maneuver"]')).to_be_visible()
    page.locator('[data-group="maneuver"]').click()
    expect(page.locator('#turn-banner')).to_contain_text('先选择执行行动的单位')
    expect(page.locator('.hex.available')).to_have_count(2)
    expect(page.locator(f'[data-pos="{source}"].available')).to_be_visible()
    page.locator(f'[data-pos="{source}"]').click()
    expect(page.locator('[data-pos="1,0"].available')).to_be_visible()
    page.locator('[data-pos="1,0"]').click()
    expect(page.locator('[data-pos="1,0"] .unit-token')).to_be_visible()
    expect(page.locator(f'[data-pos="{source}"] .unit-token')).to_have_count(0)
    expect(page.locator(f'[data-pos="{other}"] .unit-token')).to_be_visible()
    with app.extensions['rooms'].room(seat['code']) as room:
        from warchest import deserialize
        assert deserialize(room['state']).board[(1,0)].unit == unit
    assert not errors
    page.close()


@pytest.mark.parametrize('choice', ['拆除堡垒','移动到此格'])
def test_neutral_fort_ui_distinguishes_movement_from_demolition(live, browser, choice):
    from playwright.sync_api import expect
    from test_expansions import position
    from warchest import serialize
    app,url=live;client=app.test_client()
    seat=client.post('/api/rooms',json={'name':'堡垒测试','mode':'intro'}).get_json()
    client.post(f"/api/rooms/{seat['code']}/join",json={'name':'对手'})
    state=position(('pikeman',),board=(((0,-1),0,'pikeman',1),),
                   hands=(('pikeman',),('royal',)),forts=((1,-1),))
    with app.extensions['rooms'].room(seat['code']) as room:
        room['state']=serialize(state)
    page=browser.new_page()
    page.add_init_script(f"sessionStorage.setItem('wc.session', {json.dumps(json.dumps(seat))});")
    page.goto(url)
    page.locator('[data-coin="pikeman"]').click()
    page.locator('[data-group="maneuver"]').click()
    target=page.locator('[data-pos="1,-1"]')
    expect(target.locator('.control-cue')).to_have_text('移入 / 拆堡')
    target.click()
    expect(page.locator('#decision-strip')).to_contain_text('拆除堡垒')
    expect(page.locator('#decision-strip')).to_contain_text('移动到此格')
    page.locator('#decision-strip button').filter(has_text=choice).click()
    if choice=='拆除堡垒':
        expect(page.locator('.fort-ring')).to_have_count(0)
        expect(target.locator('.unit-token')).to_have_count(0)
        expect(page.locator('[data-pos="0,-1"] .unit-token')).to_be_visible()
    else:
        expect(target.locator('.unit-token')).to_be_visible()
        expect(target.locator('.fort-ring')).to_be_visible()
    page.close()


@pytest.mark.parametrize('unit,expanded,destination', [
    ('light_cavalry',False,(1,1)),
    ('light_cavalry',True,(-1,-1)),
    ('light_cavalry',True,(0,0)),
    ('skirmisher',True,(1,1)),
    ('skirmisher',True,(1,-1)),
    ('heavy_cavalry',True,(0,2)),
])
def test_multistep_tactic_selects_only_final_destination(live,browser,unit,expanded,destination):
    from playwright.sync_api import expect
    from warchest import serialize, deserialize, legal_actions
    from test_expansions import position as expanded_position
    from test_base_units import position as base_position
    app,url=live
    board=(((0,0),0,unit,1),((1,0),1,'archer',1))
    hands=((unit,),('royal',))
    if expanded:
        state=expanded_position((unit,),('archer',),board=board,hands=hands,
                                forts=((-1,1),))
    else:
        state=base_position(('light_cavalry','swordsman','pikeman','knight'),
                            ('archer','scout','lancer','cavalry'),board=board,hands=hands)
    actions=[a for a in legal_actions(state) if a.kind=='tactic' and a.path]
    endpoints={a.path[-1] for a in actions}
    routes=[a.path for a in actions if a.path[-1]==destination]
    assert routes
    if unit=='light_cavalry' and destination==(-1,-1):
        assert len(routes)>1  # Multiple equivalent routes must not require a second choice.
    client=app.test_client()
    seat=client.post('/api/rooms',json={'name':'终点选择测试','mode':'intro'}).get_json()
    client.post(f"/api/rooms/{seat['code']}/join",json={'name':'对手'})
    with app.extensions['rooms'].room(seat['code']) as room:
        room['state']=serialize(state)
    page=browser.new_page()
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.add_init_script(f"sessionStorage.setItem('wc.session', {json.dumps(json.dumps(seat))});")
    page.goto(url)
    page.locator(f'[data-coin="{unit}"]').click()
    page.locator('[data-group="tactic"]').click()
    expect(page.locator('#turn-banner')).to_contain_text('点击高亮终点')
    highlighted={tuple(map(int,p.split(','))) for p in page.locator('.hex.available').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.pos)')}
    assert highlighted==endpoints
    if expanded:
        assert (-2,2) not in highlighted  # Cannot pass through the fort at (-1,1).
    page.locator(f'[data-pos="{destination[0]},{destination[1]}"]').click()
    expect(page.locator('#turn-banner')).to_contain_text('对手正在思考')
    expect(page.locator('#decision-strip')).not_to_be_visible()
    with app.extensions['rooms'].room(seat['code']) as room:
        result=deserialize(room['state'])
    assert result.board[destination].unit==unit
    action=next(dict(e.data) for e in reversed(result.history) if e.kind=='action')
    assert tuple(map(tuple,action['path'])) in routes
    assert len(action['path'])==min(map(len,routes))
    assert not errors
    page.close()


def test_lancer_chooses_movement_endpoint_then_attack_target(live,browser):
    from playwright.sync_api import expect
    from test_expansions import position
    from warchest import serialize
    app,url=live;client=app.test_client()
    seat=client.post('/api/rooms',json={'name':'枪骑兵测试','mode':'intro'}).get_json()
    client.post(f"/api/rooms/{seat['code']}/join",json={'name':'对手'})
    state=position(('lancer',),('archer',),board=(((0,0),0,'lancer',1),((3,0),1,'archer',1)),
                   hands=(('lancer',),('royal',)))
    with app.extensions['rooms'].room(seat['code']) as room:
        room['state']=serialize(state)
    page=browser.new_page()
    page.add_init_script(f"sessionStorage.setItem('wc.session', {json.dumps(json.dumps(seat))});")
    page.goto(url)
    page.locator('[data-coin="lancer"]').click()
    page.locator('[data-group="tactic"]').click()
    expect(page.locator('[data-pos="2,0"].available')).to_be_visible()
    page.locator('[data-pos="2,0"]').click()
    expect(page.locator('[data-pos="3,0"].attackable')).to_be_visible()
    page.locator('[data-pos="3,0"]').click()
    expect(page.locator('[data-pos="2,0"] .unit-token')).to_be_visible()
    expect(page.locator('[data-pos="3,0"] .unit-token')).to_have_count(0)
    page.close()


def test_wagon_selects_ally_before_destination(live, browser):
    from playwright.sync_api import expect
    from test_expansions import position
    from warchest import serialize, deserialize
    app, url = live
    client = app.test_client()
    seat = client.post('/api/rooms', json={'name':'战车测试','mode':'intro'}).get_json()
    client.post(f"/api/rooms/{seat['code']}/join", json={'name':'对手'})
    state = position(('war_wagon','saboteur','archer'),
                     board=(((0,0),0,'war_wagon',2),((1,0),0,'saboteur',1),((-1,0),0,'archer',1)),
                     hands=(('war_wagon',),('royal',)))
    with app.extensions['rooms'].room(seat['code']) as room:
        room['state'] = serialize(state)
    page = browser.new_page()
    page.add_init_script(f"sessionStorage.setItem('wc.session', {json.dumps(json.dumps(seat))});")
    page.goto(url)
    page.locator('[data-coin="war_wagon"]').click()
    page.locator('[data-group="tactic"]').click()
    highlighted = page.locator('.hex.available').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.pos)')
    assert set(highlighted) == {'1,0','-1,0'}
    page.locator('[data-pos="1,0"]').click()
    page.locator('[data-pos="2,0"]').click()
    expect(page.locator('[data-pos="2,0"] .unit-token')).to_be_visible()
    with app.extensions['rooms'].room(seat['code']) as room:
        result = deserialize(room['state'])
        assert result.board[(2,0)].unit == 'saboteur'
        assert result.board[(1,0)].unit == 'war_wagon'
        assert (0,0) not in result.board
    page.close()


@pytest.mark.parametrize('width', [1440, 390])
def test_removed_coins_details_both_sides_live_update(live, browser, width):
    from playwright.sync_api import expect
    from warchest import new_game, serialize, deserialize, validate_state
    app, url = live
    client = app.test_client()
    seat = client.post('/api/rooms', json={'name':'明细测试','mode':'intro'}).get_json()
    client.post(f"/api/rooms/{seat['code']}/join", json={'name':'对手'})
    state = new_game(2)
    state.players[0].supply['swordsman'] -= 2
    state.players[0].removed.extend(['swordsman'] * 2)
    state.players[0].supply['pikeman'] -= 1
    state.players[0].removed.append('pikeman')
    validate_state(state)
    with app.extensions['rooms'].room(seat['code']) as room:
        room['state'] = serialize(state)
    page = browser.new_page(viewport={'width':width,'height':900})
    page.add_init_script(f"sessionStorage.setItem('wc.session', {json.dumps(json.dumps(seat))});")
    page.goto(url)
    page.locator('#self-zone [data-removed-player]').click()
    expect(page.locator('#removed-heading')).to_have_text('己方 · 已移除币')
    expect(page.locator('[data-removed-unit="swordsman"] strong')).to_have_text('× 2')
    expect(page.locator('[data-removed-unit="pikeman"] strong')).to_have_text('× 1')
    expect(page.locator('.removed-list li')).to_have_count(2)
    # A reinforcement returns a coin to supply: the open view must not stay stale.
    with app.extensions['rooms'].room(seat['code']) as room:
        state = deserialize(room['state'])
        state.players[0].removed.remove('swordsman')
        state.players[0].supply['swordsman'] += 1
        validate_state(state)
        room['state'] = serialize(state)
        room['revision'] += 1
    expect(page.locator('[data-removed-unit="swordsman"] strong')).to_have_text('× 1')
    page.keyboard.press('Escape')
    expect(page.locator('#removed-dialog')).not_to_be_visible()
    page.locator('#opponent-zone [data-removed-player]').click()
    expect(page.locator('#removed-heading')).to_have_text('对手 · 已移除币')
    expect(page.locator('.removed-empty')).to_have_text('该方尚无已移除的币。')
    page.locator('[data-close="removed-dialog"]').click()
    expect(page.locator('#removed-dialog')).not_to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth') <= width
    page.close()


def community_page(live, browser, state, width=1440):
    from warchest import serialize
    app, url = live
    c = app.test_client()
    seat = c.post('/api/rooms', json={'name':'新扩展测试','mode':'intro'}).get_json()
    c.post(f"/api/rooms/{seat['code']}/join", json={'name':'对手'})
    with app.extensions['rooms'].room(seat['code']) as room:
        room['state'] = serialize(state)
        room['config']['expansions'] = state.extras['enabled']
    page = browser.new_page(viewport={'width':width,'height':1000})
    page.add_init_script(f"sessionStorage.setItem('wc.session', {json.dumps(json.dumps(seat))});")
    page.goto(url)
    return page, seat


@pytest.mark.parametrize('width',[1440,390])
def test_community_rules_sea_board_and_ship_target_choice(live,browser,width):
    from playwright.sync_api import expect
    from test_expansions import position, act
    from warchest import deserialize
    s = position(('longboat','archer'),('marksman',),board=(((0,0),0,'longboat',1),((1,0),0,'archer',1),((0,1),1,'marksman',1)),hands=(('archer','royal'),('marksman',)))
    s = act(s,'move',path=((0,0),))
    # UI seat zero must be the attacking player for this fixture.
    s.current=0
    s.players[0],s.players[1]=s.players[1],s.players[0]
    for stack in s.board.values():stack.owner=1-stack.owner
    for stack in s.extras['underlays'].values():stack['owner']=1-stack['owner']
    page,seat = community_page(live,browser,s,width)
    expect(page.locator('.hex')).to_have_count(49)
    expect(page.locator('.sea-hex')).to_have_count(12)
    expect(page.locator('.transport-label')).to_contain_text('长船')
    page.locator('#board-help').click()
    expect(page.locator('[data-rule]')).to_have_count(8)
    expect(page.locator('[data-rule="mastery"]')).to_contain_text('使者采用当前 v2')
    expect(page.locator('[data-rule="high_seas"]')).to_contain_text('分别选择')
    page.locator('[data-close="general-dialog"]').click()
    page.locator('[data-coin="marksman"]').click()
    page.locator('[data-group="maneuver"]').click()
    page.locator('[data-pos="0,0"]').click()
    expect(page.locator('#decision-strip')).to_contain_text('目标 长船')
    expect(page.locator('#decision-strip')).to_contain_text('目标 弓箭手')
    page.locator('#decision-strip button').filter(has_text='目标 长船').click()
    expect(page.locator('.transport-label')).to_have_count(0)
    expect(page.locator('[data-pos="0,0"] .unit-label')).to_have_text('弓箭手')
    with live[0].extensions['rooms'].room(seat['code']) as room:
        result=deserialize(room['state'])
        assert result.board[(0,0)].unit=='archer'
        assert not result.extras['underlays']
    assert page.evaluate('document.documentElement.scrollWidth') <= width
    page.screenshot(path=f'/tmp/community-transport-{width}.png')
    page.close()


def test_apprentice_copy_mode_and_ranged_tactic_in_browser(live,browser):
    from playwright.sync_api import expect
    from test_expansions import position
    from warchest import deserialize
    s = position(('apprentice','archer'),('swordsman',),board=(((0,0),0,'apprentice',1),((0,1),0,'archer',1),((2,0),1,'swordsman',1)),hands=(('apprentice',),('royal',)))
    page,seat=community_page(live,browser,s)
    page.locator('[data-coin="apprentice"]').click()
    page.locator('[data-group="tactic"]').click()
    page.locator('[data-pos="0,1"]').click()
    page.locator('#decision-strip button').filter(has_text='仅战术').click()
    expect(page.locator('#action-dialog')).to_be_visible()
    page.locator('[data-group="tactic"]').click()
    # The only legal ranged target may resolve immediately.
    expect(page.locator('[data-pos="2,0"] .unit-token')).to_have_count(0)
    with live[0].extensions['rooms'].room(seat['code']) as room:
        state=deserialize(room['state']);assert not state.extras['copies']
    page.close()


def test_champion_victory_progress_updates(live,browser):
    from playwright.sync_api import expect
    from test_expansions import position
    s = position(('marksman',),('commander',),board=(((0,0),0,'marksman',1),((1,0),1,'commander',1)),hands=(('marksman',),('royal',)))
    s.controls = dict.fromkeys(s.controls)
    for p in list(s.controls)[:5]:s.controls[p]=0
    page,seat=community_page(live,browser,s)
    expect(page.locator('#self-zone .control-progress')).to_contain_text('5 / 6')
    page.locator('[data-coin="marksman"]').click()
    page.locator('[data-group="maneuver"]').click()
    page.locator('[data-pos="1,0"]').click()
    expect(page.locator('#self-zone .control-progress')).to_contain_text('5 / 5')
    expect(page.locator('#turn-banner')).to_contain_text('你赢得了这场战役')
    page.close()


def test_new_expansions_can_form_bp_pool_without_base(live,browser):
    from playwright.sync_api import expect
    page=browser.new_page()
    page.goto(live[1]);page.locator('#player-name').fill('新扩展 BP')
    page.locator('#configure-armies').click()
    page.locator('[data-expansion="base"]').uncheck()
    for e in ('champions','mastery','high_seas'):page.locator(f'[data-expansion="{e}"]').check()
    page.locator('#save-setup').click();page.locator('#create-room').click()
    expect(page.locator('[data-draft-unit]')).to_have_count(10)
    code=page.locator('.room-code').inner_text()
    with live[0].extensions['rooms'].room(code) as room:
        from warchest.units import UNITS
        assert all(UNITS[u].expansion in ('champions','mastery','high_seas') for u in room['draft']['pool'])
    page.close()


def test_random_ai_supports_expansions_browser(live, browser):
    from playwright.sync_api import expect
    app, url = live
    page = browser.new_page()
    page.goto(url)
    page.locator('#player-name').fill('扩展练习')
    page.locator('#configure-armies').click()
    page.locator('[data-expansion="shock"]').check()
    page.locator('#save-setup').click()
    page.locator('#ai-room').click()
    expect(page.locator('#ai-level option')).to_have_count(2)
    expect(page.locator('#ai-level')).to_have_value('random')
    expect(page.locator('#general-content')).to_contain_text('支持基础版及扩展')
    expect(page.locator('#ai-level option[value="cheat_mcts"]')).to_have_js_property('disabled', True)
    page.close()


def test_cheating_ai_choice_and_background_move_browser(live, browser):
    from playwright.sync_api import expect
    app, url = live
    app.extensions['rooms'].ai_delay = 0
    app.extensions['rooms'].cheat_mcts_options = dict(simulations=0)
    page = browser.new_page()
    page.goto(url)
    page.locator('#player-name').fill('明牌练习')
    page.locator('#army-mode').select_option('intro')
    page.locator('#ai-room').click()
    expect(page.locator('#general-content')).to_contain_text('知道双方当前手牌')
    page.locator('#ai-level').select_option('cheat_mcts')
    page.locator('#start-ai').click()
    expect(page.locator('#seats-container')).to_contain_text('作弊 MCTS AI')
    page.locator('.hand-coin').first.click()
    with page.expect_response(lambda r: r.request.method == 'GET' and '/api/rooms/' in r.url
                              and r.status == 200 and r.json().get('revision', 0) >= 2):
        page.locator('[data-group="pass"]').click()
    expect(page.locator('#turn-banner')).to_contain_text('轮到你')
    page.close()
