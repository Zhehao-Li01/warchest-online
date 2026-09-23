"""Trusted local full-information recordings; views are filtered by the CLI."""
from dataclasses import asdict
import json

from .engine import apply_action, new_game
from .model import RULES_VERSION
from .serialization import action_from_dict, state_digest, serialize, deserialize


def new_record(seed, *, armies=None, expansions=None, initiative=0, setup=None):
    state = new_game(seed, armies, initiative, expansions=expansions, setup=setup)
    record = {"format": 1, "rules_version": state.version, "seed": seed,
              "initial_digest": state_digest(state), "steps": [],
              "status": "ongoing", "winner": None}
    if armies is not None or expansions is not None or initiative or setup is not None:
        record["initial_state"] = json.loads(serialize(state))
    return record


def append_step(record, action, state, events):
    record["steps"].append({"action": asdict(action), "digest": state_digest(state),
                            "events": [asdict(e) for e in events]})
    if state.winner is not None:
        record["status"] = "finished"
        record["winner"] = state.winner


def replay_states(record):
    if record.get("format") != 1 or record.get("rules_version") not in (RULES_VERSION, "expansions-1"):
        raise ValueError("不支持的回放版本")
    if record.get("status") not in {"ongoing", "finished", "aborted", "truncated"}:
        raise ValueError("无效的回放状态")
    state = deserialize(json.dumps(record["initial_state"])) if "initial_state" in record else new_game(record["seed"])
    if state.version != record["rules_version"] or state.seed != record["seed"]:
        raise ValueError("回放初始版本或种子不一致")
    if state_digest(state) != record["initial_digest"]:
        raise ValueError("回放初始状态校验失败")
    yield state, ()
    for index, step in enumerate(record["steps"], 1):
        state, events = apply_action(state, action_from_dict(step["action"]))
        if state_digest(state) != step["digest"]:
            raise ValueError(f"回放第 {index} 步状态校验失败")
        if json.dumps([asdict(e) for e in events], sort_keys=True) != json.dumps(step["events"], sort_keys=True):
            raise ValueError(f"回放第 {index} 步事件校验失败")
        yield state, events
    if record.get("winner") != state.winner or (record["status"] == "finished") != (state.winner is not None):
        raise ValueError("回放结局不一致")
