from collections import Counter

import pytest

from warchest import new_game, validate_state
from warchest.model import Stack
from warchest.units import ARMIES, ROYAL, UNITS


@pytest.fixture
def position():
    """Build coin-conserving test positions without relying on the action engine."""
    def build(board=(), hands=((ROYAL,), (ROYAL,)), current=0, controls=None):
        state = new_game(42)
        state.history = ()
        state.current = current
        state.board = {pos: Stack(owner, unit, count) for pos, owner, unit, count in board}
        if controls:
            state.controls.update(controls)
        for who, player in enumerate(state.players):
            player.hand = list(hands[who])
            player.bag = []
            player.discard = []
            player.removed = []
            used = Counter(player.hand)
            for stack in state.board.values():
                if stack.owner == who:
                    used[stack.unit] += stack.count
            player.supply = {u: UNITS[u].coins - used[u] for u in ARMIES[who]}
            if ROYAL not in player.hand:
                player.bag.append(ROYAL)
        validate_state(state)
        return state
    return build
