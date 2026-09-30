from dataclasses import dataclass, field

RULES_VERSION = "base-2"
Coord = tuple[int, int]


@dataclass(frozen=True)
class Action:
    kind: str
    coin: str
    path: tuple[Coord, ...] = ()
    target: Coord | None = None
    recruit: str | None = None
    after: Coord | None = None
    source: Coord | None = None
    effect: str | None = None
    actor: str | None = None
    target_unit: str | None = None


@dataclass
class Stack:
    owner: int
    unit: str
    count: int = 1


@dataclass
class Player:
    supply: dict[str, int]
    bag: list[str] = field(default_factory=list)
    hand: list[str] = field(default_factory=list)
    discard: list[tuple[str, bool]] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Event:
    kind: str
    # Immutable key/value pairs: events can safely be shared between snapshots.
    data: tuple[tuple[str, object], ...] = ()
    visible_to: int | None = None


@dataclass
class State:
    seed: int
    players: list[Player]
    board: dict[Coord, Stack]
    controls: dict[Coord, int | None]
    rng_state: tuple
    round: int = 0
    current: int = 0
    initiative: int = 0
    initiative_claimed: bool = False
    winner: int | None = None
    history: tuple[Event, ...] = ()
    version: str = RULES_VERSION
    pending: list[dict] = field(default_factory=list)
    turn_owner: int | None = None
    extras: dict = field(default_factory=dict)
