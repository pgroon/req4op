"""
Domain model for Req4Op v0.1.

Everything the tool works with is one of a few small, immutable-ish data
containers. We use @dataclass because it gives us __init__, __repr__ and
equality for free with almost no boilerplate, while staying far more readable
than a hand-written class or a bare dict.

Requires Python 3.10+ (for the `X | None` union type syntax).
"""

from dataclasses import dataclass
from enum import Enum


class Tier(Enum):
    """
    The four requirements-engineering tiers.

    The VALUE of each member is the human-readable label. We deliberately do NOT
    give tiers a numeric rank here: the relationship between tiers is not a single
    linear scale. User Need sits above Requirement (a genuine vertical axis), but
    Test Case and Risk Control are "cross-cutting" — they attach to several tiers.
    So semantics come from a lookup keyed by the *pair* of tiers (see config.py),
    not from arithmetic on a rank number.
    """
    USER_NEED = "User Need"
    REQUIREMENT = "Requirement"
    TEST_CASE = "Test Case"
    RISK_CONTROL = "Risk Control"


@dataclass
class WorkPackage:
    """One OpenProject work package, reduced to the fields this tool needs."""
    id: int
    type_name: str          # raw type string exactly as it comes from the API
    tier: Tier | None       # None means this type maps to no RE tier (see config)
    subject: str
    status: str | None = None
    description: str | None = None


@dataclass
class Relation:
    """
    One 'relates' edge between two work packages.

    endpoint_a_id / endpoint_b_id are just the two work packages the edge joins.
    Their ORDER carries no meaning: 'relates' is symmetric and OpenProject's
    from/to orientation is an accidental side effect of the GUI, so we treat the
    pair as unordered everywhere and never rely on which is 'a' and which is 'b'.

    marker_raw is the raw text of the relation's own `description` field. For a
    same-tier edge this is where the controlled-vocabulary marker (e.g. "refines:")
    lives. It is always optional.
    """
    id: int
    endpoint_a_id: int
    endpoint_b_id: int
    relation_type: str          # expected to always be "relates"
    marker_raw: str | None      # raw edge description text, may be None


class Severity(Enum):
    """How serious a finding is. Lets the renderer sort/colour/filter later."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class Finding:
    """
    A single thing the tool noticed and wants to report.

    The classifier and the coverage analysis both emit these into one shared
    stream, so the renderer has exactly one kind of object to display. The core
    principle: nothing that can't be cleanly resolved is silently dropped — it
    becomes a Finding instead.
    """
    code: str           # short machine-ish code, e.g. "UNKNOWN_MARKER"
    severity: Severity
    message: str        # human-readable explanation
    ref: str            # what it refers to, e.g. "relation 12 (#3<->#7)"


@dataclass
class ClassifiedRelation:
    """
    The result of interpreting one Relation.

    We keep the original Relation untouched and produce this alongside it, rather
    than mutating the input. subject_id/object_id express reading direction where
    we could recover it ("subject_id <verb> object_id"); any of the three may be
    None when the edge could not be fully classified.

    basis records HOW it was classified — useful for the report and for debugging:
      "tier"   -> direction/verb came from the endpoint tiers (cross-tier edge)
      "marker" -> came from a same-tier controlled-vocabulary marker
      None     -> not classified
    """
    relation: Relation
    subject_id: int | None
    object_id: int | None
    verb: str | None
    basis: str | None
