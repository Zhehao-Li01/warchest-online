"""Expansion rules. Choices are explicit, serializable continuations.

The base-2 resolver remains available for existing games and recordings. Expanded
matches use this resolver, with the same Action / State / observation boundary.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
import random

from .board import HEXES, LOCATIONS, DIRECTIONS, SEA_HEXES, add, all_neighbors as neighbors, distance
from . import community as co
from .model import Action, Stack
from .units import UNITS, EXPANSIONS, unit_family

DECREES = {
    'enlist': ('征募', '招募两枚币，可选择相同兵种。'),
    'guard': ('守卫', '令位于己方据点的友军普通攻击。'),
    'march': ('行军', '令一支已增强的友军普通移动。'),
    'redeploy': ('重新部署', '移走一支友军，再将整个单位重新部署。'),
    'reinforce': ('补充', '将己方一枚已移出游戏的兵种币放回供应。'),
    'sacrifice': ('牺牲', '令一支友军普通攻击，然后移除该友军一枚币。'),
    'spy': ('侦察', '查看对手手牌，可弃置其中一枚并让对手补抽一枚。'),
}
# Filled from the six printed Siege layout cards; each layout is rotationally symmetric.
FORT_LAYOUTS = (
    ((-1, 1), (-1, -2), (1, 2), (1, -1)),
    ((-3, 2), (-2, 3), (2, -3), (3, -2)),
    ((-2, 3), (-1, 1), (1, -1), (2, -3)),
    ((-3, 2), (-1, -2), (1, 2), (3, -2)),
    ((-2, 3), (-2, 0), (2, 0), (2, -3)),
    ((-2, 0), (-1, -2), (1, 2), (2, 0)),
)


def initialize(state, expansions=None, setup=None):
    required = {UNITS[u].expansion for p in state.players for u in p.supply}
    enabled = set(expansions) if expansions is not None else required | {'base'}
    if not enabled <= EXPANSIONS.keys() or not required <= enabled:
        raise ValueError('阵容包含未启用扩展的兵种')
    families = [unit_family(u) for p in state.players for u in p.supply]
    if len(set(families)) != 8:
        raise ValueError('替代兵种不能与原兵种在同一局共用棋子')
    if enabled <= {'base'}:
        return
    rng = random.Random(state.seed ^ 0x455850)
    setup = setup or {}
    forts = setup.get('forts')
    if 'siege' in enabled and forts is None:
        if not FORT_LAYOUTS:
            raise ValueError('堡垒布局尚未配置')
        forts = rng.choice(FORT_LAYOUTS)
    decrees = setup.get('decrees', rng.sample(list(DECREES), 3) if 'nobility' in enabled else [])
    if len(decrees) != (3 if 'nobility' in enabled else 0) or len(set(decrees)) != len(decrees) or not set(decrees) <= DECREES.keys():
        raise ValueError('贵族扩展需要三道不同法令')
    if forts is not None:
        try:
            valid_forts = {tuple(p) for p in forts}
            if len(valid_forts) != len(forts) or not valid_forts <= LOCATIONS or len(forts) > 7 or (forts and 'siege' not in enabled):
                raise ValueError('堡垒布局无效')
        except TypeError as exc:
            raise ValueError('堡垒布局无效') from exc
    state.version = 'expansions-1'
    state.extras = {'enabled': sorted(enabled), 'forts': [list(p) for p in (forts or [])],
                    'poison': {}, 'decoys': {u: True for p in state.players for u in p.supply
                                            if u in ('infiltrator', 'skirmisher')},
                    'decrees': list(decrees), 'seals': [[], []]}
    if enabled & {'champions', 'mastery', 'high_seas'}:
        state.version = 'expansions-2'
        state.extras.update(lost_markers=[0, 0], underlays={}, captured={}, copies={}, poison_units={})


def forts(s):
    return {tuple(p) for p in s.extras['forts']}


def poisoned(s, pos):
    return any(p == list(pos) and s.extras.get('poison_units', {}).get(u, s.board[pos].unit) == s.board[pos].unit
               for u, p in s.extras['poison'].items())


def positions(s, who, unit=None):
    return sorted(p for p, st in s.board.items() if st.owner == who and (unit is None or st.unit == unit))


def task(kind, who, unit='royal', source=None, **kw):
    return dict(type='x_' + kind, player=who, unit=unit,
                source=list(source) if source is not None else None, **kw)


def event(events, event_type, **data):
    from .engine import _event
    _event(events, event_type, **data)


def can_enter(s, pos, who, empty_origin=None):
    return (pos in co.board_hexes(s) and (pos not in s.board or pos == empty_origin or co.can_share(s, empty_origin, pos))
            and not (pos in forts(s) and s.controls[pos] == 1-who))


def paths(s, pos, length, straight=False, shock_end=False):
    owner = s.board[pos].owner
    def extend(path, direction=None):
        start = path[-1] if path else pos
        if path and start in forts(s):
            return
        for d in ([direction] if direction is not None else DIRECTIONS):
            end = add(start, d)
            last = len(path) + 1 == length
            normal = can_enter(s, end, owner, pos)
            if end in SEA_HEXES and not co.has_attribute(s, pos, 'pirate'): normal = False
            if end in s.board and end != pos and not last: normal = False
            shock = (shock_end and last and end in s.board and s.board[end].owner != owner and end not in forts(s))
            if not (normal or shock):
                continue
            route = (*path, end)
            if last:
                yield route
            else:
                yield from extend(route, d if straight else None)
    yield from extend(())


def attackable(s, source, target, *, normal=True):
    st = s.board[source]
    if normal and co.role(s, source) in ('archer', 'lancer', 'trebuchet', 'corsair'):
        return False
    if target in forts(s):
        # A hostile garrison is protected even if its location is controlled by us.
        # Neutral, empty fortifications are also valid attack targets.
        victim = s.board.get(target)
        return s.controls[target] != st.owner or (victim is not None and victim.owner != st.owner)
    victim = s.board.get(target)
    return (victim is not None and victim.owner != st.owner
            and (not co.has_attribute(s, target, 'knight') or st.count > 1)
            and (not co.has_attribute(s, target, 'bishop') or st.count == 1))


def attack_action(s, pos, target, kind='attack', path=(), **kw):
    return Action(kind, s.board[pos].unit, path=path, target=target, source=pos,
                  effect='fort_attack' if target in forts(s) else 'attack', **kw)


def maneuvers(s, pos, tactics=True, chain=True):
    st = s.board[pos]
    unit, who = co.role(s, pos), st.owner
    copy = s.extras.get('copies', {}).get(st.unit)
    tactics = tactics and (not copy or copy['tactics'])
    actions = [Action('move', st.unit, path=p, source=pos) for p in paths(s, pos, 1)]
    actions += [attack_action(s, pos, p) for p in neighbors(pos) if attackable(s, pos, p)]
    if pos in s.controls and s.controls[pos] != who:
        actions.append(Action('control', st.unit, source=pos))
    actions += co.extra_maneuvers(s, pos, tactics, chain)
    if not tactics:
        return actions
    for n in (2, 3):
        if (unit in ('archer', 'marksman') and n == 2) or (unit == 'crossbowman' and n == 2) or (unit == 'trebuchet' and st.count > 1) or (unit == 'pirate' and pos in SEA_HEXES and n == 2):
            for target in sorted(co.board_hexes(s)):
                if distance(pos, target) != n or not attackable(s, pos, target, normal=False):
                    continue
                if unit not in ('archer', 'marksman'):
                    directions = [d for d in DIRECTIONS if (pos[0]+n*d[0], pos[1]+n*d[1]) == target]
                    if not directions:
                        continue
                    if unit in ('crossbowman', 'pirate') and add(pos, directions[0]) in s.board:
                        continue
                actions.append(attack_action(s, pos, target, 'tactic'))
    if unit in ('light_cavalry', 'skirmisher', 'heavy_cavalry', 'dragoon'):
        for path in [p for n in ((1, 2) if unit == 'skirmisher' else (2,))
                     for p in paths(s, pos, n, straight=unit == 'heavy_cavalry', shock_end=unit == 'heavy_cavalry')]:
            if unit == 'skirmisher' and not any(q in s.board and s.board[q].owner != who for q in neighbors(path[-1])):
                continue
            actions.append(Action('tactic', unit, path=path, source=pos,
                                  effect='charge_shock' if unit == 'heavy_cavalry' else 'move'))
    if unit in ('cavalry', 'lancer', 'sapper', 'assassin', 'dragoon', 'ranger'):
        for n in ((1, 2) if unit in ('lancer', 'dragoon') else (1,)):
            for path in paths(s, pos, n, straight=unit in ('lancer', 'dragoon')):
                end = path[-1]
                for target in neighbors(end):
                    if unit in ('lancer', 'dragoon') and target != (end[0]+(path[0][0]-pos[0]), end[1]+(path[0][1]-pos[1])):
                        continue
                    if unit == 'assassin':
                        if target in s.board and s.board[target].owner != who:
                            actions.append(Action('tactic', unit, source=pos, path=path, target=target, effect='poison'))
                    elif (unit != 'sapper' or target in forts(s)) and attackable(s, pos, target, normal=False):
                        actions.append(attack_action(s, pos, target, 'tactic', path))
    if unit in ('infiltrator', 'raider') and (unit != 'raider' or st.count > 1):
        for path in paths(s, pos, 1):
            end = path[-1]
            if end in s.controls and s.controls[end] != who and (unit != 'infiltrator' or s.controls[end] == 1-who):
                actions.append(Action('tactic', unit, source=pos, path=path, effect='move_control'))
    if unit in ('ensign', 'marshall') or unit == 'warlord' and chain:
        for ally in positions(s, who):
            if distance(ally, pos) > 2:
                continue
            if unit == 'warlord':
                if maneuvers(s, ally, chain=False):
                    actions.append(Action('tactic', unit, source=pos, target=ally, effect='command'))
            else:
                for a in maneuvers(s, ally, False):
                    if unit == 'ensign' and a.kind == 'move' and distance(a.path[-1], pos) <= 2:
                        actions.append(replace(a, kind='tactic', coin=unit, effect='move'))
                    if unit == 'marshall' and a.kind == 'attack':
                        actions.append(replace(a, kind='tactic', coin=unit))
    if unit == 'footman':
        actions += [replace(a, kind='tactic', effect=a.effect or a.kind) for a in maneuvers(s, pos, False)]
    if unit == 'bishop':
        for recruit, count in s.players[who].supply.items():
            if count:
                actions += [replace(a, kind='tactic', recruit=recruit, effect='bishop_' + (a.effect or a.kind))
                            for a in maneuvers(s, pos, False) if a.kind in ('move', 'attack')]
    if unit == 'earl' and pos in s.controls and s.controls[pos] != who:
        preview = deepcopy(s, {id(s.history): s.history})
        preview.controls[pos] = who
        if decree_options(preview, who, free=True):
            actions.append(Action('tactic', unit, source=pos, effect='earl'))
    if unit == 'herald':
        for ally in neighbors(pos):
            other = s.board.get(ally)
            if other and co.can_bolster(s, ally) and other.owner == who and other.count == 1 and s.players[who].supply[other.unit]:
                actions.append(Action('tactic', unit, source=pos, target=ally, effect='supply_bolster'))
    if unit == 'siege_tower' and st.count > 1:
        actions += [replace(a, kind='tactic', effect='double_' + a.effect) for a in maneuvers(s, pos, False) if a.kind == 'attack']
    if unit == 'war_wagon' and st.count > 1:
        for ally in neighbors(pos):
            if ally in s.board and s.board[ally].owner == who and can_enter(s, ally, who, ally):
                for path in paths(s, ally, 1):
                    actions.append(Action('tactic', unit, source=pos, target=ally, path=path, effect='wagon_push'))
    if unit in ('saboteur', 'pitch_thrower', 'vanguard'):
        for target, victim in s.board.items():
            dist = distance(pos, target)
            if victim.owner == who:
                continue
            if unit == 'saboteur' and dist in (1, 2):
                actions.append(Action('tactic', unit, source=pos, target=target, effect='poison'))
            elif st.count > 1 and target not in forts(s) and dist == (2 if unit == 'pitch_thrower' else 1):
                actions.append(Action('tactic', unit, source=pos, target=target, effect='shock'))
    # Copied tactics still consume and identify the physical Apprentice coin.
    return [replace(a, coin=st.unit) if a.coin == unit else a for a in actions]


def placements(s, who, unit, origin=None):
    result = {p for p, owner in s.controls.items() if owner == who}
    if unit == 'scout':
        result.update(q for p in positions(s, who) if p != origin for q in neighbors(p))
    if unit != 'longboat':
        result.update(p for p, st in s.board.items() if st.owner == who and co.is_ship(s, p)
                      and co.key(p) not in s.extras.get('underlays', {}))
    return sorted(p for p in result if (can_enter(s, p, who, origin) or
                  (unit != 'longboat' and p in s.board and co.is_ship(s, p)
                   and co.key(p) not in s.extras.get('underlays', {}))))


def decree_options(s, who, free=False):
    choices = []
    for decree in s.extras['decrees']:
        if not free and decree in s.extras['seals'][who]:
            continue
        if decree_actions(s, who, decree):
            choices.append(Action('proclaim', 'royal', effect=decree))
    return choices


def decree_actions(s, who, decree):
    actions = []
    if decree == 'enlist':
        if sum(s.players[who].supply.values()) >= 2:
            actions = [Action('recruit', 'royal', recruit=u) for u, n in s.players[who].supply.items() if n]
    elif decree == 'reinforce':
        actions = [Action('reinforce', 'royal', recruit=u) for u in set(s.players[who].removed)]
    elif decree == 'spy':
        actions = [Action('spy', 'royal')]
    else:
        for pos in positions(s, who):
            st = s.board[pos]
            if decree == 'redeploy':
                actions += [Action('redeploy', st.unit, source=pos, target=p) for p in placements(s, who, st.unit, pos)]
            for a in maneuvers(s, pos, False):
                if ((decree == 'march' and st.count > 1 and a.kind == 'move')
                        or (decree == 'guard' and s.controls.get(pos) == who and a.kind == 'attack')
                        or (decree == 'sacrifice' and a.kind == 'attack')):
                    actions.append(a)
    return actions


def legal_actions(s):
    from .engine import action_key
    actions = {co.tagged(v, a) for v in co.variants(s) for a in _legal_actions(v)}
    if s.pending and not s.pending[0].get('optional') and any(a.kind != 'finish' for a in actions):
        actions = {a for a in actions if a.kind != 'finish'}
    return sorted(actions, key=action_key)


def _legal_actions(s):
    from .engine import action_key
    if s.winner is not None:
        return []
    if s.pending and s.pending[0]['type'] != 'coin':
        return sorted(set(pending_actions(s, s.pending[0])), key=action_key)
    who = s.current
    player = s.players[who]
    coins = [s.pending[0]['coin']] if s.pending else sorted(set(player.hand))
    actions = []
    for coin in coins:
        actions.append(Action('pass', coin))
        if who != s.initiative and not s.initiative_claimed:
            actions.append(Action('initiative', coin))
        actions += [Action('recruit', coin, recruit=u) for u, n in player.supply.items() if n]
        if coin.startswith('decoy_'):
            actions.append(Action('return_decoy', coin))
            continue
        if coin == 'royal':
            actions.extend(decree_options(s, who))
            for pos in positions(s, who, 'royal_guard'):
                for n in (1, 2):
                    actions.extend(Action('tactic', coin, source=pos, path=p, effect='move')
                                   for p in paths(s, pos, n) if s.controls.get(p[-1]) == who)
            for pos in positions(s, who, 'apprentice'):
                for path in paths(s, pos, 1):
                    if any(p != pos and distance(p, path[-1]) == 1 for p in positions(s, who)):
                        actions.append(Action('tactic', coin, source=pos, path=path, effect='move'))
            continue
        deployed = positions(s, who, coin)
        all_deployed = [p for p, st in co.stacks(s) if st.owner == who and st.unit == coin]
        if len(all_deployed) < (2 if coin == 'footman' else 1):
            actions += [Action('deploy', coin, target=p) for p in placements(s, who, coin)]
        if any(poisoned(s, p) for p in deployed):
            actions.append(Action('cure', coin))
        for pos in deployed:
            if not poisoned(s, pos):
                if co.can_bolster(s, pos): actions.append(Action('bolster', coin, source=pos))
                actions.extend(maneuvers(s, pos))
    return sorted(set(actions), key=action_key)


def pending_actions(s, t):
    who, unit = t['player'], t['unit']
    pos = tuple(t['source']) if t.get('source') is not None else None
    kind = t['type'][2:]
    attached = pos in s.board and s.board[pos].unit == unit and s.board[pos].owner == who
    actions = []
    if kind in ('move', 'maneuver', 'attack', 'berserk', 'saboteur') and attached:
        if kind == 'berserk' and s.board[pos].count <= 1:
            return [Action('finish', unit)]
        preview = s
        if kind == 'berserk':
            preview = deepcopy(s, {id(s.history): s.history})
            preview.board[pos].count -= 1
        actions = maneuvers(preview, pos, tactics=kind in ('maneuver', 'saboteur') and not t.get('normal_only'), chain=t.get('chain', True))
        if kind == 'move': actions = [a for a in actions if a.kind == 'move']
        if kind == 'attack': actions = [a for a in actions if a.kind == 'attack']
        if kind == 'saboteur': actions = [a for a in actions if a.effect == 'poison']
    elif kind == 'defend':
        actions = [Action('defend_unit', unit, source=pos)]
        if co.has_attribute(s, pos, 'royal_guard') and s.players[who].supply[unit]:
            actions.append(Action('defend_supply', unit, source=pos))
        if co.has_attribute(s, pos, 'skirmisher') and s.extras['decoys'].get('skirmisher'):
            actions.append(Action('defend_decoy', unit, source=pos))
        for p in neighbors(pos):
            if p in s.board and s.board[p].owner == who and s.board[p].unit == 'war_wagon':
                actions.append(Action('defend_wagon', unit, source=pos, target=p))
    elif kind == 'bannerman' and attached:
        for target in neighbors(pos):
            if target in s.board and s.board[target].owner != who:
                for path in paths(s, target, 1):
                    actions.append(Action('displace', unit, source=target, path=path))
    elif kind == 'build' and attached and pos in s.controls and pos not in forts(s) and len(forts(s)) < 7:
        actions = [Action('build', unit, source=pos)]
    elif kind == 'bolster' and attached and co.can_bolster(s, pos) and s.players[who].supply[unit]:
        actions = [Action('supply_bolster', unit, source=pos, target=pos)]
    elif kind == 'recruit_bolster' and attached and (unit, True) in s.players[who].discard:
        actions = [Action('recruit_bolster', unit, source=pos, target=pos)]
    elif kind == 'deceive' and s.extras['decoys'].get('infiltrator' if unit == 'apprentice' else unit):
        actions = [Action('deceive', unit)]
    elif kind == 'cull' and s.players[1-who].supply.get(t['victim'], 0):
        actions = [Action('cull', unit, recruit=t['victim'])]
    elif kind == 'drum':
        actions = [Action('drum', unit, recruit=u, effect=str(owner))
                   for owner, p in enumerate(s.players) for u, n in p.supply.items() if n]
    elif kind == 'decree':
        actions = decree_options(s, who, free=True)
    elif kind == 'decree_effect':
        actions = decree_actions(s, who, t['decree'])
    elif kind == 'recruit':
        actions = [Action('recruit', unit, recruit=u) for u, n in s.players[who].supply.items() if n]
    elif kind == 'spy':
        actions = [Action('spy_discard', unit, recruit=u) for u in set(s.players[1-who].hand)]
    elif kind == 'order':
        actions = [Action('resolve', unit, effect=str(i)) for i in range(len(t['groups']))]
    actions += co.pending_actions(s, t)
    if t.get('optional') or not actions:
        actions.append(Action('finish', unit))
    return actions


def ordered(groups, who):
    groups = [g for g in groups if g]
    if not groups:
        return []
    if len(groups) == 1:
        return groups[0]
    return [task('order', who, groups=groups)]


def relocate_tasks(tasks, start, end, units):
    for t in tasks:
        if tuple(t.get('source') or ()) == start and t.get('unit') in units:
            t['source'] = list(end)
        for group in t.get('groups', []): relocate_tasks(group, start, end, units)


def move(s, start, end, events):
    if start == end: return
    ship = co.is_ship(s, start)
    if ship:
        transports = s.extras.setdefault('transports', [])
        if s.board[start].unit not in transports: transports.append(s.board[start].unit)
    st = s.board.pop(start)
    carried = co.underlays(s).pop(co.key(start), None)
    moving = [st.unit]
    if carried and ship:
        co.underlays(s)[co.key(end)] = carried
        moving.append(carried['unit'])
    elif carried:
        s.board[start] = Stack(**carried)
    if end in s.board:
        other = s.board.pop(end)
        co.underlays(s)[co.key(end)] = dict(owner=other.owner, unit=other.unit, count=other.count)
    s.board[end] = st
    for poisoner, p in s.extras['poison'].items():
        target = s.extras.get('poison_units', {}).get(poisoner, st.unit)
        if p == list(start) and target in moving: s.extras['poison'][poisoner] = list(end)
    relocate_tasks(s.pending, start, end, moving)
    event(events, 'move', player=st.owner, unit=st.unit, start=start, end=end)
    if carried and ship:
        event(events, 'transport', player=st.owner, unit=carried['unit'], start=start, end=end)


def remove_unit(s, pos):
    st = s.board.pop(pos)
    other = co.underlays(s).pop(co.key(pos), None)
    if other: s.board[pos] = Stack(**other)
    s.extras['poison'] = {u: p for u, p in s.extras['poison'].items()
                          if p != list(pos) or s.extras.get('poison_units', {}).get(u, st.unit) != st.unit}
    return st


def damage(s, pos, events):
    if pos not in s.board:
        return
    st = s.board[pos]
    trophy = co.captured(s, st.unit)
    st.count -= 1
    if trophy:
        owner, unit = trophy.pop(0)
        s.players[owner].removed.append(unit)
    else:
        s.players[st.owner].removed.append(st.unit)
    event(events, 'damage', player=st.owner, unit=st.unit, pos=pos, remaining=st.count)
    if not st.count:
        champion = any(co.has_attribute(s, pos, u) for u in co.CHAMPIONS)
        remove_unit(s, pos)
        if champion:
            lost = s.extras.setdefault('lost_markers', [0, 0])
            lost[1-st.owner] += 1
            event(events, 'champion_destroyed', player=st.owner, unit=st.unit,
                  beneficiary=1-st.owner, target=co.victory_target(s, 1-st.owner))
            co.check_victory(s, events)


def shock(s, pos, events):
    if pos not in s.board:
        return
    st = s.board[pos]
    trophy = co.captured(s, st.unit)
    for owner, unit in trophy:
        s.players[owner].discard.append((unit, True))
    s.players[st.owner].discard.extend((st.unit, True) for _ in range(st.count-len(trophy)))
    trophy.clear()
    event(events, 'shock', player=st.owner, unit=st.unit, pos=pos, count=st.count)
    remove_unit(s, pos)


def unbolster(s, pos, events):
    st = s.board[pos]
    st.count -= 1
    trophy = co.captured(s, st.unit)
    if trophy:
        owner, unit = trophy.pop(0)
        s.players[owner].discard.append((unit, True))
    else:
        s.players[st.owner].discard.append((st.unit, True))
    event(events, 'unbolster', player=st.owner, unit=st.unit, pos=pos)


def move_hooks(s, pos):
    st = s.board[pos]
    if co.is_ship(s, pos) and co.key(pos) in s.extras.get('underlays', {}):
        passenger = s.extras['underlays'][co.key(pos)]['unit']
        preview = deepcopy(s, {id(s.history): s.history})
        co.expose(preview, pos, passenger)
        return ordered([move_hooks(preview, pos), maneuver_hooks(preview, pos)], st.owner)
    if co.has_attribute(s, pos, 'sapper') and pos in s.controls and pos not in forts(s) and len(forts(s)) < 7:
        return [task('build', st.owner, st.unit, pos, optional=True)]
    if co.has_attribute(s, pos, 'war_drummer'):
        return [task('drum', st.owner, st.unit, pos, optional=True)]
    return []


def maneuver_hooks(s, pos):
    if pos not in s.board:
        return []
    st = s.board[pos]
    if co.has_attribute(s, pos, 'bannerman'):
        return [task('bannerman', st.owner, st.unit, pos, optional=True)]
    if co.has_attribute(s, pos, 'berserker') and st.count > 1:
        return [task('berserk', st.owner, st.unit, pos, optional=True)]
    return []


def control(s, pos, events):
    st = s.board[pos]
    s.controls[pos] = st.owner
    event(events, 'control', player=st.owner, unit=st.unit, pos=pos)
    co.check_victory(s, events)
    hooks = []
    if co.has_attribute(s, pos, 'infiltrator') and s.extras['decoys'].get('infiltrator'):
        hooks.append(task('deceive', st.owner, st.unit, pos, optional=True))
    if co.has_attribute(s, pos, 'warrior_priest'):
        hooks.append(task('draw', st.owner, st.unit, pos))
    if any(other.owner != st.owner and (other.unit == 'admiral' or s.extras.get('copies', {}).get(other.unit, {}).get('unit') == 'admiral') for _, other in co.stacks(s)):
        hooks.append(task('admirals', st.owner))
    return hooks


def bolster(s, pos, events):
    st = s.board[pos]
    st.count += 1
    event(events, 'bolster', player=st.owner, unit=st.unit, pos=pos)
    return [task('move', st.owner, st.unit, pos, optional=True)] if co.has_attribute(s, pos, 'raider') else []


def deploy_hooks(s, pos):
    st = s.board[pos]
    kind = next((v for u, v in {'earl': 'move', 'siege_tower': 'bolster', 'vanguard': 'maneuver'}.items() if co.has_attribute(s, pos, u)), None)
    return [task(kind, st.owner, st.unit, pos, optional=True)] if kind else []


def recruit(s, who, unit, events):
    p = s.players[who]
    p.supply[unit] -= 1
    p.discard.append((unit, True))
    event(events, 'recruit', player=who, unit=unit)
    result = []
    for pos in positions(s, who, unit):
        if unit in ('mercenary', 'saboteur'):
            result.append(task('maneuver' if unit == 'mercenary' else 'saboteur', who, unit, pos, optional=True,
                               normal_only=unit == 'mercenary'))
        if unit == 'pitch_thrower':
            result.append(task('recruit_bolster', who, unit, pos, optional=True))
    return result


def attack(s, pos, target, events, sacrifice=False):
    st = s.board[pos]
    event(events, 'attack', player=st.owner, unit=st.unit, source=pos, target=target)
    after = task('after_attack', st.owner, st.unit, pos, sacrifice=sacrifice,
                 victim=None, victim_owner=1-st.owner, poisoned=False, retaliates=False,
                 **({'before_removed':list(s.players[1-st.owner].removed)} if 'mastery' in s.extras['enabled'] else {}))
    if target in forts(s):
        s.extras['forts'].remove(list(target))
        event(events, 'fort_destroyed', player=st.owner, pos=target)
        return [after]
    victim = s.board[target]
    after.update(victim=victim.unit, victim_owner=victim.owner, poisoned=poisoned(s, target),
                 retaliates=co.has_attribute(s, target, 'pikeman') and distance(pos, target) == 1)
    defend = task('defend', victim.owner, victim.unit, target)
    if len(pending_actions(s, defend)) > 1:
        return [defend, after]
    damage(s, target, events)
    return [after]


def after_attack(s, t, events):
    pos = tuple(t['source'])
    co.expose(s, pos, t['unit'])
    who, unit = t['player'], t['unit']
    if t['retaliates'] and pos in s.board and s.board[pos].unit == unit: damage(s, pos, events)
    if t['sacrifice'] and pos in s.board and s.board[pos].unit == unit: damage(s, pos, events)
    groups = []
    if (unit == 'assassin' or (s.extras.get('copies', {}).get(unit, {}).get('unit') == 'assassin' and s.extras['copies'][unit]['attributes'])) and t['poisoned'] and s.players[t['victim_owner']].supply.get(t['victim'], 0):
        groups.append([task('cull', who, unit, pos, victim=t['victim'], optional=True)])
    if pos in s.board and s.board[pos].unit == unit:
        if co.has_attribute(s, pos, 'swordsman'): groups.append([task('move', who, unit, pos, optional=True)])
        if co.has_attribute(s, pos, 'warrior_priest'): groups.append([task('draw', who, unit, pos)])
        if co.has_attribute(s, pos, 'overlord') and s.board[pos].count < 5:
            lost = Counter(s.players[1-who].removed) - Counter(t.get('before_removed', []))
            if lost: groups.append([task('capture', who, unit, pos, choices=list(lost.elements()), optional=True)])
        groups.append(maneuver_hooks(s, pos))
    result = ordered(groups, who)
    # Rearguard follows all effects caused by the attack, before the next attack.
    if t['victim']:
        for p in positions(s, t['victim_owner'], 'rearguard'):
            if t['victim'] != 'rearguard':
                result.append(task('move', t['victim_owner'], 'rearguard', p, optional=True))
    return result


def deceive(s, who, unit, events):
    s.extras['decoys'][unit] = False
    s.players[1-who].discard.append(('decoy_' + unit, True))
    event(events, 'deceive', player=who, unit=unit)


def execute(s, a, events, continuation=None):
    who, coin = s.current, a.coin
    pos = a.source or next(iter(positions(s, who, coin)), None)
    t = continuation or {}
    kind = a.kind
    extra = co.execute(s, a, events, t)
    if extra is not None: return extra
    if kind == 'finish': return []
    if kind == 'resolve':
        groups = deepcopy(t['groups'])
        chosen = groups.pop(int(a.effect))
        return chosen + ordered(groups, who)
    if kind == 'pass': return []
    if kind == 'initiative':
        s.initiative, s.initiative_claimed = who, True
        return [task('emissaries', who)]
    if kind == 'return_decoy':
        s.extras['decoys'][coin.removeprefix('decoy_')] = True
        return []
    if kind == 'cure':
        targets = {p for p, st in co.stacks(s) if st.owner == who and st.unit == coin}
        s.extras['poison'] = {u: p for u, p in s.extras['poison'].items() if tuple(p) not in targets or s.extras.get('poison_units', {}).get(u, coin) != coin}
        event(events, 'cure', player=who, unit=coin)
        return []
    if kind == 'recruit':
        hooks = recruit(s, who, a.recruit, events)
        if t.get('decree') == 'enlist':
            return [task('recruit', who, first_hooks=hooks)]
        if 'first_hooks' in t:
            return ordered([t['first_hooks'], hooks], who)
        return hooks
    if kind == 'deploy':
        if a.target in s.board:
            co.underlays(s)[co.key(a.target)] = dict(owner=s.board[a.target].owner, unit=s.board[a.target].unit, count=s.board[a.target].count)
        s.board[a.target] = Stack(who, coin)
        return deploy_hooks(s, a.target)
    if kind == 'redeploy':
        st = s.board[pos]
        carried = co.underlays(s).pop(co.key(pos), None) if co.is_ship(s, pos) else None
        remove_unit(s, pos)
        if a.target in s.board:
            co.underlays(s)[co.key(a.target)] = dict(owner=s.board[a.target].owner, unit=s.board[a.target].unit, count=s.board[a.target].count)
        if carried: co.underlays(s)[co.key(a.target)] = carried
        s.board[a.target] = st
        event(events, 'redeploy', player=who, unit=st.unit, start=pos, end=a.target)
        return deploy_hooks(s, a.target)
    if kind == 'bolster': return bolster(s, pos, events)
    if kind in ('supply_bolster', 'recruit_bolster'):
        unit = s.board[a.target].unit
        if kind == 'supply_bolster': s.players[who].supply[unit] -= 1
        else: s.players[who].discard.remove((unit, True))
        return bolster(s, a.target, events)
    if kind == 'reinforce':
        s.players[who].removed.remove(a.recruit)
        s.players[who].supply[a.recruit] += 1
        return []
    if kind == 'build':
        s.extras['forts'].append(list(pos))
        event(events, 'fort_built', player=who, unit=coin, pos=pos)
        return []
    if kind == 'deceive':
        deceive(s, who, 'infiltrator' if coin == 'apprentice' else coin, events)
        return []
    if kind == 'cull':
        p = s.players[1-who]
        p.supply[a.recruit] -= 1
        p.removed.append(a.recruit)
        event(events, 'supply_damage', player=1-who, unit=a.recruit)
        return []
    if kind == 'drum':
        owner = int(a.effect)
        p = s.players[owner]
        p.supply[a.recruit] -= 1
        p.bag.append(a.recruit)
        event(events, 'bag_top', player=owner, unit=a.recruit)
        return []
    if kind == 'spy':
        event(events, 'spy_view', visible_to=who, player=who, hand=tuple(sorted(s.players[1-who].hand)))
        return [task('spy', who, optional=True)]
    if kind == 'spy_discard':
        p = s.players[1-who]
        p.hand.remove(a.recruit)
        p.discard.append((a.recruit, False))
        event(events, 'spy_discard', player=1-who)
        from .engine import _draw_extra
        _draw_extra(s, 1-who, events)
        return []
    if kind == 'proclaim':
        if not t: s.extras['seals'][who].append(a.effect)
        result = [task('decree_effect', who, decree=a.effect)]
        for p in positions(s, who, 'herald'):
            result.append(task('maneuver', who, 'herald', p, optional=True))
        return result
    if kind.startswith('defend_'):
        if kind == 'defend_supply':
            s.players[who].supply[coin] -= 1
            s.players[who].removed.append(coin)
            event(events, 'supply_damage', player=who, unit=coin)
        elif kind == 'defend_decoy': deceive(s, who, 'skirmisher' if coin == 'apprentice' else coin, events)
        else: damage(s, a.target if kind == 'defend_wagon' else pos, events)
        return []
    if kind == 'displace':
        move(s, pos, a.path[-1], events)
        return []
    st = s.board[pos]
    unit, owner = co.role(s, pos), st.owner
    effect = a.effect or kind
    groups, suffix = [], []
    if t.get('type') == 'x_berserk': unbolster(s, pos, events)
    if effect == 'command':
        target = s.board[a.target]
        return [task('maneuver', owner, target.unit, a.target), task('shock_self', owner, target.unit, a.target)]
    if effect == 'wagon_push':
        ally = a.target
        move(s, ally, a.path[-1], events)
        groups.append(move_hooks(s, a.path[-1]))
        groups.append(maneuver_hooks(s, a.path[-1]))
        move(s, pos, ally, events)
        groups.append(move_hooks(s, ally))
        groups.append(maneuver_hooks(s, ally))
        return ordered(groups, owner)
    if effect.startswith('bishop_'):
        groups.append(recruit(s, owner, a.recruit, events))
        effect = effect.removeprefix('bishop_')
    if kind == 'tactic' and unit == 'footman':
        suffix += [task('maneuver', owner, unit, p, normal_only=True)
                   for p in positions(s, owner, unit) if p != pos]
    if effect.startswith('double_'):
        suffix.append(task('attack', owner, unit, pos))
        effect = effect.removeprefix('double_')
    if unit == 'raider' and effect == 'move_control' or unit == 'pitch_thrower' and effect == 'shock':
        unbolster(s, pos, events)
    for end in a.path:
        if effect == 'charge_shock' and end in s.board and end != pos:
            shock(s, end, events)
        move(s, pos, end, events)
        pos = end
    if a.path:
        groups.append(move_hooks(s, pos))
    if effect in ('attack', 'fort_attack'):
        # Attack is resolved before optional attributes; defender choices cannot
        # be bypassed by triggering an attacker's movement or extra draw early.
        return attack(s, pos, a.target, events, sacrifice=t.get('decree') == 'sacrifice') + ordered(groups, owner) + suffix
    if effect in ('control', 'move_control', 'earl'):
        groups.append(control(s, pos, events))
        if effect == 'earl': suffix.insert(0, task('decree', owner, unit, pos))
    elif effect == 'poison':
        s.extras['poison'][unit] = list(a.target)
        if 'poison_units' in s.extras: s.extras['poison_units'][unit] = s.board[a.target].unit
        event(events, 'poison', player=owner, unit=unit, pos=a.target)
    elif effect == 'shock':
        shock(s, a.target, events)
    elif effect == 'supply_bolster':
        other = s.board[a.target]
        s.players[owner].supply[other.unit] -= 1
        groups.append(bolster(s, a.target, events))
    groups.append(maneuver_hooks(s, pos))
    return ordered(groups, owner) + suffix


def pump(s, events):
    from .engine import _draw_extra, _new_round
    while s.pending and s.winner is None:
        t = s.pending[0]
        kind = t['type']
        if t.get('source') is not None: co.expose(s, tuple(t['source']), t['unit'])
        if co.pump_task(s, t, events):
            co.normalize(s)
            continue
        if kind == 'x_draw':
            s.pending.pop(0)
            extra = _draw_extra(s, t['player'], events)
            if extra: s.pending.insert(0, extra)
        elif kind == 'x_after_attack':
            s.pending.pop(0)
            s.pending = after_attack(s, t, events) + s.pending
        elif kind == 'x_shock_self':
            s.pending.pop(0)
            pos = tuple(t['source'])
            if pos in s.board and s.board[pos].unit == t['unit']:
                shock(s, pos, events)
        else:
            s.current = t['player']
            return
    if s.winner is not None:
        s.pending.clear()
        s.turn_owner = None
        return
    owner = s.turn_owner
    s.turn_owner = None
    if s.players[1-owner].hand: s.current = 1-owner
    elif s.players[owner].hand: s.current = owner
    else: _new_round(s, events)


def apply_action(state, action):
    from .engine import IllegalAction
    if not isinstance(action, Action) or action not in legal_actions(state):
        raise IllegalAction('行动不合法，状态未改变')
    s = deepcopy(state, {id(state.history): state.history})
    events = []
    who = s.current
    continuation = s.pending.pop(0) if s.pending else None
    free = continuation is not None and continuation['type'] != 'coin'
    if s.turn_owner is None: s.turn_owner = who
    hidden = action.kind in ('pass', 'initiative', 'recruit') and not free
    event(events, 'action', player=who, kind=action.kind, coin=None if hidden else action.coin,
          path=action.path, target=action.target, recruit=None if action.kind == 'spy_discard' else action.recruit,
          after=action.after, source=action.source, effect=action.effect, free=free, **({'actor':action.actor} if action.actor else {}), **({'target_unit':action.target_unit} if action.target_unit else {}))
    if not free:
        s.players[who].hand.remove(action.coin)
        if hidden: event(events, 'payment', visible_to=who, coin=action.coin)
        if action.kind not in ('deploy', 'bolster', 'return_decoy'):
            s.players[who].discard.append((action.coin, not hidden))
    co.expose(s, action.source, action.actor)
    co.expose(s, action.target, action.target_unit)
    if continuation and continuation.get('source') is not None:
        co.expose(s, tuple(continuation['source']), continuation['unit'])
    tasks = execute(s, action, events, continuation if free else None)
    co.normalize(s)
    s.pending = tasks + s.pending
    pump(s, events)
    co.normalize(s)
    s.history += tuple(events)
    return s, tuple(events)


def observe_extras(s, player):
    result = deepcopy(s.extras)
    if s.pending and s.pending[0]['type'] == 'x_spy' and s.current == player:
        result['spied_hand'] = sorted(s.players[1-player].hand)
    return result


def validate_extras(s):
    from .engine import IllegalAction
    def require(ok, msg):
        if not ok: raise ValueError(msg)
    x = s.extras
    require(s.version in ('expansions-1', 'expansions-2'), 'expanded rules version missing')
    require(set(x['enabled']) <= EXPANSIONS.keys(), 'unknown expansion')
    require(len(forts(s)) == len(x['forts']) and forts(s) <= LOCATIONS and len(forts(s)) <= 7, 'invalid fortifications')
    require(not forts(s) or 'siege' in x['enabled'], 'fortifications without siege')
    for poisoner, pos in x['poison'].items():
        require(poisoner in ('assassin', 'saboteur', 'apprentice') and tuple(pos) in s.board, 'invalid poison marker')
        owner = next((i for i, p in enumerate(s.players) if poisoner in p.supply), None)
        require(owner is not None and s.board[tuple(pos)].owner != owner, 'invalid poisoned unit')
    families = [unit_family(u) for p in s.players for u in p.supply]
    require(len(set(families)) == 8, 'alternate units share coins')
    require(all(UNITS[u].expansion in x['enabled'] for p in s.players for u in p.supply), 'unit expansion disabled')
    require(len(x['decrees']) == (3 if 'nobility' in x['enabled'] else 0)
            and len(set(x['decrees'])) == len(x['decrees']) and set(x['decrees']) <= DECREES.keys(), 'invalid decrees')
    require(len(x['seals']) == 2 and all(len(set(z)) == len(z) and set(z) <= set(x['decrees']) for z in x['seals']), 'invalid seals')
    expected_decoys = {u for p in s.players for u in p.supply if u in ('infiltrator', 'skirmisher')}
    require(set(x['decoys']) == expected_decoys, 'invalid decoy supply')
    for unit, available in x['decoys'].items():
        require(type(available) is bool, 'invalid decoy status')
        owner = next(i for i, p in enumerate(s.players) if unit in p.supply)
        count = 0
        for who, p in enumerate(s.players):
            coins = p.bag + p.hand + [c for c, _ in p.discard]
            n = coins.count('decoy_' + unit)
            require(not n or who != owner, 'decoy in its owner bag')
            count += n
        require(count + int(available) == 1, 'decoy conservation failed')
    for p in s.players:
        require(all(not c.startswith('decoy_') or c.removeprefix('decoy_') in expected_decoys
                    for c in p.hand + p.bag + [c for c, _ in p.discard]), 'unknown decoy')
        require(not any(c.startswith('decoy_') for c in p.removed), 'decoy cannot be destroyed')

    require(len(x.get('lost_markers', [0, 0])) == 2 and all(type(n) is int and 0 <= n <= 6 for n in x.get('lost_markers', [0, 0])), 'invalid lost control markers')
    require(not any(x.get('lost_markers', [])) or 'champions' in x['enabled'], 'champion penalty without expansion')
    for p, other in x.get('underlays', {}).items():
        pos = co.coord(p)
        require(pos in s.board and other['owner'] == s.board[pos].owner and (other['unit'] == 'longboat' and other['count'] == 1 or other['unit'] == 'apprentice' and other['unit'] in x.get('transports', [])) and s.board[pos].unit != other['unit'], 'invalid transport')
    for p, st in co.stacks(s):
        require(st.unit != 'longboat' or st.count == 1, 'longboat cannot be bolstered')
    for unit, trophies in x.get('captured', {}).items():
        live = next((st for _, st in co.stacks(s) if st.unit == unit), None)
        require(not trophies or live is not None and live.count > len(trophies), 'captured coins without captor')
        require(all(owner in (0, 1) and coin in s.players[owner].supply and owner != live.owner for owner, coin in trophies), 'invalid captured coins')
    for unit, copy in x.get('copies', {}).items():
        require(unit == 'apprentice' and copy['unit'] in UNITS and copy['unit'] != unit and type(copy['attributes']) is bool and type(copy['tactics']) is bool, 'invalid copied ability')
