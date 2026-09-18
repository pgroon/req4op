"""
Configuration for Req4Op v0.1.

This is the single place where the RE model is defined. Everything the classifier
does is driven by these three tables. Editing the tool's behaviour should mean
editing this file, not the logic in classify.py.
"""

from model import Tier


# --------------------------------------------------------------------------- #
# 1. Work-package TYPE NAME  ->  RE TIER
# --------------------------------------------------------------------------- #
# The keys must match your OpenProject work-package type names EXACTLY (they are
# compared as plain strings). Any type not listed here maps to no tier, so its
# work packages are ignored as RE nodes (an edge touching one is flagged, not
# silently dropped — see classify.py).
TYPE_TO_TIER = {
    "User Need": Tier.USER_NEED,
    "Requirement": Tier.REQUIREMENT,
    "Test Case": Tier.TEST_CASE,
    "Risk Control": Tier.RISK_CONTROL,
}


# --------------------------------------------------------------------------- #
# 2. CROSS-TIER SEMANTICS, keyed by the UNORDERED pair of tiers
# --------------------------------------------------------------------------- #
# A frozenset is used as the key precisely because the pair is unordered: the
# same entry matches an edge regardless of which endpoint the user started from.
#
# Each value is a triple (subject_tier, verb, object_tier), read as:
#     "the subject_tier node <verb> the object_tier node".
# Because we ignore the edge's own from/to, this triple is how we RECOVER reading
# direction: given a real edge, whichever endpoint has subject_tier is the subject.
#
# Only the two pairings specified in the project brief are defined here. The
# others (anything involving Risk Control, and User Need <-> Test Case) are NOT
# guessed: an edge of an undefined pair is flagged as UNDEFINED_TIER_PAIRING.
# Add them below once confirmed against the Conventions wiki page.
TIER_PAIR_SEMANTICS = {
    frozenset({Tier.REQUIREMENT, Tier.USER_NEED}):
        (Tier.REQUIREMENT, "satisfies", Tier.USER_NEED),
    frozenset({Tier.TEST_CASE, Tier.REQUIREMENT}):
        (Tier.TEST_CASE, "verifies", Tier.REQUIREMENT),

    # --- Likely additions — UNCONFIRMED, left commented on purpose ----------- #
    # frozenset({Tier.RISK_CONTROL, Tier.REQUIREMENT}):
    #     (Tier.RISK_CONTROL, "controls", Tier.REQUIREMENT),
    # frozenset({Tier.TEST_CASE, Tier.RISK_CONTROL}):
    #     (Tier.TEST_CASE, "verifies", Tier.RISK_CONTROL),
    # frozenset({Tier.TEST_CASE, Tier.USER_NEED}):
    #     (Tier.TEST_CASE, "validates", Tier.USER_NEED),
}


# --------------------------------------------------------------------------- #
# 3. SAME-TIER controlled-vocabulary MARKERS
# --------------------------------------------------------------------------- #
# Same-tier edges (e.g. Requirement <-> Requirement) get no direction from tiers,
# so their meaning comes from a marker written into the edge's description field,
# in the form "token: optional free-text comment".
#
# Key   = marker token, lower-case, no colon.
# Value = (verb, is_symmetric):
#           is_symmetric True  -> no direction needed (e.g. "conflicts").
#           is_symmetric False -> the verb is directional, BUT same-tier edges
#                                 currently carry no reliable direction, so the
#                                 subject/object is left undetermined and flagged.
#                                 (This is an open design question — see README /
#                                 the note in classify.py.)
SAME_TIER_MARKERS = {
    "refines": ("refines", False),
    "conflicts": ("conflicts", True),
}
