"""Pure state transitions: all external input is validated before mutation."""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import random

from .board import HEXES, LOCATIONS, STARTS, distance, neighbors
from .model import Action, Event, Player, Stack, State, RULES_VERSION
from .tactics import swordsman_choices, tactic_actions
from .units import ARMIES, ROYAL, UNITS


class IllegalAction(ValueError):
    pass


def _event(events, event_type, visible_to=None, **data):
    events.append(Event(event_type, tuple(data.items()), visible_to))


def _new_round(state, events):
    state.round += 1
    state.initiative_claimed = False
    rng = random.Random()
    rng.setstate(state.rng_state)
    _event(events, "round", round=state.round, initiative=state.initiative)
    for who, player in enumerate(state.players):
        for _ in range(3):
            if not player.bag:
                player.bag = [coin for coin, _ in player.discard]
                player.discard.clear()
                if player.bag:
                    rng.shuffle(player.bag)
                    _event(events, "reshuffle", player=who, count=len(player.bag))
            if not player.bag:
                break
            coin = player.bag.pop()
            player.hand.append(coin)
            _event(events, "draw", player=who)
            _event(events, "draw_coin", visible_to=who, coin=coin)
    state.rng_state = rng.getstate()
    state.current = state.initiative
    if not state.players[state.current].hand:
        state.current = 1 - state.current


def new_game(seed=0, armies=None, initiative=0, *, expansions=None, setup=None):
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if type(initiative) is not int or initiative not in (0, 1):
        raise ValueError("initiative must be 0 or 1")
    armies = ARMIES if armies is None else armies
    if (len(armies) != 2 or any(len(a) != 4 for a in armies)
            or len(set(armies[0]) | set(armies[1])) != 8
            or any(u not in UNITS for a in armies for u in a)):
        raise ValueError("双方各需四个不重复的兵种")
    rng = random.Random(seed)
    players = []
    for army in armies:
        bag = [coin for unit in army for coin in (unit, unit)] + [ROYAL]
        rng.shuffle(bag)
        players.append(Player({u: UNITS[u].coins - 2 for u in army}, bag))
    controls = dict.fromkeys(sorted(LOCATIONS))
    for who, positions in STARTS.items():
        for pos in positions:
            controls[pos] = who
    state = State(seed, players, {}, controls, rng.getstate(), initiative=initiative)
    events = []
    from .expansions import initialize
    initialize(state, expansions, setup)
    _new_round(state, events)
    state.history = tuple(events)
    return state


@lru_cache(maxsize=32768)
def action_key(action):
    return json.dumps(asdict(action), sort_keys=True, separators=(",", ":"))


def can_attack(state, source, target):
    attacker, victim = state.board[source], state.board.get(target)
    return (victim is not None and victim.owner != attacker.owner
            and (victim.unit != "knight" or attacker.count > 1))


def maneuvers(state, pos, *, tactics=True, explicit=False):
    stack = state.board[pos]
    unit = stack.unit
    source = pos if explicit or unit == "footman" else None
    actions = []
    for end in neighbors(pos):
        if end not in state.board:
            actions.append(Action("move", unit, path=(end,), source=source))
        elif unit not in ("archer", "lancer") and can_attack(state, pos, end):
            attack = Action("attack", unit, target=end, source=source)
            if unit == "swordsman" and state.board[end].unit != "royal_guard":
                actions.extend(swordsman_choices(state, pos, attack))
            else:
                actions.append(attack)
    if pos in state.controls and state.controls[pos] != stack.owner:
        actions.append(Action("control", unit, source=source))
    if tactics:
        for action in tactic_actions(state, unit, pos):
            if action.target is None or can_attack(state, pos, action.target):
                actions.append(replace(action, source=source))
        if unit in ("ensign", "marshall"):
            for ally, other in state.board.items():
                if other.owner != stack.owner or distance(ally, pos) > 2:
                    continue
                for action in maneuvers(state, ally, tactics=False, explicit=True):
                    if unit == "ensign" and action.kind == "move" and distance(action.path[-1], pos) <= 2:
                        actions.append(replace(action, kind="tactic", coin=unit, effect="move"))
                    if unit == "marshall" and action.kind == "attack":
                        actions.append(replace(action, kind="tactic", coin=unit, effect="attack"))
        if unit == "footman":
            for action in maneuvers(state, pos, tactics=False, explicit=True):
                actions.append(replace(action, kind="tactic", effect=action.kind))
    return actions


def pending_actions(state):
    task = state.pending[0]
    unit = task.get("unit", "royal")
    pos = tuple(task["source"]) if task.get("source") is not None else None
    kind = task["type"]
    if kind == "defend":
        return [Action("defend_unit", unit, source=pos), Action("defend_supply", unit, source=pos)]
    if kind == "sword":
        return [Action("finish", unit)] + [Action("move", unit, source=pos, path=(p,))
                for p in neighbors(pos) if p not in state.board]
    actions = maneuvers(state, pos, tactics=False, explicit=True) if pos in state.board else []
    if kind == "berserk":
        if pos not in state.board or state.board[pos].count <= 1:
            actions = []
        else:
            # Removing the payment may make a Knight immune to the next attack.
            preview = deepcopy(state, {id(state.history): state.history, id(state.rng_state): state.rng_state})
            preview.board[pos].count -= 1
            actions = maneuvers(preview, pos, tactics=False, explicit=True)
    if kind in ("berserk", "mercenary") or not actions:
        actions.append(Action("finish", unit))
    return actions


def legal_actions(state):
    if state.extras:
        from .expansions import legal_actions as expanded_actions
        return expanded_actions(state)
    if state.winner is not None:
        return []
    if state.pending and state.pending[0]["type"] != "coin":
        return sorted(set(pending_actions(state)), key=action_key)
    player = state.players[state.current]
    coins = [state.pending[0]["coin"]] if state.pending else sorted(set(player.hand))
    actions = set()
    for coin in coins:
        actions.add(Action("pass", coin))
        if state.current != state.initiative and not state.initiative_claimed:
            actions.add(Action("initiative", coin))
        for recruit, count in player.supply.items():
            if count:
                actions.add(Action("recruit", coin, recruit=recruit))
        if coin == ROYAL:
            guards = [p for p, s in state.board.items() if s.owner == state.current and s.unit == "royal_guard"]
            for pos in guards:
                for mid in neighbors(pos):
                    if mid in state.board:
                        continue
                    if state.controls.get(mid) == state.current:
                        actions.add(Action("tactic", coin, path=(mid,), source=pos, effect="move"))
                    for end in neighbors(mid):
                        if (end not in state.board or end == pos) and state.controls.get(end) == state.current:
                            actions.add(Action("tactic", coin, path=(mid, end), source=pos, effect="move"))
            continue
        positions = [p for p, s in state.board.items() if s.owner == state.current and s.unit == coin]
        if len(positions) < (2 if coin == "footman" else 1):
            placements = {p for p, owner in state.controls.items() if owner == state.current}
            if coin == "scout":
                for p, stack in state.board.items():
                    if stack.owner == state.current:
                        placements.update(neighbors(p))
            actions.update(Action("deploy", coin, target=p) for p in placements if p not in state.board)
        for pos in positions:
            actions.add(Action("bolster", coin, source=pos if coin == "footman" else None))
            actions.update(maneuvers(state, pos))
    return sorted(actions, key=action_key)


def _move(state, start, end, events):
    stack = state.board.pop(start)
    state.board[end] = stack
    _event(events, "move", player=stack.owner, unit=stack.unit, start=start, end=end)
    return end


def _damage(state, pos, events):
    stack = state.board[pos]
    state.players[stack.owner].removed.append(stack.unit)
    stack.count -= 1
    _event(events, "damage", player=stack.owner, unit=stack.unit, pos=pos, remaining=stack.count)
    if not stack.count:
        del state.board[pos]


def _task(state, kind, owner, unit, pos=None, **extra):
    return {"type": kind, "player": owner, "unit": unit, "source": pos, **extra}


def _draw_extra(state, who, events):
    player = state.players[who]
    rng = random.Random()
    rng.setstate(state.rng_state)
    if not player.bag:
        player.bag = [c for c, _ in player.discard]
        player.discard.clear()
        rng.shuffle(player.bag)
        _event(events, "reshuffle", player=who, count=len(player.bag))
    state.rng_state = rng.getstate()
    if not player.bag:
        return None
    coin = player.bag.pop()
    player.hand.append(coin)
    _event(events, "draw", player=who)
    _event(events, "draw_coin", visible_to=who, coin=coin)
    return _task(state, "coin", who, "warrior_priest", coin=coin)


def apply_action(state, action):
    if state.extras:
        from .expansions import apply_action as expanded_apply
        return expanded_apply(state, action)
    if not isinstance(action, Action) or action not in legal_actions(state):
        raise IllegalAction("行动不合法，状态未改变")
    # History and PRNG state contain only immutable values; share those tuples.
    result = deepcopy(state, {id(state.history): state.history, id(state.rng_state): state.rng_state})
    events = []
    who = result.current
    player = result.players[who]
    task = result.pending.pop(0) if result.pending else None
    free = task is not None and task["type"] != "coin"
    if result.turn_owner is None:
        result.turn_owner = who
    if not free:
        player.hand.remove(action.coin)
    hidden = action.kind in ("pass", "initiative", "recruit")
    _event(events, "action", player=who, kind=action.kind,
           coin=None if hidden else action.coin, path=action.path,
           target=action.target, recruit=action.recruit, after=action.after,
           source=action.source, effect=action.effect, free=free)
    if hidden:
        _event(events, "payment", visible_to=who, coin=action.coin)
    if not free and action.kind not in ("deploy", "bolster"):
        player.discard.append((action.coin, not hidden))
    pos = action.source or next((p for p, s in result.board.items()
                if s.owner == who and s.unit == action.coin), None)
    if free and task["type"] == "berserk" and action.kind != "finish":
        result.board[pos].count -= 1
        player.discard.append(("berserker", True))
        _event(events, "berserk_payment", player=who, pos=pos)
    followups = []
    if action.kind == "deploy":
        result.board[action.target] = Stack(who, action.coin)
    elif action.kind == "bolster":
        result.board[pos].count += 1
    elif action.kind == "recruit":
        player.supply[action.recruit] -= 1
        player.discard.append((action.recruit, True))
        if action.recruit == "mercenary":
            merc = next((p for p, s in result.board.items() if s.owner == who and s.unit == "mercenary"), None)
            if merc is not None:
                followups.append(_task(result, "mercenary", who, "mercenary", merc))
    elif action.kind == "initiative":
        result.initiative, result.initiative_claimed = who, True
    elif action.kind == "defend_supply":
        player.supply["royal_guard"] -= 1
        player.removed.append("royal_guard")
        _event(events, "supply_damage", player=who, unit="royal_guard")
    elif action.kind == "defend_unit":
        _damage(result, pos, events)
    elif action.kind in ("control", "move", "attack", "tactic"):
        actor = result.board[pos]
        unit, owner = actor.unit, actor.owner
        effect = action.effect or action.kind
        # Footman tactic schedules the other unit only once, before any movement.
        if action.kind == "tactic" and action.coin == "footman":
            followups.extend(_task(result, "footman", owner, unit, p)
                             for p, s in result.board.items() if p != pos and s.owner == owner and s.unit == unit)
        for end in action.path:
            pos = _move(result, pos, end, events)
        is_control = effect == "control"
        is_attack = action.target is not None
        if is_control:
            result.controls[pos] = owner
            if list(result.controls.values()).count(owner) == 6:
                result.winner = owner
                _event(events, "win", player=owner)
        if is_attack:
            target = result.board[action.target]
            retaliates = target.unit == "pikeman" and distance(pos, action.target) == 1
            if target.unit == "royal_guard" and result.players[target.owner].supply["royal_guard"]:
                followups.insert(0, _task(result, "defend", target.owner, target.unit, action.target))
            else:
                _damage(result, action.target, events)
            if retaliates:
                _damage(result, pos, events)
        if action.after is not None:
            pos = _move(result, pos, action.after, events)
        if unit == "swordsman" and is_attack and state.board[action.target].unit == "royal_guard" and pos in result.board:
            followups.append(_task(result, "sword", owner, unit, pos))
        if unit == "berserker" and pos in result.board and result.board[pos].count > 1:
            followups.append(_task(result, "berserk", owner, unit, pos))
        if unit == "warrior_priest" and pos in result.board and (is_attack or is_control) and result.winner is None:
            # Draw after any defender decision, so the defense player cannot see it.
            followups.append(_task(result, "draw", owner, unit))
    result.pending = followups + result.pending
    if result.winner is not None:
        result.pending.clear()
        result.turn_owner = None
    else:
        while result.pending and result.pending[0]["type"] == "draw":
            draw = result.pending.pop(0)
            extra = _draw_extra(result, draw["player"], events)
            if extra:
                result.pending.insert(0, extra)
        if result.pending:
            result.current = result.pending[0]["player"]
        else:
            owner = result.turn_owner
            result.turn_owner = None
            other = 1 - owner
            if result.players[other].hand:
                result.current = other
            elif result.players[owner].hand:
                result.current = owner
            else:
                _new_round(result, events)
    result.history += tuple(events)
    return result, tuple(events)


def visible_events(events, player):
    return [asdict(e) for e in events if e.visible_to is None or e.visible_to == player]


def observe(state, player, *, include_history=True):
    if type(player) is not int or player not in (0, 1):
        raise ValueError("player must be 0 or 1")
    players = []
    for who, p in enumerate(state.players):
        players.append({
            "supply": dict(p.supply), "bag_count": len(p.bag),
            "hand": sorted(p.hand) if who == player else None,
            "hand_count": len(p.hand),
            "discard": [coin if faceup or who == player else None for coin, faceup in p.discard],
            "discard_faceup": [faceup for _, faceup in p.discard],
            "removed": sorted(p.removed),
        })
    result = {"version": state.version, "player": player, "round": state.round,
            "current": state.current, "initiative": state.initiative,
            "initiative_claimed": state.initiative_claimed, "winner": state.winner,
            "board": [{"pos": pos, **asdict(s)} for pos, s in sorted(state.board.items())],
            "controls": [{"pos": p, "owner": o} for p, o in sorted(state.controls.items())],
            "players": players,
            "turn_owner": state.turn_owner,
            "pending": [{k: deepcopy(v) for k, v in t.items() if k != "coin" or t["player"] == player}
                        for t in state.pending],
            "history": visible_events(state.history, player) if include_history else []}
    if state.extras:
        from .expansions import observe_extras
        result["extras"] = observe_extras(state, player)
    return result


def validate_state(state):
    """Raise ValueError for broken structural or conservation invariants."""
    def require(condition, message):
        if not condition:
            raise ValueError(message)
    require(state.version in (RULES_VERSION, "expansions-1", "expansions-2"), "unsupported rules version")
    require(bool(state.extras) == (state.version in ("expansions-1", "expansions-2")), "missing or unexpected expansion state")
    require(len(state.players) == 2 and state.current in (0, 1)
            and state.initiative in (0, 1), "invalid players")
    require(set(state.controls) == LOCATIONS, "invalid control locations")
    require(all(o in (None, 0, 1) for o in state.controls.values()), "invalid control owner")
    from .community import board_hexes, stacks, captured, victory_target
    deployed = [st for _, st in stacks(state)]
    require(set(state.board) <= board_hexes(state), "unit outside board")
    seen = set()
    for stack in deployed:
        require(stack.owner in (0, 1), "invalid unit owner")
        require(stack.unit in state.players[stack.owner].supply and type(stack.count) is int and stack.count > 0,
                "invalid unit stack")
        identity = (stack.owner, stack.unit)
        limit = 2 if stack.unit == "footman" else 1
        require(sum(s.owner == stack.owner and s.unit == stack.unit for s in deployed) <= limit,
                "duplicate deployed unit")
        seen.add(identity)
    all_units = [u for p in state.players for u in p.supply]
    require(len(all_units) == 8 and len(set(all_units)) == 8, "invalid army composition")
    for who, p in enumerate(state.players):
        require(len(p.supply) == 4 and set(p.supply) <= UNITS.keys(), "invalid supply types")
        require(all(type(n) is int and n >= 0 for n in p.supply.values()), "invalid supply count")
        require(all(type(faceup) is bool for _, faceup in p.discard), "invalid discard visibility")
        counts = Counter(c for c in p.bag + p.hand + p.removed + [c for c, _ in p.discard]
                         if not (state.extras and c.startswith("decoy_")))
        counts.update(p.supply)
        for s in deployed:
            trophies = captured(state, s.unit)
            if s.owner == who:
                counts[s.unit] += s.count - len(trophies)
            for owner, unit in trophies:
                if owner == who: counts[unit] += 1
        expected = Counter({u: UNITS[u].coins for u in p.supply})
        expected[ROYAL] = 1
        require(counts == expected, "coin conservation failed")
        require(ROYAL not in p.removed, "royal coin cannot be destroyed")
        require(list(state.controls.values()).count(who) <= 6, "control marker conservation failed")
    winners = [p for p in (0, 1) if list(state.controls.values()).count(p) >= victory_target(state, p)]
    require((state.winner is None and not winners) or winners == [state.winner], "invalid winner")
    require(state.round >= 1, "invalid round")
    if state.pending:
        require(state.turn_owner in (0, 1), "missing original turn owner")
        require(state.current == state.pending[0]["player"], "incorrect continuation player")
        for task in state.pending:
            require((state.extras and task["type"].startswith("x_")) or task["type"] in {"coin", "draw", "defend", "sword", "footman", "berserk", "mercenary"},
                    "unknown continuation")
            require(task["player"] in (0, 1), "invalid continuation player")
        if state.pending[0]["type"] == "coin":
            require(state.pending[0]["coin"] in state.players[state.current].hand, "missing extra coin")
    else:
        require(state.turn_owner is None, "unresolved turn owner")
    require(state.winner is not None or bool(state.pending) or bool(state.players[state.current].hand), "no active hand")
    rng = random.Random()
    rng.setstate(state.rng_state)
    if state.extras:
        from .expansions import validate_extras
        validate_extras(state)
