"""
Coverage analysis for Req4Op v0.1.

Where classify.py interprets individual edges, this module looks at the graph as a
whole and reports coverage gaps — the classic RE traceability checks:

  * Requirements not traced up to any User Need   (requirement without rationale)
  * Requirements not traced down to any Test Case (unverified requirement)
  * User Needs with no Requirement                (need not addressed)
  * Test Cases not linked to any Requirement       (orphan test)

These are emitted as Findings so they join the same display stream as the edge
findings. We also return a small stats dict for a headline summary.
"""

from model import Tier, Finding, Severity


def build_tier_adjacency(relations, nodes):
    """
    For each node, which TIERS is it linked to via any 'relates' edge?

    Returns {node_id: set_of_tiers}. We only count edges whose BOTH endpoints are
    known and mapped to a tier — an edge to a non-RE node doesn't contribute to
    RE coverage. Direction is irrelevant here (coverage is about connectivity),
    so we add the link in both directions.

    A heavier alternative would be a real graph library (networkx) with proper
    adjacency structures; for these simple "is it connected to tier X?" questions
    a dict of sets is enough and far more legible.
    """
    adjacency = {node_id: set() for node_id in nodes}
    for relation in relations:
        node_a = nodes.get(relation.endpoint_a_id)
        node_b = nodes.get(relation.endpoint_b_id)
        if node_a is None or node_b is None:
            continue
        if node_a.tier is None or node_b.tier is None:
            continue
        adjacency[node_a.id].add(node_b.tier)
        adjacency[node_b.id].add(node_a.tier)
    return adjacency


def analyse_coverage(relations, nodes):
    """
    Run the coverage checks. Returns (stats_dict, list_of_findings).
    """
    adjacency = build_tier_adjacency(relations, nodes)
    findings = []

    # Each check is (source tier, required linked tier, code, severity, message).
    # Adding a new coverage rule = adding a row here.
    checks = [
        (Tier.REQUIREMENT, Tier.USER_NEED,
         "REQ_WITHOUT_NEED", Severity.WARNING,
         "Requirement is not traced up to any User Need."),
        (Tier.REQUIREMENT, Tier.TEST_CASE,
         "REQ_WITHOUT_TEST", Severity.WARNING,
         "Requirement is not verified by any Test Case."),
        (Tier.USER_NEED, Tier.REQUIREMENT,
         "NEED_WITHOUT_REQ", Severity.WARNING,
         "User Need is not addressed by any Requirement."),
        (Tier.TEST_CASE, Tier.REQUIREMENT,
         "TEST_WITHOUT_REQ", Severity.WARNING,
         "Test Case is not linked to any Requirement (orphan test)."),
    ]

    stats = {}
    for source_tier, required_tier, code, severity, message in checks:
        missing_ids = []
        for node in nodes.values():
            if node.tier is not source_tier:
                continue
            if required_tier not in adjacency[node.id]:
                missing_ids.append(node.id)
                findings.append(Finding(
                    code, severity, message, f"#{node.id} {node.subject!r}"))
        stats[code] = missing_ids

    return stats, findings
