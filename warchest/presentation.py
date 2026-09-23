"""Public, non-rule-changing visual cues derived from confirmed transitions."""


def combat_effects(before, action, events):
    effects = []
    if before.extras:
        for event in events:
            data = dict(event.data)
            if event.kind == 'attack':
                effects.append(dict(kind='attack', unit=data['unit'], owner=data['player'],
                                    source=data['source'], origin=action.source or data['source'],
                                    path=action.path, target=data['target']))
            elif event.kind == 'damage':
                effects.append(dict(kind='hit', unit=data['unit'], owner=data['player'], pos=data['pos'], remaining=data['remaining']))
            elif event.kind == 'shock':
                effects.append(dict(kind='hit', unit=data['unit'], owner=data['player'], pos=data['pos'], remaining=0, label='震慑'))
            elif event.kind == 'supply_damage' and action.kind == 'defend_supply':
                effects.append(dict(kind='shield', unit=data['unit'], owner=data['player'], pos=action.source))
        return effects
    if action.kind in ("attack", "tactic") and action.target is not None:
        source = action.source or next((p for p, s in before.board.items()
                    if s.owner == before.current and s.unit == action.coin), None)
        if source is not None:
            actor = before.board[source]
            attack_from = action.path[-1] if action.path else source
            effects.append({"kind": "attack", "unit": actor.unit, "owner": actor.owner,
                            "source": attack_from, "origin": source,
                            "path": action.path, "target": action.target})
    for event in events:
        data = dict(event.data)
        if event.kind == "damage":
            effects.append({"kind": "hit", "unit": data["unit"], "owner": data["player"],
                            "pos": data["pos"], "remaining": data["remaining"]})
        elif event.kind == "supply_damage":
            effects.append({"kind": "shield", "unit": "royal_guard", "owner": data["player"],
                            "pos": action.source})
    return effects
