"""Unit-specific legal actions. No hidden opponent data is consulted."""
from dataclasses import replace

from .board import DIRECTIONS, HEXES, add, distance, neighbors
from .model import Action


def tactic_actions(state, unit, pos):
    board = state.board
    enemy = lambda p: p in board and board[p].owner != state.current
    if unit == "archer":
        for target in sorted(board):
            if enemy(target) and distance(pos, target) == 2:
                yield Action("tactic", unit, target=target)
    elif unit == "crossbowman":
        for d in DIRECTIONS:
            mid = add(pos, d)
            target = add(mid, d)
            if mid in HEXES and mid not in board and enemy(target):
                yield Action("tactic", unit, target=target)
    elif unit == "light_cavalry":
        for mid in neighbors(pos):
            if mid not in board:
                for end in neighbors(mid):
                    # Returning to the origin is a valid two-step move.
                    if end not in board or end == pos:
                        yield Action("tactic", unit, path=(mid, end))
    elif unit == "cavalry":
        for end in neighbors(pos):
            if end not in board:
                for target in neighbors(end):
                    if enemy(target):
                        yield Action("tactic", unit, path=(end,), target=target)
    elif unit == "lancer":
        for d in DIRECTIONS:
            path = []
            end = pos
            for _ in range(2):
                end = add(end, d)
                if end not in HEXES or end in board:
                    break
                path.append(end)
                target = add(end, d)
                if enemy(target):
                    yield Action("tactic", unit, path=tuple(path), target=target)


def swordsman_choices(state, pos, attack):
    yield attack
    target = state.board[attack.target]
    if target.unit == "pikeman" and state.board[pos].count == 1:
        return
    for end in neighbors(pos):
        if end not in state.board or (end == attack.target and target.count == 1):
            yield replace(attack, after=end)
