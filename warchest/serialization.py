"""JSON-only save format; no pickle or executable deserialization."""
from dataclasses import asdict
import hashlib
import json

from .engine import validate_state
from .model import Action, Event, Player, Stack, State, RULES_VERSION

FORMAT_VERSION = 1


def _tuples(value):
    return tuple(_tuples(v) for v in value) if isinstance(value, list) else value


def action_from_dict(data):
    return Action(data["kind"], data["coin"],
                  tuple(tuple(p) for p in data.get("path", ())),
                  tuple(data["target"]) if data.get("target") is not None else None,
                  data.get("recruit"),
                  tuple(data["after"]) if data.get("after") is not None else None,
                  tuple(data["source"]) if data.get("source") is not None else None,
                  data.get("effect"))


def state_dict(state, *, history=True):
    result = {
        "format": FORMAT_VERSION, "version": state.version, "seed": state.seed,
        "players": [asdict(p) for p in state.players],
        "board": [{"pos": p, **asdict(s)} for p, s in sorted(state.board.items())],
        "controls": [{"pos": p, "owner": owner} for p, owner in sorted(state.controls.items())],
        "rng_state": state.rng_state, "round": state.round, "current": state.current,
        "initiative": state.initiative, "initiative_claimed": state.initiative_claimed,
        "winner": state.winner,
        "pending": state.pending, "turn_owner": state.turn_owner,
        "history": [asdict(e) for e in state.history] if history else [],
    }

    if state.extras:
        result["extras"] = state.extras
    return result


def serialize(state):
    return json.dumps(state_dict(state), ensure_ascii=False, sort_keys=True)


def deserialize(payload):
    try:
        data = json.loads(payload)
        if data["format"] != FORMAT_VERSION or data["version"] not in (RULES_VERSION, "expansions-1"):
            raise ValueError("不支持的存档版本")
        players = [Player(p["supply"], p["bag"], p["hand"],
                          [tuple(d) for d in p["discard"]], p["removed"])
                   for p in data["players"]]
        for task in data.get("pending", []):
            if data["version"] == RULES_VERSION and task.get("source") is not None:
                task["source"] = tuple(task["source"])
        state = State(
            seed=data["seed"], players=players,
            board={tuple(s["pos"]): Stack(s["owner"], s["unit"], s["count"]) for s in data["board"]},
            controls={tuple(c["pos"]): c["owner"] for c in data["controls"]},
            rng_state=_tuples(data["rng_state"]), round=data["round"], current=data["current"],
            initiative=data["initiative"], initiative_claimed=data["initiative_claimed"],
            winner=data["winner"],
            history=tuple(Event(e["kind"], _tuples(e["data"]), e["visible_to"]) for e in data["history"]),
            version=data["version"],
            pending=data.get("pending", []), turn_owner=data.get("turn_owner"),
            extras=data.get("extras", {}),
        )
        validate_state(state)
        return state
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError("存档结构无效") from exc


def state_digest(state):
    # Event deltas are checked separately by replay; omit growing history here.
    data = json.dumps(state_dict(state, history=False), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()
