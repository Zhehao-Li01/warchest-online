"""War Chest Online additions and shared public state for their interactions.

Underlays hold the second unit on a transport hex. The canonical board displays
its passenger; projection exposes either unit to the existing rule resolver.
No private bag/hand information participates in these projections.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
from itertools import product

from .board import HEXES, SEA_HEXES, FULL_HEXES, all_neighbors, distance
from .model import Stack, Action

CHAMPIONS = {'commander', 'dragoon', 'marksman', 'ranger'}


def key(pos):
    return ','.join(map(str, pos))


def coord(value):
    return tuple(map(int, value.split(',')))


def role(s, pos):
    st = s.board[pos]
    return s.extras.get('copies', {}).get(st.unit, {}).get('unit', st.unit)


def has_attribute(s, pos, unit):
    st = s.board[pos]
    copy = s.extras.get('copies', {}).get(st.unit)
    return (copy['unit'] == unit and copy['attributes']) if copy else st.unit == unit


def board_hexes(s):
    return FULL_HEXES if 'high_seas' in s.extras.get('enabled', []) else HEXES


def underlays(s):
    return s.extras.get('underlays', {})


def stacks(s):
    yield from s.board.items()
    for p, st in s.extras.get('underlays', {}).items():
        yield coord(p), Stack(**st)


def victory_target(s, who):
    return 6 - s.extras.get('lost_markers', [0, 0])[who]


def check_victory(s, events):
    from .expansions import event
    if s.winner is not None:
        return
    for who in (0, 1):
        if list(s.controls.values()).count(who) >= victory_target(s, who):
            s.winner = who
            event(events, 'win', player=who, **({'target':victory_target(s, who)} if victory_target(s, who) != 6 else {}))
            return


def expose(s, pos, unit):
    if pos is None or not unit or pos not in s.board or s.board[pos].unit == unit:
        return
    other = s.extras.get('underlays', {}).get(key(pos))
    if other and other['unit'] == unit:
        underlays(s)[key(pos)] = asdict(s.board[pos])
        s.board[pos] = Stack(**other)


def normalize(s):
    for p, other in list(s.extras.get('underlays', {}).items()):
        pos = coord(p)
        if pos not in s.board:
            s.board[pos] = Stack(**underlays(s).pop(p))
        elif is_ship(s, pos):
            underlays(s)[p] = asdict(s.board[pos])
            s.board[pos] = Stack(**other)


@contextmanager
def projected(s, pos, unit):
    expose(s, pos, unit)
    try:
        yield
    finally:
        normalize(s)


def variants(s):
    positions = list(s.extras.get('underlays', {}))
    if not positions:
        yield s
        return
    for flags in product((False, True), repeat=len(positions)):
        preview = deepcopy(s, {id(s.history): s.history})
        for p, swap in zip(positions, flags):
            if swap:
                expose(preview, coord(p), preview.extras['underlays'][p]['unit'])
        yield preview


def tagged(s, a):
    # Only transport decisions need the extra unit identity. Ordinary actions
    # keep their existing serialization and remain deduplicated across views.
    ports = s.extras.get('underlays', {})
    return replace(a,
                   actor=a.actor or (s.board[a.source].unit if a.source in s.board and key(a.source) in ports else None),
                   target_unit=a.target_unit or (s.board[a.target].unit if a.target in s.board and key(a.target) in ports else None))


def is_ship(s, pos):
    if pos not in s.board: return False
    unit = s.board[pos].unit
    return has_attribute(s, pos, 'longboat') or (unit in s.extras.get('transports', []) and key(pos) in s.extras.get('underlays', {}))


def can_share(s, start, end):
    if start not in s.board or end not in s.board or start == end:
        return False
    a, b = s.board[start], s.board[end]
    if a.owner != b.owner or key(end) in s.extras.get('underlays', {}):
        return False
    return ((is_ship(s, start) and key(start) not in s.extras.get('underlays', {}) and not is_ship(s, end))
            or (is_ship(s, end) and not is_ship(s, start)))


def can_bolster(s, pos):
    return not is_ship(s, pos)


def captured(s, unit):
    return s.extras.get('captured', {}).get(unit, [])


def copy_options(s, pos):
    # Copying a second Apprentice would create unbounded self-referential rules.
    # There is only one physical Apprentice in a legal two-player army.
    return [(p, st.unit) for p, st in stacks(s)
            if st.owner == s.board[pos].owner and distance(pos, p) == 1 and st.unit != 'apprentice']


def extra_maneuvers(s, pos, tactics, chain):
    from . import expansions as ex
    st = s.board[pos]
    unit = role(s, pos)
    actions = []
    if has_attribute(s, pos, 'pirate'):
        for path in ex.paths(s, pos, 2):
            if any(p in SEA_HEXES for p in all_neighbors(path[-1])):
                actions.append(Action('move', st.unit, source=pos, path=path))
        if pos in SEA_HEXES:
            for end in sorted(SEA_HEXES):
                if end != pos and ex.can_enter(s, end, st.owner, pos):
                    actions.append(Action('move', st.unit, source=pos, path=(end,)))
    if not tactics:
        return actions
    if unit == 'commander' and chain:
        for p, other in stacks(s):
            if other.owner == st.owner and distance(pos, p) <= 2:
                preview = deepcopy(s, {id(s.history): s.history})
                expose(preview, p, other.unit)
                if ex.maneuvers(preview, p, chain=False):
                    actions.append(Action('tactic', st.unit, source=pos, target=p, target_unit=other.unit, effect='command_free'))
    if unit == 'ranger':
        for target in all_neighbors(pos):
            if ex.attackable(s, pos, target) and (any(ex.paths(s, pos, 1)) or
                    (target not in ex.forts(s) and s.board[target].count == 1)):
                actions.append(Action('tactic', st.unit, source=pos, target=target, effect='attack_move'))
    if unit == 'alchemist':
        for p, other in stacks(s):
            if p == pos or other.owner != st.owner or distance(pos, p) > 2:
                continue
            if ((key(p) in s.extras.get('underlays', {}) and other.unit == 'longboat') or
                    (key(pos) in s.extras.get('underlays', {}) and st.unit == 'longboat')):
                continue  # A loaded carrier cannot swap whole hexes with a single unit.
            if (key(pos) in s.extras.get('underlays', {}) and other.unit == 'longboat') or (key(p) in s.extras.get('underlays', {}) and st.unit == 'longboat'):
                continue
            if p in SEA_HEXES and st.unit != 'pirate' or pos in SEA_HEXES and other.unit != 'pirate':
                continue
            if p in ex.forts(s) and s.controls[p] == 1-st.owner or pos in ex.forts(s) and s.controls[pos] == 1-st.owner:
                continue
            actions.append(Action('tactic', st.unit, source=pos, target=p, effect='swap'))
    if unit == 'apprentice':
        for p, other in copy_options(s, pos):
            for mode in ('both', 'attribute', 'tactic'):
                preview = deepcopy(s, {id(s.history): s.history})
                preview.extras.setdefault('copies', {})[st.unit] = {'unit':other, 'attributes':mode != 'tactic', 'tactics':mode != 'attribute'}
                if ex.maneuvers(preview, pos, chain=False):
                    actions.append(Action('tactic', st.unit, source=pos, target=p, target_unit=other,
                                          recruit=other, effect='copy_' + mode))
    if unit == 'emissary' and pos in s.controls and s.controls[pos] != st.owner:
        actions.append(Action('tactic', st.unit, source=pos, effect='emissary'))
    if unit == 'corsair':
        from .board import DIRECTIONS, add
        for d in DIRECTIONS:
            over = add(pos, d)
            end = add(over, d)
            if over in s.board and over not in ex.forts(s) and ex.can_enter(s, end, st.owner, pos) and end in HEXES:
                actions.append(Action('tactic', st.unit, source=pos, path=(end,), effect='vault'))
    return actions


def pending_actions(s, t):
    from . import expansions as ex
    unit, who = t['unit'], t['player']
    pos = tuple(t['source']) if t.get('source') is not None else None
    attached = pos in s.board and s.board[pos].unit == unit and s.board[pos].owner == who
    kind = t['type'][2:]
    actions = []
    if kind == 'capture' and attached and s.board[pos].count < 5:
        actions = [Action('capture', unit, source=pos, recruit=c) for c in set(t['choices']) if c in s.players[1-who].removed]
    elif kind == 'vault_follow' and attached:
        actions = [a for a in ex.maneuvers(s, pos, False) if a.kind == 'attack']
        # Corsair's restriction excludes normal attacks, but the vault explicitly grants one.
        actions += [ex.attack_action(s, pos, p) for p in all_neighbors(pos) if ex.attackable(s, pos, p, normal=False)]
        if s.board[pos].count > 1:
            actions += [Action('spend_move', unit, source=pos, path=p) for p in ex.paths(s, pos, 1)]
    elif kind == 'emissary_initiative' and not s.initiative_claimed:
        actions = [Action('change_initiative', unit, source=pos, effect='take' if s.initiative != who else 'give')]
    return actions


def execute(s, a, events, t):
    """None means the standard resolver owns this action."""
    from . import expansions as ex
    who = s.current
    pos = a.source
    effect = a.effect or a.kind
    if a.kind == 'capture':
        st = s.board[pos]
        s.players[1-who].removed.remove(a.recruit)
        s.extras.setdefault('captured', {}).setdefault(st.unit, []).append([1-who, a.recruit])
        ex.event(events, 'capture', player=who, unit=st.unit, victim=a.recruit)
        return ex.bolster(s, pos, events)
    if a.kind == 'spend_move':
        ex.unbolster(s, pos, events)
        ex.move(s, pos, a.path[-1], events)
        return ex.ordered([ex.move_hooks(s, a.path[-1]), ex.maneuver_hooks(s, a.path[-1])], who)
    if a.kind == 'change_initiative':
        s.initiative = who if a.effect == 'take' else 1-who
        s.initiative_claimed = True
        ex.event(events, 'initiative_changed', player=who, initiative=s.initiative)
        return [ex.task('emissaries', who)] if a.effect == 'take' else []
    if effect == 'command_free':
        other = s.board[a.target]
        return [ex.task('maneuver', who, other.unit, a.target)]
    if effect.startswith('copy_'):
        mode = effect.removeprefix('copy_')
        s.extras.setdefault('copies', {})[s.board[pos].unit] = {'unit':a.recruit, 'attributes':mode != 'tactic', 'tactics':mode != 'attribute'}
        ex.event(events, 'copy', player=who, unit=a.coin, copied=a.recruit, mode=mode)
        return [ex.task('maneuver', who, a.coin, pos), ex.task('uncopy', who, a.coin)]
    if effect == 'swap':
        st, other = s.board[pos], s.board[a.target]
        s.board[pos], s.board[a.target] = other, st
        for poisoner, p in s.extras['poison'].items():
            identity = s.extras.get('poison_units', {}).get(poisoner)
            if p == list(pos) and identity in (None, st.unit): s.extras['poison'][poisoner] = list(a.target)
            elif p == list(a.target) and identity in (None, other.unit): s.extras['poison'][poisoner] = list(pos)
        ex.relocate_tasks(s.pending, pos, a.target, [st.unit])
        ex.relocate_tasks(s.pending, a.target, pos, [other.unit])
        ex.event(events, 'swap', player=who, unit=st.unit, source=pos, target=a.target)
        return [ex.task('maneuver', who, st.unit, a.target, optional=True, normal_only=True)]
    if effect == 'emissary':
        hooks = ex.control(s, pos, events)
        return hooks + [ex.task('emissary_initiative', who, s.board[pos].unit, pos)]
    if effect == 'attack_move':
        unit = s.board[pos].unit
        return ex.attack(s, pos, a.target, events) + [ex.task('move', who, unit, pos)]
    if effect == 'vault':
        unit = s.board[pos].unit
        ex.move(s, pos, a.path[-1], events)
        return ex.ordered([ex.move_hooks(s, a.path[-1]), ex.maneuver_hooks(s, a.path[-1])], who) + [ex.task('vault_follow', who, unit, a.path[-1], optional=True)]
    return None


def pump_task(s, t, events):
    from . import expansions as ex
    kind = t['type']
    if kind == 'x_uncopy':
        s.pending.pop(0)
        s.extras.get('copies', {}).pop(t['unit'], None)
        return True
    if kind in ('x_emissaries', 'x_admirals'):
        s.pending.pop(0)
        hooks = []
        for pos, st in stacks(s):
            preview = deepcopy(s, {id(s.history): s.history})
            expose(preview, pos, st.unit)
            if has_attribute(preview, pos, 'emissary' if kind == 'x_emissaries' else 'admiral'):
                if kind == 'x_admirals' and st.owner == t['player']: continue
                hooks.append(ex.task('maneuver', st.owner, st.unit, pos, optional=True))
        s.pending = hooks + s.pending
        return True
    return False
