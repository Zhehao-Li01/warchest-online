"""Authoritative, persistent two-seat rooms. The engine remains web-independent."""
import argparse
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import random
import secrets
import sqlite3
import time
from urllib.parse import urlsplit

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from .ai import choose_action, choose_basic_action
from .presentation import combat_effects
from .board import HEXES
from .engine import apply_action, legal_actions, new_game, observe, validate_state, visible_events
from .serialization import deserialize, serialize
from .units import ARMIES, UNITS, EXPANSIONS, unit_pool, unit_family
from .expansions import DECREES


class RoomError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def clean_name(value):
    if not isinstance(value, str):
        raise RoomError("请输入昵称")
    value = "".join(c for c in value.strip() if c.isprintable())
    if not 1 <= len(value) <= 16:
        raise RoomError("昵称需要 1–16 个字符")
    return value


class Rooms:
    ai_delay = 0.65

    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS rooms (code TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @contextmanager
    def room(self, code):
        if not re.fullmatch(r"[A-Z2-9]{6}", code):
            raise RoomError("房间号无效", 404)
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT payload FROM rooms WHERE code=?", (code,)).fetchone()
            if row is None:
                raise RoomError("没有找到这个房间，请检查房间号", 404)
            room = json.loads(row[0])
            yield room
            conn.execute("UPDATE rooms SET payload=? WHERE code=?", (json.dumps(room), code))

    @staticmethod
    def fresh_state(mode, config=None):
        seed = secrets.randbits(63)
        config = config or {"expansions": ["base"]}
        enabled = config["expansions"]
        if mode == "custom":
            return new_game(seed, config["armies"], initiative=config.get("initiative", 0), expansions=enabled)
        if mode == "random":
            rng = random.Random(seed ^ 0x5743)
            pool = unit_pool(enabled)
            rng.shuffle(pool)
            units, families = [], set()
            for unit in pool:
                family = unit_family(unit)
                if family not in families:
                    units.append(unit)
                    families.add(family)
                if len(units) == 8: break
            return new_game(seed, (units[:4], units[4:]), initiative=random.Random(seed ^ 0x494E).randrange(2), expansions=enabled)
        return new_game(seed)

    @staticmethod
    def configuration(mode, expansions, armies, initiative):
        enabled = ["base"] if expansions is None else expansions
        if (not isinstance(enabled, list) or not enabled or any(not isinstance(e, str) for e in enabled)
                or len(set(enabled)) != len(enabled) or not set(enabled) <= EXPANSIONS.keys()):
            raise RoomError("扩展选择无效")
        enabled = sorted(set(enabled) | {"base"})
        if mode == "intro": enabled = ["base"]
        if type(initiative) is not int or initiative not in (0, 1):
            raise RoomError("先手设置无效")
        config = {"expansions": enabled, "initiative": initiative}
        if mode == "custom":
            if (not isinstance(armies, list) or len(armies) != 2
                    or any(not isinstance(a, list) or len(a) != 4 for a in armies)
                    or any(not isinstance(u, str) or u not in UNITS for a in armies for u in a)):
                raise RoomError("请为双方各选择四个兵种")
            units = armies[0] + armies[1]
            if len(set(unit_family(u) for u in units)) != 8:
                raise RoomError("兵种不能重复，替代版本与原兵种不能同时入选")
            if any(UNITS[u].expansion not in enabled for u in units):
                raise RoomError("阵容包含未启用扩展的兵种")
            config["armies"] = armies
        return config

    def create(self, name, mode="random", opponent="human", ai_level="basic", expansions=None, armies=None, initiative=0):
        name = clean_name(name)
        if mode not in ("random", "intro", "custom"):
            raise RoomError("未知阵容模式")
        if opponent not in ("human", "ai") or ai_level not in ("basic", "random"):
            raise RoomError("未知对手类型或 AI 难度")
        config = self.configuration(mode, expansions, armies, initiative)
        token = secrets.token_urlsafe(32)
        bot = {"name": "基础 AI" if ai_level == "basic" else "随机 AI", "hash": "",
               "seen": 0, "bot": True} if opponent == "ai" else None
        room = {"code": "", "state": serialize(self.fresh_state(mode, config)), "mode": mode, "config": config,
                "seats": [{"name": name, "hash": token_hash(token), "seen": time.time()}, bot],
                "opponent": opponent, "ai_level": ai_level, "ai_seed": secrets.randbits(63),
                "ai_ready_at": time.time() + self.ai_delay, "effects": [],
                "revision": 0, "resigned": None, "rematch": [], "game": 1}
        with self.connection() as conn:
            while True:
                code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
                room["code"] = code
                try:
                    conn.execute("INSERT INTO rooms VALUES (?, ?)", (code, json.dumps(room)))
                    break
                except sqlite3.IntegrityError:
                    continue
        return {"code": code, "token": token, "player": 0}

    def join(self, code, name):
        name = clean_name(name)
        token = secrets.token_urlsafe(32)
        with self.room(code) as room:
            if room["seats"][1] is not None:
                raise RoomError("房间已有两位玩家，请回到自己的原标签页或创建新房间", 409)
            room["seats"][1] = {"name": name, "hash": token_hash(token), "seen": time.time()}
            room["revision"] += 1
        return {"code": code, "token": token, "player": 1}

    @staticmethod
    def authenticate(room, token):
        if not token or len(token) > 128:
            raise RoomError("座位凭证已失效，请重新进入房间", 401)
        for index, seat in enumerate(room["seats"]):
            if seat and not seat.get("bot") and secrets.compare_digest(seat["hash"], token_hash(token)):
                seat["seen"] = time.time()
                return index
        raise RoomError("无权访问此座位", 401)

    @staticmethod
    def snapshot(room, who):
        state = deserialize(room["state"])
        view = observe(state, who, include_history=False)
        view["history"] = visible_events(state.history[-160:], who)
        winner = 1 - room["resigned"] if room["resigned"] is not None else state.winner
        status = "finished" if winner is not None else ("playing" if room["seats"][1] else "waiting")
        actions = legal_actions(state) if status == "playing" and state.current == who else []
        return {"room": room["code"], "revision": room["revision"], "game": room["game"], "mode": room["mode"],
                "config": room.get("config", {"expansions": ["base"]}),
                "opponent": room.get("opponent", "human"), "ai_level": room.get("ai_level", "basic"),
                "effects": room.get("effects", []),
                "status": status, "winner": winner, "resigned": room["resigned"],
                "rematch": room["rematch"], "view": view,
                "seats": [{"name": s["name"], "online": bool(s.get("bot")) or time.time() - s["seen"] < 12, "bot": bool(s.get("bot"))} if s else None
                          for s in room["seats"]],
                "actions": [{"id": i, **asdict(a)} for i, a in enumerate(actions)]}

    def commit_action(self, room, state, action):
        result, events = apply_action(state, action)
        validate_state(result)
        room["state"] = serialize(result)
        room["revision"] += 1
        effects = combat_effects(state, action, events)
        if effects:
            room.setdefault("effects", []).append({"revision": room["revision"], "items": effects})
            room["effects"] = room["effects"][-24:]
        room["ai_ready_at"] = time.time() + self.ai_delay

    def advance_ai(self, room):
        if (room.get("opponent") != "ai" or room["resigned"] is not None
                or time.time() < room.get("ai_ready_at", 0)):
            return
        state = deserialize(room["state"])
        if state.winner is not None or state.current != 1:
            return
        # One committed decision per tick, including skill continuations and defense.
        # Reading from two tabs cannot double-play: the room transaction and delay guard it.
        actions = legal_actions(state)
        chooser = choose_basic_action if room.get("ai_level") == "basic" else choose_action
        rng = random.Random(room["ai_seed"] ^ (room["game"] << 32) ^ room["revision"])
        action = chooser(observe(state, 1, include_history=False), actions, rng)
        self.commit_action(room, state, action)

    def get(self, code, token):
        with self.room(code) as room:
            who = self.authenticate(room, token)
            self.advance_ai(room)
            return self.snapshot(room, who)

    def change(self, code, token, command, data):
        with self.room(code) as room:
            who = self.authenticate(room, token)
            same_game_vote = command == "rematch" and data.get("game") == room["game"]
            if not same_game_vote and (type(data.get("revision")) is not int or data["revision"] != room["revision"]):
                raise RoomError("局面已经更新，请按最新棋盘重新选择", 409)
            state = deserialize(room["state"])
            finished = room["resigned"] is not None or state.winner is not None
            if command == "rematch":
                if not finished:
                    raise RoomError("本局尚未结束", 409)
                if who in room["rematch"]:
                    return self.snapshot(room, who)
                if who not in room["rematch"]:
                    room["rematch"].append(who)
                if room.get("opponent") == "ai":
                    room["rematch"] = [0, 1]
                if len(room["rematch"]) == 2:
                    room.update(state=serialize(self.fresh_state(room["mode"], room.get("config"))), resigned=None,
                                rematch=[], game=room["game"] + 1, effects=[],
                                ai_ready_at=time.time() + self.ai_delay)
            else:
                if not room["seats"][1] or finished:
                    raise RoomError("当前不能行动", 409)
                if command == "resign":
                    room["resigned"] = who
                elif command == "actions":
                    if state.current != who:
                        raise RoomError("请等待对手行动", 403)
                    actions = legal_actions(state)
                    index = data.get("action_id")
                    if type(index) is not int or not 0 <= index < len(actions):
                        raise RoomError("行动无效")
                    self.commit_action(room, state, actions[index])
                    return self.snapshot(room, who)
                else:
                    raise RoomError("未知操作", 404)
            room["revision"] += 1
            return self.snapshot(room, who)


def create_app(database="data/rooms.sqlite3"):
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = 8192
    rooms = Rooms(database)
    app.extensions["rooms"] = rooms

    @app.before_request
    def same_origin():
        origin = request.headers.get("Origin")
        if origin and urlsplit(origin).netloc != request.host:
            raise RoomError("不允许跨站请求", 403)

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        )
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(RoomError)
    def room_error(exc):
        return jsonify(error=exc.message), exc.status

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify(error="请求无效" if exc.code == 400 else exc.description), exc.code

    def body():
        value = request.get_json()
        if not isinstance(value, dict):
            raise RoomError("请求格式无效")
        return value

    def token():
        value = request.headers.get("Authorization", "")
        return value[7:] if value.startswith("Bearer ") else ""

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/api/bootstrap")
    def bootstrap():
        return jsonify(expansions=EXPANSIONS, decrees=DECREES, units={key: asdict(u) for key, u in UNITS.items()}, armies=ARMIES,
                       hexes=sorted(HEXES), preview=observe(new_game(7), 0, include_history=False))

    @app.post("/api/rooms")
    def create():
        data = body()
        return jsonify(rooms.create(data.get("name"), data.get("mode", "random"),
                                    data.get("opponent", "human"), data.get("ai_level", "basic"),
                                   data.get("expansions"), data.get("armies"), data.get("initiative", 0))), 201

    @app.post("/api/rooms/<code>/join")
    def join(code):
        return jsonify(rooms.join(code.upper(), body().get("name")))

    @app.get("/api/rooms/<code>")
    def get_room(code):
        return jsonify(rooms.get(code.upper(), token()))

    @app.post("/api/rooms/<code>/<command>")
    def change(code, command):
        return jsonify(rooms.change(code.upper(), token(), command, body()))

    return app


def main():
    parser = argparse.ArgumentParser(description="战争之匣在线对战")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--database", default="data/rooms.sqlite3")
    args = parser.parse_args()
    from waitress import serve
    print(f"战争之匣已启动：http://localhost:{args.port}（局域网请用本机 IP）", flush=True)
    serve(create_app(args.database), host=args.host, port=args.port, threads=8)


if __name__ == "__main__":
    main()
