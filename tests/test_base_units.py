from collections import Counter
from dataclasses import replace
import random

import pytest

from warchest import Action, apply_action, deserialize, legal_actions, new_game, observe, serialize, validate_state
from warchest.model import Stack
from warchest.units import UNITS, BASE_UNITS


def position(a, b, board=(), hands=None, current=0):
    state = new_game(31, (a, b))
    state.board = {pos: Stack(owner, unit, count) for pos, owner, unit, count in board}
    state.current = current
    state.history = ()
    hands = hands or (("royal",), ("royal",))
    for who, player in enumerate(state.players):
        player.hand = list(hands[who])
        player.bag = [] if "royal" in player.hand else ["royal"]
        player.discard = []
        used = Counter(player.hand)
        for stack in state.board.values():
            if stack.owner == who:
                used[stack.unit] += stack.count
        player.supply = {u: UNITS[u].coins - used[u] for u in player.supply}
    validate_state(state)
    return state


A = ("warrior_priest", "footman", "berserker", "marshall")
B = ("royal_guard", "knight", "ensign", "mercenary")


def act(s, a):
    result, _ = apply_action(s, a)
    validate_state(result)
    assert deserialize(serialize(result)) == result
    return result


def test_all_sixteen_and_valid_armies():
    assert len(BASE_UNITS) == 16
    validate_state(new_game(0, (A, B)))
    with pytest.raises(ValueError):
        new_game(0, (A, A))


def test_footman_two_units_and_separate_bolstering():
    s = position(A, B, board=(((0, 0), 0, "footman", 1),), hands=(("footman", "footman"), ("royal",)))
    assert Action("deploy", "footman", target=(-1, -2)) in legal_actions(s)
    s = act(s, Action("deploy", "footman", target=(-1, -2)))
    s = act(s, Action("pass", "royal"))
    assert not any(a.kind == "deploy" for a in legal_actions(s))
    assert len([a for a in legal_actions(s) if a.kind == "bolster"]) == 2
    s = act(s, Action("bolster", "footman", source=(0, 0)))
    assert s.board[(0, 0)].count == 2


def test_footman_tactic_each_unit_once_different_maneuvers():
    s = position(A, B, board=(((-2, 0), 0, "footman", 1), ((0, 0), 0, "footman", 1)),
                 hands=(("footman",), ("royal",)))
    s = act(s, Action("tactic", "footman", source=(-2, 0), effect="control"))
    assert s.current == 0 and s.pending[0]["type"] == "footman"
    assert s.controls[(-2, 0)] == 0
    assert all(a.source == (0, 0) for a in legal_actions(s))
    s = act(s, Action("move", "footman", source=(0, 0), path=((1, 0),)))
    assert s.current == 1 and not s.pending
    assert len(s.players[0].discard) == 1


def test_knight_requires_bolstered_attacker():
    s = position(A, B, board=(((0, 0), 0, "berserker", 1), ((1, 0), 1, "knight", 1)),
                 hands=(("berserker",), ("royal",)))
    assert not any(a.kind == "attack" for a in legal_actions(s))
    s.board[(0, 0)].count += 1
    s.players[0].supply["berserker"] -= 1
    assert Action("attack", "berserker", target=(1, 0)) in legal_actions(s)
    s = act(s, Action("attack", "berserker", target=(1, 0)))
    assert (1, 0) not in s.board


def test_berserker_continuation_discards_stack_not_hand():
    s = position(A, B, board=(((0, 0), 0, "berserker", 3),), hands=(("berserker",), ("royal",)))
    s = act(s, Action("move", "berserker", path=((1, 0),)))
    assert s.current == 0 and s.pending[0]["type"] == "berserk"
    s = act(s, Action("move", "berserker", source=(1, 0), path=((2, 0),)))
    assert s.board[(2, 0)].count == 2
    assert s.players[0].discard == [("berserker", True)] * 2
    s = act(s, Action("finish", "berserker"))
    assert s.current == 1 and not s.pending


def test_berserker_payment_cannot_unlock_knight_attack():
    s = position(A, B, board=(((0, 0), 0, "berserker", 2), ((2, 0), 1, "knight", 1)),
                 hands=(("berserker",), ("royal",)))
    s = act(s, Action("move", "berserker", path=((1, 0),)))
    assert not any(a.kind == "attack" for a in legal_actions(s))
    s = act(s, Action("move", "berserker", source=(1, 0), path=((1, 1),)))
    assert s.board[(1, 1)].count == 1 and s.current == 1


def test_ensign_moves_ally_and_triggers_berserker():
    a = ("ensign", "berserker", "swordsman", "scout")
    b = ("royal_guard", "knight", "archer", "mercenary")
    s = position(a, b, board=(((0, 0), 0, "ensign", 1), ((1, 0), 0, "berserker", 2)),
                 hands=(("ensign",), ("royal",)))
    action = Action("tactic", "ensign", source=(1, 0), path=((2, 0),), effect="move")
    s = act(s, action)
    assert s.pending[0]["type"] == "berserk"
    assert s.players[0].discard == [("ensign", True)]
    assert s.board[(2, 0)].unit == "berserker"


def test_ensign_respects_destination_radius():
    a = ("ensign", "berserker", "swordsman", "scout")
    b = ("royal_guard", "knight", "archer", "mercenary")
    s = position(a, b, board=(((0, 0), 0, "ensign", 1), ((2, 0), 0, "scout", 1)),
                 hands=(("ensign",), ("royal",)))
    assert Action("tactic", "ensign", source=(2, 0), path=((3, 0),), effect="move") not in legal_actions(s)


def test_marshall_normal_attack_only_and_swordsman_attribute():
    a = ("marshall", "swordsman", "archer", "scout")
    b = ("royal_guard", "knight", "ensign", "mercenary")
    s = position(a, b, board=(((0, 0), 0, "marshall", 1), ((1, 0), 0, "swordsman", 1),
                             ((1, 1), 0, "archer", 1), ((2, 0), 1, "mercenary", 1)),
                 hands=(("marshall",), ("royal",)))
    assert not any(a.kind == "tactic" and a.source == (1, 1) for a in legal_actions(s))
    s = act(s, Action("tactic", "marshall", source=(1, 0), target=(2, 0), after=(2, 0), effect="attack"))
    assert s.board[(2, 0)].unit == "swordsman"


def test_mercenary_recruit_grants_optional_maneuver():
    s = position(A, B, board=(((0, 0), 1, "mercenary", 1),), current=1)
    s = act(s, Action("recruit", "royal", recruit="mercenary"))
    assert s.current == 1 and s.pending[0]["type"] == "mercenary"
    assert {a.kind for a in legal_actions(s)} <= {"move", "attack", "control", "finish"}
    s = act(s, Action("move", "mercenary", source=(0, 0), path=((1, 0),)))
    assert s.current == 0
    assert s.players[1].discard == [("royal", False), ("mercenary", True)]


def test_undeployed_mercenary_does_not_trigger():
    s = position(A, B, current=1)
    s = act(s, Action("recruit", "royal", recruit="mercenary"))
    assert s.current == 0 and not s.pending


def test_priest_immediate_extra_coin_is_mandatory_and_hidden():
    s = position(A, B, board=(((-2, 0), 0, "warrior_priest", 1),),
                 hands=(("warrior_priest", "footman"), ("royal",)))
    s.players[0].bag.append("berserker")
    s.players[0].supply["berserker"] -= 1
    s = act(s, Action("control", "warrior_priest"))
    assert s.current == 0 and s.pending[0]["coin"] == "berserker"
    assert all(a.coin == "berserker" for a in legal_actions(s))
    assert "coin" not in observe(s, 1)["pending"][0]
    s = act(s, Action("pass", "berserker"))
    assert s.current == 1 and s.players[0].hand == ["footman"]


def test_priest_attack_does_not_draw_after_pike_death():
    b = ("pikeman", "knight", "ensign", "mercenary")
    s = position(A, b, board=(((0, 0), 0, "warrior_priest", 1), ((1, 0), 1, "pikeman", 1)),
                 hands=(("warrior_priest",), ("royal",)))
    s = act(s, Action("attack", "warrior_priest", target=(1, 0)))
    assert s.board == {} and s.pending == []
    assert s.current == 1 and s.players[0].bag == ["royal"]


@pytest.mark.parametrize("choice", ["defend_unit", "defend_supply"])
def test_royal_guard_interrupt_and_resume(choice):
    s = position(A, B, board=(((0, 0), 0, "warrior_priest", 1), ((1, 0), 1, "royal_guard", 1)),
                 hands=(("warrior_priest",), ("royal",)))
    s = act(s, Action("attack", "warrior_priest", target=(1, 0)))
    assert s.current == 1 and s.pending[0]["type"] == "defend"
    assert s.players[0].hand == []  # No extra draw before defense resolves.
    s = act(s, Action(choice, "royal_guard", source=(1, 0)))
    assert s.current == 0 and s.pending[0]["type"] == "coin"
    assert ((1, 0) in s.board) == (choice == "defend_supply")
    assert s.players[1].removed == ["royal_guard"]
    s = act(s, Action("pass", s.pending[0]["coin"]))
    assert s.current == 1 and not s.pending


def test_guard_royal_coin_tactic_destination_and_payment():
    s = position(A, B, board=(((0, 1), 1, "royal_guard", 1),), current=1)
    a = Action("tactic", "royal", path=((0, 2), (1, 2)), source=(0, 1), effect="move")
    s = act(s, a)
    assert s.board[(1, 2)].unit == "royal_guard"
    assert s.players[1].discard == [("royal", True)]


@pytest.mark.parametrize("seed", range(12))
def test_random_full_rosters(seed):
    units = random.Random(seed).sample(list(BASE_UNITS), 8)
    s = new_game(seed, (units[:4], units[4:]))
    rng = random.Random(seed + 100)
    for _ in range(150):
        if s.winner is not None:
            break
        actions = legal_actions(s)
        assert actions
        s, _ = apply_action(s, rng.choice(actions))
        validate_state(s)
    assert deserialize(serialize(s)) == s
