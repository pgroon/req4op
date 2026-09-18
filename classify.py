"""
Classification for Req4Op v0.1 — the judgment layer.

This is where directionality and semantics are actually decided, kept deliberately
separate from fetching (client.py) and rendering (main.py). It takes the node
store and the raw relations and produces, for each relation, a ClassifiedRelation
plus zero or more Findings.

Guiding principle: never silently drop or ignore information. Every combination of
(endpoint tiers x marker presence) has a defined outcome — either a clean
classification or a Finding. This mirrors the matrix agreed during design:

    endpoints    marker            outcome
    ---------    ------            -------
    cross-tier   none              classify by tier pair                (normal)
    cross-tier   present           classify by tier pair + flag         (redundant/conflict)
    same-tier    in vocabulary     classify by marker                   (normal)
    same-tier    unknown token     flag                                 (unknown marker)
    same-tier    none              flag                                 (unclassifiable)

Plus structural cases: an endpoint outside the fetched node set (dangling edge),
an endpoint whose type maps to no tier, and a relation type other than 'relates'.
"""

from model import ClassifiedRelation, Finding, Severity
from config import TIER_PAIR_SEMANTICS, SAME_TIER_MARKERS


def parse_marker_token(marker_raw):
    """
    Extract the controlled-vocabulary token from an edge description.

    Convention: "token: optional free-text comment". We return the lower-cased
    token only if there is a colon delimiter and a non-empty token before it;
    otherwise None (there is no structured marker). The caller still sees the raw
    text via relation.marker_raw and decides whether stray text deserves a flag.
    """
    if not marker_raw:
        return None
    stripped = marker_raw.strip()
    if ":" not in stripped:
        return None
    token = stripped.split(":", 1)[0].strip().lower()
    return token or None


def _unclassified(relation):
    """Helper: a ClassifiedRelation carrying no verb/direction."""
    return ClassifiedRelation(relation, None, None, None, None)


def classify_relation(relation, nodes):
    """
    Classify a single relation. Returns (ClassifiedRelation, list_of_findings).
    `nodes` is the dict {work_package_id: WorkPackage}.
    """
    findings = []
    ref = f"relation {relation.id} (#{relation.endpoint_a_id}<->#{relation.endpoint_b_id})"

    # --- structural: both endpoints must resolve to known nodes -------------- #
    node_a = nodes.get(relation.endpoint_a_id)
    node_b = nodes.get(relation.endpoint_b_id)
    if node_a is None or node_b is None:
        findings.append(Finding(
            "DANGLING_EDGE", Severity.ERROR,
            "Relation references a work package outside the fetched set.", ref))
        return _unclassified(relation), findings

    # --- sanity: we only model the 'relates' type ---------------------------- #
    if relation.relation_type != "relates":
        findings.append(Finding(
            "UNEXPECTED_RELATION_TYPE", Severity.WARNING,
            f"Relation type is '{relation.relation_type}', expected 'relates'. "
            "Directional types carry scheduling side effects and are not modelled.",
            ref))
        # We continue and still try to classify by tier, but the flag stands.

    # --- both endpoints must map to a tier to mean anything in the RE graph -- #
    tier_a = node_a.tier
    tier_b = node_b.tier
    if tier_a is None or tier_b is None:
        # Not necessarily wrong (a Requirement may legitimately link to a
        # non-RE Task), so INFO rather than WARNING — but still surfaced.
        findings.append(Finding(
            "UNMAPPABLE_ENDPOINT", Severity.INFO,
            "One endpoint has a type that maps to no RE tier; edge not part of "
            "the RE trace graph.", ref))
        return _unclassified(relation), findings

    marker_token = parse_marker_token(relation.marker_raw)

    # ======================= CROSS-TIER ===================================== #
    if tier_a != tier_b:
        semantics = TIER_PAIR_SEMANTICS.get(frozenset({tier_a, tier_b}))

        if semantics is None:
            findings.append(Finding(
                "UNDEFINED_TIER_PAIRING", Severity.WARNING,
                f"No semantic defined for tier pair "
                f"{tier_a.value} / {tier_b.value}.", ref))
            classified = _unclassified(relation)
        else:
            subject_tier, verb, _object_tier = semantics
            # Recover direction from tiers: whichever endpoint has subject_tier
            # is the subject. (from/to on the edge is ignored by design.)
            if node_a.tier == subject_tier:
                subject_id, object_id = node_a.id, node_b.id
            else:
                subject_id, object_id = node_b.id, node_a.id
            classified = ClassifiedRelation(relation, subject_id, object_id, verb, "tier")

        # Phil's rule: a marker on a cross-tier edge is redundant — the tiers
        # already fix the meaning — and possibly contradicts it. Flag it.
        if relation.marker_raw:
            findings.append(Finding(
                "REDUNDANT_MARKER", Severity.WARNING,
                "Cross-tier edge also carries a marker; tier pair already "
                f"determines semantics. Marker text: {relation.marker_raw!r}. "
                "Potential conflict — check the marker does not contradict the "
                "tier-inferred verb.", ref))
        return classified, findings

    # ======================= SAME-TIER ====================================== #
    # tier_a == tier_b: no direction from tiers, so we need a marker.
    if marker_token is None:
        if relation.marker_raw:                     # text present but not a valid marker
            findings.append(Finding(
                "MALFORMED_MARKER", Severity.WARNING,
                "Same-tier edge description has text but no valid 'token:' marker: "
                f"{relation.marker_raw!r}.", ref))
        else:                                       # nothing at all -> unclassifiable
            findings.append(Finding(
                "UNMARKED_SAME_TIER", Severity.WARNING,
                "Same-tier edge has no marker; semantics undetermined.", ref))
        return _unclassified(relation), findings

    marker_def = SAME_TIER_MARKERS.get(marker_token)
    if marker_def is None:
        findings.append(Finding(
            "UNKNOWN_MARKER", Severity.WARNING,
            f"Same-tier marker '{marker_token}' is not in the controlled "
            "vocabulary.", ref))
        return _unclassified(relation), findings

    verb, is_symmetric = marker_def
    if is_symmetric:
        # Symmetric marker (e.g. conflicts): direction is meaningless, so we just
        # record both endpoints without a preferred subject/object order.
        classified = ClassifiedRelation(relation, node_a.id, node_b.id, verb, "marker")
    else:
        # OPEN QUESTION: the marker is directional (e.g. refines) but a same-tier
        # edge carries no reliable direction. For v0.1 we record the verb but
        # leave subject/object undetermined and flag it. A convention that encodes
        # the target in the marker (e.g. "refines: #123") would resolve this.
        findings.append(Finding(
            "UNDETERMINED_DIRECTION", Severity.INFO,
            f"Marker '{marker_token}' is directional but same-tier edges carry no "
            "reliable direction; subject/object left undetermined.", ref))
        classified = ClassifiedRelation(relation, None, None, verb, "marker")
    return classified, findings


def classify_all(relations, nodes):
    """
    Classify every relation. Returns (list_of_ClassifiedRelation, list_of_Finding).
    A more functional style could use itertools/comprehensions, but the explicit
    loop keeps the two accumulating outputs obvious.
    """
    classified_relations = []
    all_findings = []
    for relation in relations:
        classified, findings = classify_relation(relation, nodes)
        classified_relations.append(classified)
        all_findings.extend(findings)
    return classified_relations, all_findings
