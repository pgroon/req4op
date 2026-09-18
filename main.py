"""
Req4Op v0.1 — command-line entry point.

Runs the whole read-only pipeline and prints a plain-text report:

    fetch work packages + relations  (client.py)
        -> build the node store, assign tiers
        -> classify every relation     (classify.py)
        -> analyse coverage            (analyse.py)
        -> render a text report to stdout

Rendering the traceability MATRIX and the specification/review PDF is intentionally
NOT part of v0.1 — this console report is the readable stand-in that proves the
model and judgment layer work end to end.

Configuration comes from a .env file in the working directory (loaded via
python-dotenv), with these keys:

    OP_URL=https://openproject.example.org
    OP_PROJECT=my-project-id
    OP_API_KEY=your_key_here

--url and --project may be given on the command line to OVERRIDE the .env values.
The API key is deliberately env-only (never a CLI flag) so it can't land in shell
history or a process listing, and it is never printed.

Usage:
    python main.py                       # all three read from .env
    python main.py --project other-id    # override just the project
"""

import argparse
import os
import sys

# python-dotenv reads a .env file and injects its keys into os.environ.
# It does NOT overwrite variables already set in the real environment, so an
# explicit `export OP_URL=...` still wins over the file — handy for one-off runs.
from dotenv import load_dotenv

from model import WorkPackage, Relation, Severity
from config import TYPE_TO_TIER
from client import OpenProjectClient, _id_from_href
from classify import classify_all
from analyse import analyse_coverage


# --------------------------------------------------------------------------- #
# Parsing raw API JSON into our model objects.
# Kept here (not in client.py) so the client stays purely about transport.
# --------------------------------------------------------------------------- #

def _dig(mapping, *keys):
    """Safely walk nested dicts: _dig(d, '_links', 'type', 'title'). None if any step missing."""
    current = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def parse_work_package(element):
    """Turn one raw work-package JSON element into a WorkPackage."""
    type_name = _dig(element, "_links", "type", "title") or ""
    return WorkPackage(
        id=element["id"],
        type_name=type_name,
        tier=TYPE_TO_TIER.get(type_name),           # None if the type is unmapped
        subject=element.get("subject", ""),
        status=_dig(element, "_links", "status", "title"),
        # `description` is a formattable object: {format, raw, html}. We keep raw.
        description=_dig(element, "description", "raw"),
    )


def parse_relation(element):
    """
    Turn one raw relation JSON element into a Relation.

    NOTE: the `description` field on a relation is what the project treats as the
    same-tier marker. If your OpenProject instance exposes this under a different
    key, adjust it here — this is the one spot the field name is assumed.
    """
    from_id = _id_from_href(_dig(element, "_links", "from", "href"))
    to_id = _id_from_href(_dig(element, "_links", "to", "href"))
    return Relation(
        id=element["id"],
        endpoint_a_id=from_id,
        endpoint_b_id=to_id,
        relation_type=element.get("type", ""),
        marker_raw=element.get("description") or None,
    )


# --------------------------------------------------------------------------- #
# Fetching + assembling the graph.
# --------------------------------------------------------------------------- #

def load_graph(client, project_id):
    """Fetch everything and return (nodes_dict, relations_list)."""
    # Nodes: dict keyed by id so relations can look endpoints up in O(1).
    nodes = {}
    for element in client.fetch_work_packages(project_id):
        work_package = parse_work_package(element)
        nodes[work_package.id] = work_package

    # Relations: fetched per work package, so each edge appears twice. De-duplicate
    # by relation id using a dict, then keep the values.
    relations_by_id = {}
    for work_package_id in nodes:
        for element in client.fetch_relations_for(work_package_id):
            relation = parse_relation(element)
            relations_by_id[relation.id] = relation
    relations = list(relations_by_id.values())

    return nodes, relations


# --------------------------------------------------------------------------- #
# Text rendering.
# --------------------------------------------------------------------------- #

def render_report(nodes, relations, classified_relations, findings):
    """Print a plain-text report to stdout."""
    print("=" * 70)
    print("Req4Op v0.1 — traceability report")
    print("=" * 70)

    # --- headline counts ---
    tier_counts = {}
    for node in nodes.values():
        key = node.tier.value if node.tier else "(unmapped)"
        tier_counts[key] = tier_counts.get(key, 0) + 1
    print(f"\nWork packages: {len(nodes)}   Relations: {len(relations)}")
    for tier_label, count in sorted(tier_counts.items()):
        print(f"    {tier_label:<14} {count}")

    # --- classified trace links ---
    print("\n--- Trace links ---")
    for classified in classified_relations:
        relation = classified.relation
        if classified.verb and classified.subject_id and classified.object_id:
            subject = nodes[classified.subject_id]
            obj = nodes[classified.object_id]
            print(f"  #{subject.id} {classified.verb} #{obj.id}   "
                  f"[{classified.basis}]")
        elif classified.verb:                       # verb known, direction not
            print(f"  #{relation.endpoint_a_id} <{classified.verb}> "
                  f"#{relation.endpoint_b_id}   [{classified.basis}, undirected]")
        else:                                       # not classified
            print(f"  #{relation.endpoint_a_id} -- #{relation.endpoint_b_id}   "
                  f"[unclassified]")

    # --- findings, grouped by severity (most serious first) ---
    print("\n--- Findings ---")
    order = [Severity.ERROR, Severity.WARNING, Severity.INFO]
    if not findings:
        print("  none")
    for severity in order:
        for finding in findings:
            if finding.severity is severity:
                print(f"  [{severity.value.upper():<7}] {finding.code}: "
                      f"{finding.message}  ({finding.ref})")


# --------------------------------------------------------------------------- #
# CLI wiring.
# --------------------------------------------------------------------------- #

def main():
    # Load .env into os.environ before we read any settings.
    load_dotenv()

    # CLI flags are now OPTIONAL overrides (default=None), not required. When a
    # flag is omitted we fall back to the matching .env / environment value.
    parser = argparse.ArgumentParser(description="Req4Op v0.1 — read-only OpenProject RE report")
    parser.add_argument("--url", default=None, help="OpenProject base URL (overrides OP_URL)")
    parser.add_argument("--project", default=None, help="Project identifier or id (overrides OP_PROJECT)")
    args = parser.parse_args()

    # Resolve each setting: command-line flag first, then environment/.env.
    url = args.url or os.environ.get("OP_URL")
    project = args.project or os.environ.get("OP_PROJECT")
    api_key = os.environ.get("OP_API_KEY")          # env-only, never a flag

    # Fail early and name exactly what's missing, rather than crashing later.
    missing = []
    if not url:
        missing.append("OP_URL (or --url)")
    if not project:
        missing.append("OP_PROJECT (or --project)")
    if not api_key:
        missing.append("OP_API_KEY")
    if missing:
        sys.exit("Error: missing configuration: " + ", ".join(missing)
                 + "\nSet them in a .env file in this directory.")

    client = OpenProjectClient(url, api_key)
    nodes, relations = load_graph(client, project)

    classified_relations, edge_findings = classify_all(relations, nodes)
    _coverage_stats, coverage_findings = analyse_coverage(relations, nodes)

    all_findings = edge_findings + coverage_findings
    render_report(nodes, relations, classified_relations, all_findings)


if __name__ == "__main__":
    main()
