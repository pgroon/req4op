#!/usr/bin/env python3
"""Seed the OpenProject RE demo project from incubation_seed.csv via REST API v3.

WRITE-side environment setup for the demo dataset. This is not the analysis tool.
It creates the work packages, sets parent (hierarchy) links, and creates the
relation links that native CSV/Excel import can't reliably set.

Idempotent: existing work packages (matched by subject) and existing relations
are detected and skipped, so re-running does not create duplicates.

Prereqs (in the OpenProject UI):
  1. Project 'req4op-demo' exists.
  2. Four types created AND enabled for THIS project (Project settings ->
     Work package types), names matching the CSV 'type' column:
     User Need, Requirement, Test Case, Risk Control.
  3. A status matching the CSV 'status' column ('New') exists.

Config comes from a .env (found by walking up from this script):
    OP_API_KEY=your-openproject-api-token
    OP_URL=http://naspi.local:8089
    OP_PROJECT=req4op-demo

Run:
  pip install requests python-dotenv
  python seed_openproject.py incubation_seed.csv
"""

import csv
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv, find_dotenv

# --- Config -----------------------------------------------------------------
load_dotenv(find_dotenv())
# Explicit alternative for a fixed layout:
# load_dotenv(Path(__file__).resolve().parent.parent / ".env")

OP_API_KEY = os.environ.get("OP_API_KEY") or os.environ.get("API_KEY")
OP_URL = os.environ.get("OP_URL", "http://naspi.local:8089")
OP_PROJECT = os.environ.get("OP_PROJECT", "req4op-demo")


def build_auth():
    if not OP_API_KEY:
        sys.exit("No API key found. Add OP_API_KEY=<token> to your .env file.")
    # OpenProject basic auth: username is the literal string 'apikey',
    # password is your token. (The 'apikey' below is NOT your key.)
    return ("apikey", OP_API_KEY)


def error_detail(r):
    """Pull the human-readable validation message out of an OpenProject error."""
    try:
        j = r.json()
        parts = [j.get("message", "")]
        for e in (j.get("_embedded") or {}).get("errors", []) or []:
            parts.append(e.get("message", ""))
        return " | ".join(p for p in parts if p) or r.text[:300]
    except Exception:
        return r.text[:300]


def wp_id_from_href(href):
    return int(href.rstrip("/").split("/")[-1])


def name_to_href(base, auth, endpoint):
    """Return {name: self-href} for a global collection (types, statuses)."""
    r = requests.get(f"{base}/api/v3/{endpoint}?pageSize=200", auth=auth)
    r.raise_for_status()
    return {e["name"]: e["_links"]["self"]["href"]
            for e in r.json()["_embedded"]["elements"]}


def existing_subjects(base, auth):
    """Return {subject: id} for work packages already in the project."""
    r = requests.get(
        f"{base}/api/v3/projects/{OP_PROJECT}/work_packages?pageSize=200",
        auth=auth)
    r.raise_for_status()
    return {e["subject"]: e["id"] for e in r.json()["_embedded"]["elements"]}


def related_ids(base, auth, wp_id):
    """Return the set of work package ids already related to wp_id (either end)."""
    r = requests.get(
        f"{base}/api/v3/work_packages/{wp_id}/relations?pageSize=200", auth=auth)
    r.raise_for_status()
    ids = set()
    for rel in r.json()["_embedded"]["elements"]:
        for side in ("from", "to"):
            other = wp_id_from_href(rel["_links"][side]["href"])
            if other != wp_id:
                ids.add(other)
    return ids


def build_description(row):
    desc = row["description"]
    extra = []
    if row.get("category"):
        extra.append(f"Category: {row['category']}")
    if row.get("verification_method"):
        extra.append(f"Verification method: {row['verification_method']}")
    return desc + ("\n\n" + "\n".join(extra) if extra else "")


def main(csv_path):
    auth = build_auth()
    base = OP_URL.rstrip("/")
    headers = {"Content-Type": "application/json"}

    types = name_to_href(base, auth, "types")
    statuses = name_to_href(base, auth, "statuses")
    seen = existing_subjects(base, auth)

    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for missing in {r["type"] for r in rows} - types.keys():
        sys.exit(f"Type '{missing}' not found in this instance. Create it first.")
    for missing in {r["status"] for r in rows} - statuses.keys():
        sys.exit(f"Status '{missing}' not found. Options: {sorted(statuses)}")

    id_map = {}  # temp_id -> real work package id

    # Pass 1: create work packages, or reuse ones that already exist (by subject).
    for row in rows:
        if row["subject"] in seen:
            id_map[row["temp_id"]] = seen[row["subject"]]
            print(f"exists  {row['temp_id']:>6} -> #{seen[row['subject']]}")
            continue

        links = {
            "type": {"href": types[row["type"]]},
            "status": {"href": statuses[row["status"]]},
        }
        parent = row.get("parent", "").strip()
        if parent:
            links["parent"] = {"href": f"/api/v3/work_packages/{id_map[parent]}"}

        body = {
            "subject": row["subject"],
            "description": {"format": "markdown", "raw": build_description(row)},
            "_links": links,
        }
        r = requests.post(f"{base}/api/v3/projects/{OP_PROJECT}/work_packages",
                          json=body, auth=auth, headers=headers)
        if r.status_code >= 300:
            sys.exit(
                f"\nHTTP {r.status_code} creating {row['temp_id']} "
                f"(type '{row['type']}').\nReason: {error_detail(r)}\n\n"
                f"Payload sent:\n{json.dumps(body, indent=2)}\n")
        wp_id = r.json()["id"]
        id_map[row["temp_id"]] = wp_id
        print(f"created {row['temp_id']:>6} -> #{wp_id}  {row['subject'][:48]}")

    # Pass 2: create relations. OpenProject requires BOTH 'from' and 'to' in the
    # body even though the endpoint is nested under the source work package.
    # All trace links use the generic 'relates' type; the RE meaning lives in
    # the RE Conventions wiki page.
    for row in rows:
        rel = row.get("relates_to", "").strip()
        if not rel:
            continue
        src = id_map[row["temp_id"]]
        already = related_ids(base, auth, src)
        for target in (t.strip() for t in rel.split(";") if t.strip()):
            dst = id_map[target]
            if dst in already:
                print(f"  linked {row['temp_id']} relates {target} (already)")
                continue
            body = {
                "type": "relates",
                "_links": {
                    "from": {"href": f"/api/v3/work_packages/{src}"},
                    "to": {"href": f"/api/v3/work_packages/{dst}"},
                },
            }
            r = requests.post(f"{base}/api/v3/work_packages/{src}/relations",
                              json=body, auth=auth, headers=headers)
            if r.status_code >= 300:
                print(f"  ! relation {row['temp_id']}->{target} failed: "
                      f"{r.status_code} {error_detail(r)}")
            else:
                print(f"  linked {row['temp_id']} relates {target}")

    print(f"\nDone. {len(id_map)} work packages in '{OP_PROJECT}'.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "incubation_seed.csv")
