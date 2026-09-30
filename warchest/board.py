"""Official two-player board, rotated so A starts above B.

Axial coordinates: display x = q, y = 2*r + q. Radius 3: 37 hexes.
"""

DIRECTIONS = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))
HEXES = frozenset(
    (q, r) for q in range(-3, 4) for r in range(-3, 4)
    if -3 <= q + r <= 3
)
SEA_HEXES = frozenset((q, r) for q in range(-3, 4) for r in range(-3, 4)) - HEXES
FULL_HEXES = HEXES | SEA_HEXES

STARTS = {0: ((-1, -2), (2, -3)), 1: ((-2, 3), (1, 2))}
LOCATIONS = frozenset((
    (-1, -2), (2, -3), (-2, 3), (1, 2),
    (-2, 0), (1, -1), (3, -2), (-3, 2), (-1, 1), (2, 0),
))


def add(a, b):
    return a[0] + b[0], a[1] + b[1]


def neighbors(pos):
    return tuple(p for d in DIRECTIONS if (p := add(pos, d)) in HEXES)


def distance(a, b):
    q, r = a[0] - b[0], a[1] - b[1]
    return max(abs(q), abs(r), abs(q + r))


def all_neighbors(pos):
    return tuple(p for d in DIRECTIONS if (p := add(pos, d)) in FULL_HEXES)
