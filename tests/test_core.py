import json
from types import SimpleNamespace

import pytest
import yaml

from decision_ha.actions import ALLOWED, ParamError, build_service_call
from decision_ha.catalog import (MP_NEXT_TRACK, MP_PAUSE, MP_TURN_OFF, MP_VOLUME_SET, Entity,
                                 aliases_skeleton, build_catalog, derive_intents)
from decision_ha.config import Settings
from decision_ha.decide import NONE, apply_gate, build_questions, decide
from decision_ha.execute import describe_state
from decision_ha.index import Candidate, group_hits
from decision_ha.params import extract_color, extract_numbers, extract_options
from decision_ha.templates import action_documents, candidate_description

ALIASES = {
    "areas": {"Bedroom": {"name": "sypialnia", "where": "w sypialni"}},
    "exclude": ["media_player.undefined_*"],
    "entities": {
        "switch.relay": {"aliases": ["światło w sypialni"], "description": "główne światło"},
        "switch.hidden": {"exclude": True},
    },
}

STATES = [
    {"entity_id": "switch.relay", "state": "off", "attributes": {"friendly_name": "Sypialnia światło"}},
    {"entity_id": "switch.hidden", "state": "off", "attributes": {}},
    {"entity_id": "sensor.temp", "state": "21", "attributes": {}},
    {"entity_id": "media_player.undefined_undefined_x", "state": "off", "attributes": {}},
    {"entity_id": "light.lamp", "state": "on",
     "attributes": {"friendly_name": "Lampa", "supported_color_modes": ["hs"]}},
]


def light(**kw):
    return Entity("light.lamp", "light", "Lampa", intents=["turn_on", "set_brightness", "set_color"], **kw)


# --- catalog

def test_build_catalog_filters_and_merges_aliases():
    catalog = {e.entity_id: e for e in build_catalog(STATES, {"switch.relay": "Bedroom"}, ALIASES)}
    assert set(catalog) == {"switch.relay", "light.lamp"}
    relay = catalog["switch.relay"]
    assert relay.area == "sypialnia" and relay.where == "w sypialni"
    assert relay.aliases == ["światło w sypialni"]
    assert relay.intents == ["turn_on", "turn_off", "toggle", "query_state"]


def test_aliases_skeleton_is_valid_yaml_listing_areas_and_entities():
    text = aliases_skeleton(STATES, ["Bedroom", "Garage"], {"switch.relay": "Bedroom"})
    parsed = yaml.safe_load(text)
    assert parsed["areas"] == {"Bedroom": {"name": "Bedroom", "where": None},
                               "Garage": {"name": "Garage", "where": None}}
    assert parsed["entities"] is None
    assert "#  switch.relay:  # Sypialnia światło (Bedroom)" in text
    assert "sensor.temp" not in text
    # the generated file is accepted as-is by build_catalog
    assert {e.entity_id for e in build_catalog(STATES, {}, parsed)} >= {"switch.relay", "light.lamp"}


def test_derive_intents_light_and_media_player():
    assert "set_color" in derive_intents("light", {"supported_color_modes": ["hs"]})
    assert "set_brightness" not in derive_intents("light", {"supported_color_modes": ["onoff"]})
    features = MP_PAUSE | MP_VOLUME_SET | MP_NEXT_TRACK | MP_TURN_OFF
    assert derive_intents("media_player", {"supported_features": features}) == [
        "turn_off", "media_pause", "media_next", "set_volume", "query_state"]
    assert derive_intents("button", {}) == ["press"]


# --- templates / index

def test_action_documents_cover_aliases_and_location():
    entity = Entity("switch.relay", "switch", "Sypialnia światło", area="sypialnia",
                    where="w sypialni", aliases=["lampa"], intents=["turn_on"])
    texts = [text for _, text, _ in action_documents(entity)]
    assert "włącz lampa" in texts
    assert "włącz Sypialnia światło w sypialni" in texts
    ids = [doc_id for doc_id, _, _ in action_documents(entity)]
    assert len(ids) == len(set(ids))
    assert "pomieszczenie: sypialnia" in candidate_description(entity, "turn_on")


def test_group_hits_keeps_best_score_per_pair():
    hits = [({"entity_id": "a", "intent": "turn_on"}, 0.5),
            ({"entity_id": "b", "intent": "turn_on"}, 0.7),
            ({"entity_id": "a", "intent": "turn_on"}, 0.9)]
    grouped = group_hits(hits)
    assert [(c.key, c.retrieval_score) for c in grouped] == [("a::turn_on", 0.9), ("b::turn_on", 0.7)]


# --- params / actions

@pytest.mark.parametrize("text,expected", [
    ("ustaw na 30%", [30]), ("jasność 75 procent", [75]), ("na połowę", [50]),
    ("na maksa", [100]), ("bez liczby", []), ("200 i 40", [40]),
])
def test_extract_numbers(text, expected):
    assert extract_numbers(text) == expected


def test_extract_color_and_options():
    assert extract_color("ambilight na czerwono") == [255, 0, 0]
    assert extract_color("na szaro") is None
    assert extract_options("ustaw tryb Debug", ["info", "debug"]) == ["debug"]


def test_service_calls():
    assert build_service_call(light(), "set_brightness", "lampa na 30%").data == {
        "entity_id": "light.lamp", "brightness_pct": 30}
    assert build_service_call(light(), "set_brightness", "przyciemnij lampę").data["brightness_step_pct"] == -20
    assert build_service_call(light(), "set_color", "lampa na niebiesko").data["rgb_color"] == [0, 0, 255]
    tv = Entity("media_player.tv", "media_player", "TV")
    assert build_service_call(tv, "set_volume", "głośność 20").data["volume_level"] == 0.2
    assert build_service_call(tv, "set_volume", "ścisz tv").service == "volume_down"
    assert build_service_call(tv, "media_next", "dalej").service == "media_next_track"


def test_service_call_errors_and_chooser():
    with pytest.raises(ParamError):
        build_service_call(light(), "set_brightness", "zmień lampę")
    with pytest.raises(ParamError):
        build_service_call(light(), "query_state", "czy działa")
    call = build_service_call(light(), "set_brightness", "za 5 minut lampa na 40",
                              chooser=lambda values, what: values[-1])
    assert call.data["brightness_pct"] == 40


def test_every_simple_intent_maps_into_allowlist():
    for domain, intents in [("switch", ["turn_on", "turn_off", "toggle"]),
                            ("media_player", ["turn_on", "turn_off", "media_play", "media_pause"]),
                            ("button", ["press"]), ("scene", ["turn_on"])]:
        for intent in intents:
            call = build_service_call(Entity(f"{domain}.x", domain, "x"), intent, "")
            assert (call.domain, call.service) in ALLOWED


# --- decision

SETTINGS = Settings()


def test_apply_gate():
    fits = {"a::turn_on": 0.9}
    assert apply_gate("a::turn_on", 0.95, fits, 0.9, SETTINGS) == (True, "ok")
    assert not apply_gate("a::turn_on", 0.6, fits, 0.9, SETTINGS)[0]
    assert not apply_gate("a::turn_on", 0.95, {"a::turn_on": 0.2}, 0.9, Settings(min_fits=0.5))[0]
    assert apply_gate("a::turn_on", 0.95, {"a::turn_on": 0.2}, 0.9, SETTINGS)[0]
    assert not apply_gate("a::turn_on", 0.95, fits, 0.1, SETTINGS)[0]
    assert not apply_gate(NONE, 0.99, fits, 0.9, SETTINGS)[0]


class FakeTypeSafe:
    def __init__(self, choice, confidence, fits, gate):
        self.answer = (choice, confidence, fits, gate)
        self.calls = []

    def system_one(self, state, questions, model=None):
        self.calls.append((state, questions))
        choice, confidence, fits, gate = self.answer
        nouls = {f"fits_{i}": SimpleNamespace(noul=f) for i, f in enumerate(fits)}
        nouls["gate"] = SimpleNamespace(noul=gate)
        probs = {k: 0.0 for k in questions["action"].criteria}
        probs[choice] = confidence
        return SimpleNamespace(
            choices={"action": SimpleNamespace(choice=choice, confidence=confidence, probabilities=probs)},
            nouls=nouls)


def test_decide_with_fake_client():
    candidates = [Candidate("switch.a", "turn_on"), Candidate("light.b", "turn_on")]
    describe = lambda c: c.key
    questions = build_questions(candidates, describe, describe)
    assert set(questions) == {"action", "gate", "fits_0", "fits_1"}
    assert NONE in questions["action"].criteria
    client = FakeTypeSafe("switch.a::turn_on", 0.93, [0.9, 0.1], 0.97)
    decision = decide(client, "włącz a", candidates, describe, describe, SETTINGS)
    assert decision.accepted and decision.fits == {"switch.a::turn_on": 0.9, "light.b::turn_on": 0.1}
    assert client.calls[0][0]["command"] == "włącz a"


def test_decide_with_lmstudio_client():
    """The TypeSafe SDK parses LM Studio's /v1/systemone answers (shape from the llama.cpp server docs)."""
    import httpx2
    from decision_ha.compat import build_lmstudio_client
    requests_seen = []

    def handler(request):
        requests_seen.append(request)
        return httpx2.Response(200, json={"model": "local-decider", "usage": {"input_tokens": 239, "output_tokens": 0}, "answers": {
            "action": {"type": "choice", "choice": "switch.a::turn_on", "confidence": 0.93,
                       "probabilities": {"switch.a::turn_on": 0.95, "light.b::turn_on": 0.03, NONE: 0.02}},
            "gate": {"type": "noul", "noul": 0.97},
            "fits_0": {"type": "noul", "noul": 0.9},
            "fits_1": {"type": "noul", "noul": 0.1},
        }})

    client = build_lmstudio_client("http://lmstudio.test:1234", transport=httpx2.MockTransport(handler))
    candidates = [Candidate("switch.a", "turn_on"), Candidate("light.b", "turn_on")]
    describe = lambda c: c.key
    decision = decide(client, "włącz a", candidates, describe, describe, Settings(typesafe_model="local-decider"))
    assert decision.accepted and decision.choice == "switch.a::turn_on" and decision.gate == 0.97
    request = requests_seen[0]
    assert str(request.url) == "http://lmstudio.test:1234/v1/systemone"
    assert "content-encoding" not in request.headers
    body = json.loads(request.content)
    assert body["model"] == "local-decider" and body["questions"]["action"]["type"] == "choice"


def test_describe_state():
    entity = light()
    assert describe_state(entity, {"state": "on", "attributes": {"brightness": 128}}) == "Lampa jest włączone (jasność 50%)."
    assert describe_state(entity, {"state": "off", "attributes": {}}) == "Lampa jest wyłączone."
