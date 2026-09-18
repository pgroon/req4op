"""
Read-only OpenProject REST API v3 client for Req4Op v0.1.

This module ONLY reads. It never issues POST/PATCH/DELETE. Auth is HTTP Basic
with the literal username "apikey" and the API key as the password, as OpenProject
requires.

Dependency: `requests` (pip install requests). We parse the HAL+JSON responses by
hand rather than pulling in a HAL library — for a tool this size the manual
parsing is more transparent than another dependency.
"""

import requests


def _id_from_href(href):
    """
    Turn an OpenProject API href like "/api/v3/work_packages/42" into the int 42.
    Returns None if href is missing.
    """
    if not href:
        return None
    return int(href.rstrip("/").split("/")[-1])


class OpenProjectClient:
    def __init__(self, base_url, api_key):
        # e.g. base_url = "https://openproject.mypi.local"
        self.base_url = base_url.rstrip("/")
        self.auth = ("apikey", api_key)      # HTTP Basic: username is literally "apikey"

    def _get(self, path, params=None):
        """Single GET against /api/v3, returning parsed JSON. Raises on HTTP error."""
        url = f"{self.base_url}/api/v3{path}"
        response = requests.get(url, auth=self.auth, params=params, timeout=30)
        response.raise_for_status()          # turn 4xx/5xx into an exception
        return response.json()

    def _get_all_pages(self, path, params=None):
        """
        Follow OpenProject's offset/pageSize pagination and return every element
        across all pages as one flat list.

        OpenProject paginates with `offset` (1-based PAGE number, not a row index)
        and `pageSize`. Each response reports `total`; we loop until we've
        collected that many. A more sophisticated version could follow the
        `_links.nextByOffset` HAL link instead of computing offsets ourselves.
        """
        params = dict(params or {})
        params.setdefault("pageSize", 100)
        collected = []
        page_number = 1
        while True:
            params["offset"] = page_number
            payload = self._get(path, params)
            elements = payload.get("_embedded", {}).get("elements", [])
            collected.extend(elements)
            total = payload.get("total", len(collected))
            if len(collected) >= total or not elements:
                break
            page_number += 1
        return collected

    def fetch_work_packages(self, project_id):
        """
        Return the raw JSON element for every work package in the project.
        Parsing into WorkPackage objects happens in main.py, keeping this client
        purely about transport.
        """
        return self._get_all_pages(f"/projects/{project_id}/work_packages")

    def fetch_relations_for(self, work_package_id):
        """
        Return the raw JSON for every relation that involves this work package.

        NOTE on duplication: OpenProject exposes each relation from BOTH of its
        endpoints, so iterating over all work packages returns every edge twice
        (once per endpoint). The caller must de-duplicate by relation id.
        A performance-minded alternative is a single filtered GET /api/v3/relations
        query, but the filter syntax is fiddly and the per-work-package endpoint is
        clearer for a small demo project.
        """
        return self._get_all_pages(f"/work_packages/{work_package_id}/relations")
