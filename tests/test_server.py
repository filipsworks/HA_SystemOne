import pytest
from fastapi.testclient import TestClient

from decision_ha.actions import ServiceCall
from decision_ha.config import Settings
from decision_ha.decide import Decision
from decision_ha.ha_client import HAAuthError
from decision_ha.index import Candidate
from decision_ha.pipeline import Result
from decision_ha.server import create_app

TOKEN = "s3cret"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakePipeline:
    settings = Settings()

    def __init__(self, error=None, decision=None):
        self.runs = []
        self.error = error
        self.decision = decision
        self.warmed = False

    def warm_up(self):
        self.warmed = True

    def entity_name(self, key):
        return {"switch.relay": "Sypialnia światło", "light.led": "Dioda"}[key.split("::")[0]]

    def run(self, text, execute=False):
        self.runs.append((text, execute))
        if self.error:
            raise self.error
        if self.decision:
            return Result(text, decision=self.decision, answer="Niepewne — długi opis kandydatów")
        candidate = Candidate("switch.relay", "turn_on", rerank_score=0.91)
        decision = Decision("switch.relay::turn_on", 0.95, {"switch.relay::turn_on": 0.95}, {}, 0.99, True, "ok")
        call = ServiceCall("switch", "turn_on", {"entity_id": "switch.relay"})
        return Result(text, reranked=[candidate], decision=decision, call=call, executed=execute)


def client(token=TOKEN, pipeline=None):
    pipeline = pipeline or FakePipeline()
    return TestClient(create_app(lambda: pipeline, token)), pipeline


def test_health_and_dry_run():
    test_client, pipeline = client()
    with test_client as c:
        assert pipeline.warmed
        assert c.get("/health").json() == {"status": "ok"}
        body = c.post("/decide", json={"text": " włącz światło "}, headers=AUTH).json()
    assert body["accepted"] and not body["executed"]
    assert body["entity_id"] == "switch.relay" and body["intent"] == "turn_on"
    assert body["call"] == {"domain": "switch", "service": "turn_on", "data": {"entity_id": "switch.relay"}}
    assert body["speech"] == "Dry-run: switch.turn_on (Sypialnia światło)."
    assert body["text"] == "włącz światło"


def test_execute_with_token():
    test_client, pipeline = client()
    with test_client as c:
        body = c.post("/decide", json={"text": "włącz", "execute": True}, headers=AUTH).json()
    assert body["executed"] and body["speech"].startswith("Wykonano")
    assert pipeline.runs == [("włącz", True)]


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN}])
def test_bad_token_rejected(headers):
    test_client, pipeline = client()
    with test_client as c:
        assert c.post("/decide", json={"text": "włącz"}, headers=headers).status_code == 401
    assert pipeline.runs == []


def test_no_token_means_dry_run_only():
    test_client, pipeline = client(token=None)
    with test_client as c:
        assert c.post("/decide", json={"text": "włącz"}).status_code == 200
        assert c.post("/decide", json={"text": "włącz", "execute": True}).status_code == 403
    assert pipeline.runs == [("włącz", False)]


def test_ha_errors_and_validation():
    with client(pipeline=FakePipeline(HAAuthError("401")))[0] as c:
        assert c.post("/decide", json={"text": "włącz"}, headers=AUTH).status_code == 502
        assert c.post("/decide", json={"text": ""}, headers=AUTH).status_code == 422


def abstain(choice, gate):
    return Decision(choice, 0.6, {}, {}, gate, False, "niepewne",
                    alternatives=["switch.relay::turn_on", "switch.relay::toggle", "light.led::turn_on"])


@pytest.mark.parametrize("choice,gate,speech", [
    ("switch.relay::turn_on", 0.9, "Nie jestem pewien. Czy chodziło o: Sypialnia światło, Dioda?"),
    ("none", 0.9, "Nie mam urządzenia ani akcji pasującej do tego polecenia."),
    ("switch.relay::turn_on", 0.05, "Nie rozumiem polecenia."),
])
def test_abstain_speech_is_short(choice, gate, speech):
    with client(pipeline=FakePipeline(decision=abstain(choice, gate)))[0] as c:
        body = c.post("/decide", json={"text": "włącz"}, headers=AUTH).json()
    assert not body["accepted"] and body["call"] is None
    assert body["speech"] == speech
    assert body["answer"].startswith("Niepewne")
