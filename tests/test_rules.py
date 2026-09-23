from dataclasses import replace

import pytest

from warchest import Action, IllegalAction, apply_action, legal_actions, new_game, serialize, validate_state
from warchest.board import HEXES, LOCATIONS, STARTS, distance, neighbors
from warchest.units import ARMIES, ROYAL, UNITS


def execute(state, action):
    result, events = apply_action(state, action)
    validate_state(result)
    return result


def test_official_board():
    assert len(HEXES) == 37
    assert len(LOCATIONS) == 10
    assert STARTS == {0: ((-1, -2), (2, -3)), 1: ((-2, 3), (1, 2))}
    assert LOCATIONS <= HEXES
    assert len(neighbors((0, 0))) == 6
    assert len(neighbors((3, 0))) == 3
    assert distance((0, 0), (1, 1)) == 2
    assert distance((-3, 3), (3, -3)) == 6
    assert all(p in neighbors(n) for p in HEXES for n in neighbors(p))
    assert {(-q, -r) for q, r in LOCATIONS} == LOCATIONS


def test_initial_setup():
    state = new_game(123)
    validate_state(state)
    assert state.current == state.initiative == 0
    assert state.round == 1 and state.board == {}
    for who, p in enumerate(state.players):
        assert len(p.hand) == 3 and len(p.bag) == 6
        assert p.hand.count(ROYAL) + p.bag.count(ROYAL) == 1
        assert sum(o == who for o in state.controls.values()) == 2
        for u in ARMIES[who]:
            assert p.hand.count(u) + p.bag.count(u) == 2
            assert p.supply[u] == UNITS[u].coins - 2


def test_deploy_and_bolster(position):
    state = position(hands=(("swordsman", "swordsman"), (ROYAL,)))
    deployed = execute(state, Action("deploy", "swordsman", target=(-1, -2)))
    assert deployed.board[(-1, -2)].count == 1
    deployed = execute(deployed, Action("pass", ROYAL))
    assert not any(a.kind == "deploy" for a in legal_actions(deployed))
    bolstered = execute(deployed, Action("bolster", "swordsman"))
    assert bolstered.board[(-1, -2)].count == 2
    assert state.board == {}  # Pure transition.


def test_blocked_deployment(position):
    state = position(board=(((-1, -2), 0, "pikeman", 1), ((2, -3), 1, "archer", 1)),
                     hands=(("swordsman",), (ROYAL,)))
    assert not any(a.kind == "deploy" for a in legal_actions(state))


def test_scout_deployment(position):
    state = position(board=(((0, 0), 1, "archer", 1),),
                     hands=((ROYAL,), ("scout",)), current=1)
    locations = {a.target for a in legal_actions(state) if a.kind == "deploy"}
    assert locations == set(neighbors((0, 0))) | set(STARTS[1])


def test_scout_cannot_duplicate(position):
    state = position(board=(((0, 0), 1, "scout", 1),), hands=((ROYAL,), ("scout",)), current=1)
    assert not any(a.kind == "deploy" for a in legal_actions(state))


def test_move_stack_and_blocking(position):
    state = position(board=(((0, 0), 0, "pikeman", 2), ((1, 0), 1, "scout", 1)),
                     hands=(("pikeman",), (ROYAL,)))
    assert Action("move", "pikeman", path=((1, 0),)) not in legal_actions(state)
    result = execute(state, Action("move", "pikeman", path=((0, 1),)))
    assert (0, 0) not in result.board and result.board[(0, 1)].count == 2


def test_recruit_and_pass(position):
    state = position(hands=((ROYAL, "swordsman"), (ROYAL,)))
    result = execute(state, Action("recruit", ROYAL, recruit="pikeman"))
    assert result.players[0].discard == [(ROYAL, False), ("pikeman", True)]
    assert result.players[0].supply["pikeman"] == 3
    result = execute(result, Action("pass", ROYAL))
    assert result.current == 0 and result.players[0].hand == ["swordsman"]
    assert any(a.kind == "deploy" for a in legal_actions(result))


def test_empty_supply_not_recruitable(position):
    state = position(board=(((0, 0), 0, "pikeman", 4),))
    assert not any(a.recruit == "pikeman" for a in legal_actions(state))


def test_royal_only_facedown_actions():
    state = new_game(0)
    state.players[0].hand = [ROYAL]
    assert {a.kind for a in legal_actions(state)} == {"pass", "recruit"}


def test_initiative_next_round_only(position):
    state = position(hands=(("swordsman", ROYAL), ("scout", ROYAL)), current=1)
    result = execute(state, Action("initiative", "scout"))
    assert result.initiative == 1 and result.current == 0
    assert not any(a.kind == "initiative" for a in legal_actions(result))
    result = execute(result, Action("pass", "swordsman"))
    result = execute(result, Action("pass", ROYAL))
    result = execute(result, Action("pass", ROYAL))
    assert result.round == 2 and result.current == 1 and not result.initiative_claimed
    assert not any(a.kind == "initiative" for a in legal_actions(result))


def test_control_is_separate_from_move(position):
    state = position(board=(((-1, 0), 0, "swordsman", 1),),
                     hands=(("swordsman", "swordsman"), (ROYAL,)))
    result = execute(state, Action("move", "swordsman", path=((-2, 0),)))
    assert result.controls[(-2, 0)] is None
    result = execute(result, Action("pass", ROYAL))
    result = execute(result, Action("control", "swordsman"))
    assert result.controls[(-2, 0)] == 0


def test_capture_enemy_start_and_win(position):
    controlled = {p: (0 if p in sorted(LOCATIONS)[:5] else None) for p in LOCATIONS}
    target = next(p for p in STARTS[1] if controlled[p] is None)
    controlled[target] = 1
    state = position(board=((target, 0, "swordsman", 1),),
                     hands=(("swordsman",), (ROYAL,)), controls=controlled)
    assert state.controls[target] == 1
    result = execute(state, Action("control", "swordsman"))
    assert result.winner == 0 and result.round == 1
    assert result.players[1].hand == [ROYAL]
    assert legal_actions(result) == []
    with pytest.raises(IllegalAction):
        apply_action(result, Action("pass", ROYAL))


def test_cannot_control_own_location(position):
    state = position(board=(((-1, -2), 0, "swordsman", 1),), hands=(("swordsman",), (ROYAL,)))
    assert Action("control", "swordsman") not in legal_actions(state)


def test_attack_removes_to_box_and_no_automatic_advance(position):
    state = position(board=(((0, 0), 0, "crossbowman", 1), ((1, 0), 1, "scout", 1)),
                     hands=(("crossbowman",), (ROYAL,)))
    result = execute(state, Action("attack", "crossbowman", target=(1, 0)))
    assert (1, 0) not in result.board
    assert result.players[1].removed == ["scout"]
    assert result.board[(0, 0)].unit == "crossbowman"


@pytest.mark.parametrize("unit", ["archer", "lancer"])
def test_no_normal_attack_for_restricted_units(position, unit):
    state = position(board=(((0, 0), 1, unit, 1), ((1, 0), 0, "swordsman", 1)),
                     hands=((ROYAL,), (unit,)), current=1)
    assert not any(a.kind == "attack" for a in legal_actions(state))


def test_archer_nonstraight_and_blocked_shot(position):
    state = position(board=(((0, 0), 1, "archer", 1), ((1, 0), 1, "scout", 1),
                            ((2, 0), 0, "swordsman", 1), ((1, 1), 0, "pikeman", 1)),
                     hands=((ROYAL,), ("archer",)), current=1)
    for target in ((2, 0), (1, 1)):
        result = execute(state, Action("tactic", "archer", target=target))
        assert target not in result.board
        assert result.board[(0, 0)].count == 1  # No ranged pike retaliation.


def test_crossbow_straight_clear_shot_and_melee(position):
    state = position(board=(((0, 0), 0, "crossbowman", 1), ((2, 0), 1, "scout", 1),
                            ((0, 1), 1, "cavalry", 1), ((1, 1), 1, "archer", 1)),
                     hands=(("crossbowman",), (ROYAL,)))
    actions = legal_actions(state)
    assert Action("tactic", "crossbowman", target=(2, 0)) in actions
    assert Action("tactic", "crossbowman", target=(1, 1)) not in actions
    assert Action("attack", "crossbowman", target=(0, 1)) in actions
    execute(state, Action("tactic", "crossbowman", target=(2, 0)))
    state.board[(1, 0)] = state.board.pop((0, 1))
    assert Action("tactic", "crossbowman", target=(2, 0)) not in legal_actions(state)


def test_light_cavalry_turn_and_return(position):
    state = position(board=(((0, 0), 0, "light_cavalry", 1),),
                     hands=(("light_cavalry",), (ROYAL,)))
    for path in (((1, 0), (1, 1)), ((1, 0), (0, 0))):
        result = execute(state, Action("tactic", "light_cavalry", path=path))
        assert result.board[path[-1]].unit == "light_cavalry"
    assert Action("move", "light_cavalry", path=((1, 0),)) in legal_actions(state)


def test_cavalry_move_then_attack(position):
    state = position(board=(((0, 0), 1, "cavalry", 1), ((1, 1), 0, "swordsman", 1)),
                     hands=((ROYAL,), ("cavalry",)), current=1)
    result = execute(state, Action("tactic", "cavalry", path=((1, 0),), target=(1, 1)))
    assert result.board[(1, 0)].unit == "cavalry" and (1, 1) not in result.board
    assert Action("tactic", "cavalry", path=((1, 0),)) not in legal_actions(state)


@pytest.mark.parametrize("length", [1, 2])
def test_lancer_straight_charge(position, length):
    target = (length + 1, 0)
    state = position(board=(((0, 0), 1, "lancer", 1), (target, 0, "swordsman", 1)),
                     hands=((ROYAL,), ("lancer",)), current=1)
    path = tuple((n, 0) for n in range(1, length + 1))
    result = execute(state, Action("tactic", "lancer", path=path, target=target))
    assert target not in result.board and path[-1] in result.board
    assert Action("tactic", "lancer", path=path) not in legal_actions(state)


def test_lancer_cannot_turn_or_cross_units(position):
    state = position(board=(((0, 0), 1, "lancer", 1), ((1, 1), 0, "swordsman", 1)),
                     hands=((ROYAL,), ("lancer",)), current=1)
    assert not any(a.kind == "tactic" for a in legal_actions(state))
    state.board[(2, 0)] = state.board.pop((1, 1))
    state.board[(1, 0)] = state.board.pop((0, 0))
    # Adjacent enemy cannot be attacked without the compulsory forward move.
    assert not any(a.kind == "tactic" and a.target == (2, 0) for a in legal_actions(state))


@pytest.mark.parametrize("count", [1, 2])
def test_pikeman_retaliation_even_when_destroyed(position, count):
    state = position(board=(((0, 0), 0, "pikeman", 1), ((1, 0), 1, "cavalry", count)),
                     hands=((ROYAL,), ("cavalry",)), current=1)
    result = execute(state, Action("attack", "cavalry", target=(0, 0)))
    assert (0, 0) not in result.board
    assert result.players[0].removed == ["pikeman"]
    assert result.players[1].removed == ["cavalry"]
    assert ((1, 0) in result.board) == (count == 2)


def test_lancer_retaliation_after_moving(position):
    state = position(board=(((0, 0), 1, "lancer", 1), ((2, 0), 0, "pikeman", 1)),
                     hands=((ROYAL,), ("lancer",)), current=1)
    result = execute(state, Action("tactic", "lancer", path=((1, 0),), target=(2, 0)))
    assert result.board == {}


def test_swordsman_optional_move_and_capture_space(position):
    state = position(board=(((0, 0), 0, "swordsman", 1), ((1, 0), 1, "scout", 1)),
                     hands=(("swordsman",), (ROYAL,)))
    base = Action("attack", "swordsman", target=(1, 0))
    assert base in legal_actions(state)
    result = execute(state, replace(base, after=(1, 0)))
    assert (0, 0) not in result.board and result.board[(1, 0)].unit == "swordsman"


def test_swordsman_cannot_move_onto_surviving_target(position):
    state = position(board=(((0, 0), 0, "swordsman", 1), ((1, 0), 1, "scout", 2)),
                     hands=(("swordsman",), (ROYAL,)))
    assert Action("attack", "swordsman", target=(1, 0), after=(1, 0)) not in legal_actions(state)


def test_reshuffle_mid_draw_and_short_hand(position):
    state = position()
    p = state.players[0]
    # One coin left in bag, plus the royal just spent; only two can be drawn.
    p.bag = ["swordsman"]
    p.supply["swordsman"] -= 1
    state = execute(state, Action("pass", ROYAL))
    result = execute(state, Action("pass", ROYAL))
    assert result.round == 2
    assert result.players[0].hand == ["swordsman", ROYAL]
    assert result.players[1].hand == [ROYAL]
    assert result.players[0].discard == []
    result = execute(result, Action("pass", "swordsman"))
    result = execute(result, Action("pass", ROYAL))
    assert result.current == 0 and result.round == 2


@pytest.mark.parametrize("action", [
    Action("deploy", "swordsman", target=(99, 99)),
    Action("pass", "archer"), Action("unknown", "royal"),
    Action("recruit", "royal", recruit="nonexistent"),
])
def test_illegal_atomicity(position, action):
    state = position()
    before = serialize(state)
    with pytest.raises(IllegalAction):
        apply_action(state, action)
    assert serialize(state) == before


def test_stable_unique_legal_actions(position):
    state = position(hands=(("swordsman", "swordsman"), (ROYAL,)))
    actions = legal_actions(state)
    assert len(actions) == len(set(actions))
    assert actions == legal_actions(state)
    for action in actions:
        execute(state, action)


def test_destroyed_unit_can_redeploy(position):
    state = position(board=(((0, 0), 0, "crossbowman", 1), ((1, 0), 1, "scout", 1)),
                     hands=(("crossbowman",), ("scout",)))
    state = execute(state, Action("attack", "crossbowman", target=(1, 0)))
    result = execute(state, Action("deploy", "scout", target=(-2, 3)))
    assert result.board[(-2, 3)].count == 1
    assert result.players[1].removed == ["scout"]


def test_draw_does_not_reshuffle_early(position):
    state = position()
    p = state.players[0]
    p.bag = ["swordsman"] * 4
    p.supply["swordsman"] -= 4
    state = execute(state, Action("pass", ROYAL))
    result = execute(state, Action("pass", ROYAL))
    assert result.players[0].hand == ["swordsman"] * 3
    assert result.players[0].bag == ["swordsman"]
    assert result.players[0].discard == [(ROYAL, False)]


def test_mid_draw_refill_reaches_three(position):
    state = position()
    p = state.players[0]
    p.bag = ["swordsman"]
    p.discard = [("pikeman", True), ("crossbowman", False)]
    for u in ("swordsman", "pikeman", "crossbowman"):
        p.supply[u] -= 1
    state = execute(state, Action("pass", ROYAL))
    result = execute(state, Action("pass", ROYAL))
    assert result.players[0].hand[0] == "swordsman"
    assert len(result.players[0].hand) == 3
    assert len(result.players[0].bag) == 1
    assert result.players[0].discard == []


def test_light_cavalry_cannot_cross_or_land_on_unit(position):
    state = position(board=(((0, 0), 0, "light_cavalry", 1),
                            ((1, 0), 1, "scout", 1), ((0, 2), 0, "pikeman", 1)),
                     hands=(("light_cavalry",), (ROYAL,)))
    for path in (((1, 0), (2, 0)), ((0, 1), (0, 2))):
        before = serialize(state)
        with pytest.raises(IllegalAction):
            apply_action(state, Action("tactic", "light_cavalry", path=path))
        assert serialize(state) == before


def test_lancer_cannot_jump_friendly_unit(position):
    state = position(board=(((0, 0), 1, "lancer", 1), ((1, 0), 1, "scout", 1),
                            ((3, 0), 0, "swordsman", 1)),
                     hands=((ROYAL,), ("lancer",)), current=1)
    assert Action("tactic", "lancer", path=((1, 0), (2, 0)), target=(3, 0)) not in legal_actions(state)
