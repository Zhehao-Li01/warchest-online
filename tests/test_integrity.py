from copy import deepcopy
import json
from pathlib import Path
import random
import subprocess
import sys

import pytest

from warchest import Action, apply_action, deserialize, legal_actions, new_game, observe, serialize, validate_state
from warchest.ai import choose_action
from warchest.engine import visible_events
from warchest.recording import append_step, new_record, replay_states
from warchest.serialization import state_digest


def test_hidden_information_invariant():
    a = new_game(4)
    b = deepcopy(a)
    # Swap two opponent coins between hidden zones; public knowledge is unchanged.
    b.players[1].hand[0], b.players[1].bag[0] = b.players[1].bag[0], b.players[1].hand[0]
    b.players[0].bag.reverse()  # Even one's own draw order is secret.
    assert observe(a, 0) == observe(b, 0)
    assert legal_actions(a) == legal_actions(b)
    view = observe(a, 0)
    assert "seed" not in view and "rng_state" not in view
    assert "bag" not in view["players"][0]
    view["players"][0]["supply"].clear()
    validate_state(a)  # Observation contains no mutable aliases.


def test_dark_payment_observation_and_events(position):
    state = position(hands=(("swordsman", "pikeman"), ("royal",)))
    a, ea = apply_action(state, Action("recruit", "swordsman", recruit="crossbowman"))
    b, eb = apply_action(state, Action("recruit", "pikeman", recruit="crossbowman"))
    assert observe(a, 1) == observe(b, 1)
    assert visible_events(ea, 1) == visible_events(eb, 1)
    assert observe(a, 0) != observe(b, 0)
    assert observe(a, 1)["players"][0]["discard"] == [None, "crossbowman"]
    assert a.players[0].hand != b.players[0].hand
    assert legal_actions(a) == legal_actions(b)  # B is now acting.


def test_rng_separate_from_agent():
    a = new_game(100)
    b = new_game(100)
    rng = random.Random(99)
    actions = legal_actions(a)
    for _ in range(20):
        choose_action(observe(a, 0, include_history=False), actions, rng)
    assert serialize(a) == serialize(b)


def test_serialization_and_deterministic_continuation():
    a = new_game(10)
    rng = random.Random(22)
    for _ in range(30):
        a, _ = apply_action(a, rng.choice(legal_actions(a)))
    b = deserialize(serialize(a))
    assert serialize(a) == serialize(b)
    for _ in range(40):
        if a.winner is not None:
            break
        action = rng.choice(legal_actions(a))
        a, ea = apply_action(a, action)
        b, eb = apply_action(b, action)
        assert a == b and ea == eb


def test_replay_and_tamper_detection():
    state = new_game(3)
    record = new_record(3)
    rng = random.Random(44)
    for _ in range(20):
        action = rng.choice(legal_actions(state))
        state, events = apply_action(state, action)
        append_step(record, action, state, events)
    loaded = json.loads(json.dumps(record))
    assert list(replay_states(loaded))[-1][0] == state
    loaded["steps"][4]["digest"] = "tampered"
    with pytest.raises(ValueError, match="第 5 步"):
        list(replay_states(loaded))
    loaded = deepcopy(record)
    loaded["steps"][0]["events"] = []
    with pytest.raises(ValueError, match="事件"):
        list(replay_states(loaded))


@pytest.mark.parametrize("field,value", [("format", 99), ("version", "future")])
def test_unknown_save_versions_rejected(field, value):
    data = json.loads(serialize(new_game(0)))
    data[field] = value
    with pytest.raises(ValueError):
        deserialize(json.dumps(data))


def test_corrupt_save_rejected():
    data = json.loads(serialize(new_game(0)))
    data["players"][0]["supply"]["swordsman"] = -1
    with pytest.raises(ValueError):
        deserialize(json.dumps(data))


@pytest.mark.parametrize("seed", range(10))
def test_random_trajectories_preserve_invariants(seed):
    state = new_game(seed)
    rng = random.Random(10000 + seed)
    for _ in range(100):
        if state.winner is not None:
            break
        before = state_digest(state)
        action = choose_action(observe(state, state.current, include_history=False), legal_actions(state), rng)
        result, _ = apply_action(state, action)
        assert state_digest(state) == before
        validate_state(result)
        state = result


def test_complete_example():
    path = Path(__file__).resolve().parents[1] / "examples" / "intro-win.json"
    record = json.loads(path.read_text())
    states = list(replay_states(record))
    assert record["status"] == "finished"
    assert states[-1][0].winner == 0
    for state, _ in states:
        validate_state(state)


def cli(*args, input=None):
    return subprocess.run([sys.executable, "-m", "warchest", *args], input=input,
                          text=True, capture_output=True, timeout=30)


def test_cli_save_resume_help_and_invalid_input(tmp_path):
    path = str(tmp_path / "record.json")
    result = cli("play", "--output", path, input="wrong\n0\nhelp\nsave\nquit\n")
    assert result.returncode == 0, result.stderr
    assert "请输入有效行动编号" in result.stdout
    assert "弩手" in result.stdout
    assert json.loads(Path(path).read_text())["status"] == "aborted"
    assert cli("play", "--load", path, "--output", path, input="quit\n").returncode == 0
    assert cli("replay", path, "--view", "B").returncode == 0


def test_cli_truncation_and_arguments(tmp_path):
    path = str(tmp_path / "report.json")
    result = cli("simulate", "--games", "2", "--max-actions", "1", "--output", path)
    assert result.returncode == 0
    report = json.loads(Path(path).read_text())
    assert report["summary"] == {"truncated": 2}
    assert all(r["winner"] is None for r in report["results"])
    assert cli("simulate", "--games", "0").returncode != 0


def test_cli_replay_view_does_not_print_private_state(tmp_path):
    path = str(tmp_path / "record.json")
    cli("play", "--output", path, input="quit\n")
    result = cli("replay", path, "--view", "B")
    assert "rng_state" not in result.stdout and "draw_coin" not in result.stdout
    assert "暗牌" in result.stdout
