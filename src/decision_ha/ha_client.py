"""Thin Home Assistant REST client: states, areas (via the template API) and service calls."""

import json


class HAAuthError(Exception):
    """HA rejected the token. The CLI exits with this message; the server returns 502."""


class HAClient:
    def __init__(self, session, base_url):
        self.session = session
        self.base_url = base_url

    def _check(self, resp):
        if resp.status_code == 401:
            raise HAAuthError("401 Unauthorized — check HA_TOKEN is valid and not expired.")
        resp.raise_for_status()
        return resp

    def get(self, path):
        return self._check(self.session.get(f"{self.base_url}{path}", timeout=15)).json()

    def post(self, path, payload):
        return self._check(
            self.session.post(f"{self.base_url}{path}", json=payload, timeout=15)
        )

    def states(self):
        return self.get("/api/states")

    def state(self, entity_id):
        return self.get(f"/api/states/{entity_id}")

    def areas_for(self, entity_ids):
        """Map entity_id → HA area name (or None). The REST API has no area endpoint,
        so one template render resolves them all."""
        template = (
            "{% set ns = namespace(d={}) %}"
            "{% for e in " + json.dumps(list(entity_ids)) + " %}"
            "{% set ns.d = dict(ns.d, **{e: area_name(e)}) %}"
            "{% endfor %}{{ ns.d | tojson }}"
        )
        return json.loads(self.post("/api/template", {"template": template}).text)

    def areas(self):
        """All HA area names, including ones with no entities yet."""
        resp = self.post("/api/template", {"template": "{{ areas() | map('area_name') | list | tojson }}"})
        return json.loads(resp.text)

    def call_service(self, domain, service, data):
        return self.post(f"/api/services/{domain}/{service}", data).json()
