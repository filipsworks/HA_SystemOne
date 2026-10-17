"""Long-running HTTP service: models load once, then HA calls POST /decide via rest_command."""

import secrets
import threading
from contextlib import asynccontextmanager

import requests
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from decision_ha.decide import NONE
from decision_ha.ha_client import HAAuthError


class DecideRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    execute: bool = False


def speech_for(result, pipeline):
    """A short Polish sentence to show or speak in HA; `answer` keeps the full detail."""
    d, call = result.decision, result.call
    if call:
        prefix = "Wykonano" if result.executed else "Dry-run"
        return f"{prefix}: {call.domain}.{call.service} ({pipeline.entity_name(d.choice)})."
    if d and not d.accepted:
        if d.gate < pipeline.settings.min_gate:
            return "Nie rozumiem polecenia."
        if d.choice == NONE or not d.alternatives:
            # TypeSafe is sure nothing fits — the closest candidates would only mislead
            return "Nie mam urządzenia ani akcji pasującej do tego polecenia."
        names = list(dict.fromkeys(pipeline.entity_name(k) for k in d.alternatives))
        return "Nie jestem pewien. Czy chodziło o: " + ", ".join(names) + "?"
    return result.answer or ""


def result_payload(result, pipeline):
    """JSON for HA: `speech` for the user, the rest for automations and debugging."""
    d = result.decision
    call = result.call
    return {
        "text": result.text,
        "accepted": bool(d and d.accepted),
        "executed": result.executed,
        "speech": speech_for(result, pipeline),
        "answer": result.answer,
        "entity_id": result.entity_intent[0] if result.entity_intent else None,
        "intent": result.entity_intent[1] if result.entity_intent else None,
        "call": call and {"domain": call.domain, "service": call.service, "data": call.data},
        "decision": d and {
            "choice": d.choice, "confidence": round(d.confidence, 3), "gate": round(d.gate, 3),
            "reason": d.reason, "alternatives": d.alternatives,
        },
        "reranked": [{"key": c.key, "score": round(c.rerank_score, 3)} for c in result.reranked],
    }


def create_app(make_pipeline, token=None):
    """make_pipeline() is called once at startup. Without a token, execute requests are refused."""
    state = {}
    lock = threading.Lock()  # one query at a time: the models and the TypeSafe client are shared

    @asynccontextmanager
    async def lifespan(app):
        pipeline = make_pipeline()
        pipeline.warm_up()
        state["pipeline"] = pipeline
        yield
        state.clear()

    app = FastAPI(title="decision_ha", lifespan=lifespan)

    def check_token(authorization: str | None = Header(default=None)):
        if token is None:
            return
        scheme, _, value = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(value, token):
            raise HTTPException(401, "Nieprawidłowy lub brakujący token (Authorization: Bearer …)")

    @app.get("/health")
    def health():
        return {"status": "ok" if "pipeline" in state else "loading"}

    @app.post("/decide", dependencies=[Depends(check_token)])
    def decide(request: DecideRequest):
        if request.execute and token is None:
            raise HTTPException(403, "Wykonywanie wyłączone: ustaw DECISION_API_TOKEN w .env")
        pipeline = state.get("pipeline")
        if pipeline is None:
            raise HTTPException(503, "Modele jeszcze się ładują")
        try:
            with lock:
                result = pipeline.run(request.text.strip(), execute=request.execute)
        except (HAAuthError, requests.RequestException) as error:
            raise HTTPException(502, f"Błąd Home Assistanta: {error}")
        return result_payload(result, pipeline)

    return app
