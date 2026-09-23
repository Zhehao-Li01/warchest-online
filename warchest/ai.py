"""Baseline agent. Its interface contains no privileged game state."""


def choose_action(observation, actions, rng):
    if observation["current"] != observation["player"]:
        raise ValueError("AI can only act on its own turn")
    if not actions:
        raise ValueError("no legal actions")
    return rng.choice(actions)


def choose_basic_action(observation, actions, rng):
    """Small transparent heuristic, using only the same observation as a human.

    No access to State, opponent hand, bag order, or game random generator.
    Legal action generation stays authoritative in the engine.
    """
    if observation.get("extras"):
        return choose_expanded_action(observation, actions, rng)
    from .board import distance
    from .units import UNITS

    if observation["current"] != observation["player"] or not actions:
        raise ValueError("AI needs its own turn and legal actions")
    who = observation["player"]
    board = {tuple(s["pos"]): s for s in observation["board"]}
    controls = {tuple(c["pos"]): c["owner"] for c in observation["controls"]}
    own_points = sum(o == who for o in controls.values())
    enemy_points = sum(o == 1 - who for o in controls.values())
    friendly = [s for s in board.values() if s["owner"] == who]
    enemies = [s for s in board.values() if s["owner"] != who]
    goals = [p for p, o in controls.items() if o != who and (p not in board or board[p]["owner"] == who)]
    me = observation["players"][who]

    def objective_distance(pos):
        # Seek accessible control points rather than chasing units indefinitely.
        return min((distance(pos, p) for p in goals if p not in board or p == pos), default=3)

    def threat(pos):
        return sum(distance(pos, tuple(s["pos"])) == 1 and s["unit"] not in ("archer", "lancer")
                   or distance(pos, tuple(s["pos"])) == 2 and s["unit"] in ("archer", "crossbowman")
                   for s in enemies)

    def score(action):
        if action.kind == "defend_supply":
            return 150
        if action.kind == "defend_unit":
            return -100
        if action.kind == "finish":
            return 0
        pos = action.source or next((p for p, s in board.items()
                                     if s["owner"] == who and s["unit"] == action.coin), None)
        actor = board.get(pos)
        effect = action.effect or action.kind
        if effect == "control":
            if own_points == 5:
                return 10000
            return 150 + (90 if controls.get(pos) == 1 - who else 0) + (200 if enemy_points == 5 else 0)
        if action.kind == "pass":
            return -60
        if action.kind == "initiative":
            return 5 + (12 if enemy_points >= 4 else 0)
        if action.kind == "recruit":
            unit = action.recruit
            owned = UNITS[unit].coins - me["supply"][unit] - me["removed"].count(unit)
            deployed = any(s["unit"] == unit for s in friendly)
            return 8 + max(0, 4 - owned) * 8 + (8 if deployed else 0)
        if action.kind == "deploy":
            return 62 - len(friendly) * 7 - objective_distance(action.target) * 3 - threat(action.target) * 5
        if action.kind == "bolster":
            return (20 + threat(pos) * 14 + (20 if any(s["unit"] == "knight" for s in enemies) else 0)
                    if actor["count"] == 1 else 3)
        end = action.path[-1] if action.path else pos
        value = 0
        if action.path:
            value += 12 + (objective_distance(pos) - objective_distance(end)) * 22
            if end in controls and controls[end] != who:
                value += 42
            value -= threat(end) * (8 if actor["count"] == 1 else 2)
            if end == pos:
                value -= 20
        if action.target is not None:
            target = board[action.target]
            guarded = target["unit"] == "royal_guard" and observation["players"][1-who]["supply"]["royal_guard"] > 0
            kill = target["count"] == 1 and not guarded
            value += 48 + (32 if kill else 0)
            if action.target in controls:
                value += 20
                if enemy_points == 5 and controls[action.target] != 1 - who:
                    value += 400 if kill else 60
            if target["unit"] == "pikeman" and distance(end, action.target) == 1:
                value -= 45 if actor["count"] == 1 else 8
            if actor["unit"] == "warrior_priest":
                value += 12
        if action.after is not None:
            value += (objective_distance(end) - objective_distance(action.after)) * 12
            if action.after in controls and controls[action.after] != who:
                value += 20
            value -= threat(action.after) * 5
        if observation.get("pending") and observation["pending"][0]["type"] == "berserk":
            value -= 10
        return value

    scored = [(score(a), a) for a in actions]
    best = max(s for s, _ in scored)
    return rng.choice([a for s, a in scored if s == best])


def choose_expanded_action(observation, actions, rng):
    """Expansion-aware heuristic; consumes only public/player-visible inputs."""
    from .board import distance
    if observation['current'] != observation['player'] or not actions:
        raise ValueError('AI needs its own turn and legal actions')
    who = observation['player']
    board = {tuple(s['pos']): s for s in observation['board']}
    controls = {tuple(c['pos']): c['owner'] for c in observation['controls']}
    goals = [p for p, owner in controls.items() if owner != who]
    count = sum(owner == who for owner in controls.values())
    def dist(pos):
        return min((distance(pos, p) for p in goals), default=0)
    def score(a):
        k, effect = a.kind, a.effect or a.kind
        direct = {'pass': -60, 'finish': -10, 'initiative': 5,
                  'defend_supply': 120, 'defend_decoy': 130, 'defend_wagon': 30,
                  'defend_unit': -40, 'cure': 55, 'return_decoy': 10,
                  'deceive': 25, 'cull': 30, 'build': 20, 'resolve': 0,
                  'reinforce': 20, 'spy': 15, 'spy_discard': 5,
                  'proclaim': 35, 'supply_bolster': 30, 'recruit_bolster': 35}
        if k in direct: return direct[k]
        if k == 'drum': return 25 if a.effect == str(who) else -20
        if k == 'recruit': return 15 + observation['players'][who]['supply'][a.recruit] * 3
        if k in ('deploy', 'redeploy'): return 60 - dist(a.target) * 5
        pos = a.source or next((p for p, s in board.items() if s['owner'] == who and s['unit'] == a.coin), None)
        if pos is None: return 0
        st = board[pos]
        # Repeated self-command is legal but makes no progress and can recurse
        # forever under a greedy policy; prefer an actual maneuver.
        if effect == 'command' and a.target == pos: return -50
        if k == 'bolster': return 28 if st['count'] == 1 else 2
        end = a.path[-1] if a.path else pos
        if effect in ('control', 'earl', 'move_control'):
            return 10000 if count == 5 else 180 + (60 if controls.get(end) == 1-who else 0)
        value = 0
        if a.path:
            value += 12 + (dist(pos)-dist(end))*22
            if end in goals: value += 40
        if a.target:
            target = board.get(a.target)
            if effect in ('poison', 'shock', 'charge_shock'): value += 65
            elif effect in ('command', 'supply_bolster', 'wagon_push'): value += 30
            elif target and target['owner'] != who:
                value += 55 + (25 if target['count'] == 1 else 0)
                if target['unit'] == 'pikeman' and distance(end, a.target) == 1 and st['count'] == 1: value -= 45
            elif not target and 'attack' in effect: value += 40
        return value
    values = [(score(a), a) for a in actions]
    best = max(v for v, _ in values)
    return rng.choice([a for v, a in values if v == best])
