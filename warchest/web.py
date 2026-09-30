"""Authoritative, persistent two-seat rooms. The engine remains web-independent."""
import argparse
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import logging
from pathlib import Path
import re
import random
import secrets
import sqlite3
import time
from threading import Event, Lock, Semaphore, Thread
from urllib.parse import urlsplit

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from .ai import choose_action
from .cheat_mcts import SearchMemory, choose_cheat_mcts_action, MAX_SEARCH_WORKERS
from .presentation import combat_effects
from .board import HEXES, SEA_HEXES
from .engine import apply_action, legal_actions, new_game, observe, validate_state, visible_events
from .serialization import deserialize, serialize
from .units import ARMIES, UNITS, EXPANSIONS, unit_pool, unit_family
from .expansions import DECREES, FORT_LAYOUTS

# Relative to the randomly chosen first player: ban, ban, pick 1/2/2/2/1.
DRAFT_STEPS = ((0, "ban", 1), (1, "ban", 1), (0, "pick", 1),
               (1, "pick", 2), (0, "pick", 2), (1, "pick", 2), (0, "pick", 1))


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
    cheat_mcts_options = dict(num_simulations=5000, rollout_depth=120, workers=MAX_SEARCH_WORKERS)

    def __init__(self, path):
        self.path = str(path)
        self._ai_jobs = {}
        self._ai_memories = {}
        self._ai_jobs_lock = Lock()
        self._ai_slots = Semaphore(2)
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
            self.migrate_ai(room)
            yield room
            conn.execute("UPDATE rooms SET payload=? WHERE code=?", (json.dumps(room), code))

    @staticmethod
    def migrate_ai(room):
        if room.get("opponent") != "ai":
            return
        if room.get("ai_level") == "cheat_mcts":
            room["seats"][1]["name"] = "作弊 MCTS AI"
        else:
            room["ai_level"] = "random"
            room["seats"][1]["name"] = "随机 AI"

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
        enabled = sorted(enabled)
        if mode == "intro": enabled = ["base"]
        required = 10 if mode == "bp" else 8
        if mode != "intro" and len({unit_family(u) for u in unit_pool(enabled)}) < required:
            raise RoomError(f"当前选择的版本兵种不足，{'BP 需要' if mode == 'bp' else '双方阵容需要'}至少 {required} 种不同兵种，请增加扩展或更换组军方式")
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

    @staticmethod
    def draft_turn(draft):
        if draft["step"] == len(DRAFT_STEPS):
            return None, None, 0
        side, kind, count = DRAFT_STEPS[draft["step"]]
        return draft["first"] ^ side, kind, count

    @staticmethod
    def draft_available(draft):
        used = set(sum(draft["bans"] + draft["picks"], []))
        return [u for u in draft["pool"] if u not in used]

    def prepare_game(self, room):
        if room["mode"] != "bp":
            room["state"] = serialize(self.fresh_state(room["mode"], room.get("config")))
            room.pop("draft", None)
            return
        rng = random.Random(secrets.randbits(63))
        pool = unit_pool(room["config"]["expansions"])
        rng.shuffle(pool)
        units, families = [], set()
        for unit in pool:
            family = unit_family(unit)
            if family not in families:
                units.append(unit)
                families.add(family)
            if len(units) == 10:
                break
        room["state"] = None
        room["draft"] = {"pool": units, "first": rng.randrange(2), "step": 0,
                         "bans": [[], []], "picks": [[], []],
                         "setup": {"forts": [list(p) for p in rng.choice(FORT_LAYOUTS)] if "siege" in room["config"]["expansions"] else [],
                                   "decrees": rng.sample(list(DECREES), 3) if "nobility" in room["config"]["expansions"] else []}}

    def commit_draft(self, room, who, units):
        draft = room.get("draft")
        if not draft or room["state"] is not None:
            raise RoomError("当前不在 BP 阶段", 409)
        current, kind, count = self.draft_turn(draft)
        if current != who:
            raise RoomError("请等待对手完成 BP", 403)
        if (not isinstance(units, list) or len(units) != count
                or any(not isinstance(u, str) for u in units)
                or len(set(units)) != count
                or not set(units) <= set(self.draft_available(draft))):
            raise RoomError(f"请从剩余候选兵种中选择 {count} 个不同兵种")
        draft["bans" if kind == "ban" else "picks"][who].extend(units)
        draft["step"] += 1
        if draft["step"] == len(DRAFT_STEPS):
            state = new_game(secrets.randbits(63), draft["picks"], initiative=draft["first"],
                             expansions=room["config"]["expansions"], setup=draft.get("setup"))
            validate_state(state)
            room["state"] = serialize(state)
        room["revision"] += 1
        room["ai_ready_at"] = time.time() + self.ai_delay

    def create(self, name, mode="bp", opponent="human", ai_level="random", expansions=None, armies=None, initiative=0):
        name = clean_name(name)
        if mode not in ("bp", "random", "intro", "custom"):
            raise RoomError("未知阵容模式")
        if opponent not in ("human", "ai") or ai_level not in ("cheat_mcts", "mcts", "basic", "random"):
            raise RoomError("未知对手类型或 AI 难度")
        config = self.configuration(mode, expansions, armies, initiative)
        ai_level = "random" if ai_level in ("basic", "mcts") else ai_level
        if opponent == "ai" and ai_level == "cheat_mcts" and config["expansions"] != ["base"]:
            raise RoomError("作弊 MCTS AI 目前仅支持基础版")
        token = secrets.token_urlsafe(32)
        bot = {"name": "作弊 MCTS AI" if ai_level == "cheat_mcts" else "随机 AI", "hash": "",
               "seen": 0, "bot": True} if opponent == "ai" else None
        room = {"code": "", "mode": mode, "config": config,
                "seats": [{"name": name, "hash": token_hash(token), "seen": time.time()}, bot],
                "opponent": opponent, "ai_level": ai_level, "ai_seed": secrets.randbits(63),
                "ai_ready_at": time.time() + self.ai_delay, "effects": [], "activity": [],
                "revision": 0, "resigned": None, "rematch": [], "game": 1}
        self.prepare_game(room)
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
        state = deserialize(room["state"]) if room["state"] is not None else None
        view = observe(state, who, include_history=False) if state else None
        if view is not None:
            view["history"] = visible_events(state.history[-160:], who)
        winner = 1 - room["resigned"] if room["resigned"] is not None else (state.winner if state else None)
        status = ("finished" if winner is not None else "waiting" if not room["seats"][1]
                  else "drafting" if state is None else "playing")
        actions = legal_actions(state) if status == "playing" and state.current == who else []
        draft = room.get("draft")
        if draft:
            current, kind, count = Rooms.draft_turn(draft)
            draft = {**draft, "current": current, "kind": kind, "count": count,
                     "available": Rooms.draft_available(draft)}
        return {"room": room["code"], "revision": room["revision"], "game": room["game"], "mode": room["mode"],
                "config": room.get("config", {"expansions": ["base"]}),
                "opponent": room.get("opponent", "human"), "ai_level": room.get("ai_level", "random"),
                "effects": room.get("effects", []), "activity": room.get("activity", []),
                "status": status, "winner": winner, "resigned": room["resigned"],
                "rematch": room["rematch"], "view": view, "draft": draft,
                "seats": [{"name": s["name"], "online": bool(s.get("bot")) or time.time() - s["seen"] < 12, "bot": bool(s.get("bot"))} if s else None
                          for s in room["seats"]],
                "actions": [{"id": i, **asdict(a)} for i, a in enumerate(actions)]}

    def commit_action(self, room, state, action):
        result, events = apply_action(state, action)
        validate_state(result)
        room["state"] = serialize(result)
        room["revision"] += 1
        # Only public action events: hidden payment events must never reach this feed.
        for event in events:
            if event.kind == "action" and event.visible_to is None:
                room.setdefault("activity", []).append({"revision": room["revision"], "action": dict(event.data)})
        room["activity"] = room.get("activity", [])[-40:]
        effects = combat_effects(state, action, events)
        if effects:
            room.setdefault("effects", []).append({"revision": room["revision"], "items": effects})
            room["effects"] = room["effects"][-24:]
        room["ai_ready_at"] = time.time() + self.ai_delay

    def advance_ai(self, code, token):
        # Copy the decision inputs in a short transaction; never select an action while
        # holding SQLite's database-wide write lock.
        with self.room(code) as room:
            self.authenticate(room, token)
            if (room.get("opponent") != "ai" or room["resigned"] is not None
                    or time.time() < room.get("ai_ready_at", 0)):
                return
            rng = random.Random(room["ai_seed"] ^ (room["game"] << 32) ^ room["revision"])
            if room["state"] is None:
                current, _, count = self.draft_turn(room["draft"])
                if current == 1:
                    self.commit_draft(room, 1, rng.sample(self.draft_available(room["draft"]), count))
                return
            state = deserialize(room["state"])
            if state.winner is not None or state.current != 1:
                return
            version = (room["game"], room["revision"], room["ai_level"])
            actions = legal_actions(state)
            view = observe(state, 1, include_history=False)
        if version[2] == "cheat_mcts":
            self.start_cheat_search(code, version, state, actions, rng)
            return
        action = choose_action(view, actions, rng)
        self.commit_ai_result(code, version, action)

    def commit_ai_result(self, code, version, action):
        with self.room(code) as room:
            if ((room["game"], room["revision"], room["ai_level"]) != version
                    or room["resigned"] is not None or room.get("opponent") != "ai"
                    or room["state"] is None):
                return
            current = deserialize(room["state"])
            if current.current != 1 or current.winner is not None:
                return
            self.commit_action(room, current, action)

    def cancel_ai_search(self, code):
        with self._ai_jobs_lock:
            job = self._ai_jobs.get(code)
            if job:
                job[1].set()
            for key in list(self._ai_memories):
                if key[0] == code:
                    del self._ai_memories[key]

    def start_cheat_search(self, code, version, state, actions, rng):
        # Polls never wait for search. One job per room and at most two coordinator threads; shared bounded rollout pool.
        with self._ai_jobs_lock:
            old = self._ai_jobs.get(code)
            if old:
                if old[0] != version:
                    old[1].set()
                return
            if not self._ai_slots.acquire(blocking=False):
                return  # Retry on the next poll; no unbounded worker queue.
            key = (code, version[0])
            memory = self._ai_memories.pop(key, None) or SearchMemory()
            for stale in list(self._ai_memories):
                if stale[0] == code:
                    del self._ai_memories[stale]
            self._ai_memories[key] = memory
            while len(self._ai_memories) > 8:
                del self._ai_memories[next(iter(self._ai_memories))]
            cancelled = Event()
            self._ai_jobs[code] = (version, cancelled)
        def run():
            try:
                with self.room(code) as room:
                    if ((room["game"], room["revision"], room["ai_level"]) != version
                            or room["resigned"] is not None):
                        return
                action = choose_cheat_mcts_action(
                    state, actions, rng, player=1, memory=memory, cancelled=cancelled.is_set,
                    **self.cheat_mcts_options)
                if not cancelled.is_set():
                    self.commit_ai_result(code, version, action)
            except Exception:
                logging.getLogger(__name__).exception("AI search failed for room %s", code)
            finally:
                with self._ai_jobs_lock:
                    self._ai_jobs.pop(code, None)
                self._ai_slots.release()
        Thread(target=run, name="cheat-ai-" + code, daemon=True).start()

    def get(self, code, token):
        self.advance_ai(code, token)
        with self.room(code) as room:
            who = self.authenticate(room, token)
            return self.snapshot(room, who)

    def change(self, code, token, command, data):
        with self.room(code) as room:
            who = self.authenticate(room, token)
            same_game_vote = command == "rematch" and data.get("game") == room["game"]
            if not same_game_vote and (type(data.get("revision")) is not int or data["revision"] != room["revision"]):
                raise RoomError("局面已经更新，请按最新棋盘重新选择", 409)
            state = deserialize(room["state"]) if room["state"] is not None else None
            finished = room["resigned"] is not None or (state is not None and state.winner is not None)
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
                    room.update(resigned=None,
                                rematch=[], game=room["game"] + 1, effects=[], activity=[],
                                ai_ready_at=time.time() + self.ai_delay)
                    self.cancel_ai_search(code)
                    self.prepare_game(room)
            else:
                if not room["seats"][1] or finished:
                    raise RoomError("当前不能行动", 409)
                if command == "resign":
                    room["resigned"] = who
                    self.cancel_ai_search(code)
                elif command == "draft":
                    self.commit_draft(room, who, data.get("units"))
                    return self.snapshot(room, who)
                elif command == "actions":
                    if state is None:
                        raise RoomError("请先完成 BP", 409)
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
                       hexes=sorted(HEXES), sea_hexes=sorted(SEA_HEXES), preview=observe(new_game(7), 0, include_history=False))

    @app.post("/api/rooms")
    def create():
        data = body()
        return jsonify(rooms.create(data.get("name"), data.get("mode", "bp"),
                                    data.get("opponent", "human"), data.get("ai_level", "random"),
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
