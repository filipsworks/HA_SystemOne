"""retrieve → rerank → TypeSafe decide → service call / state answer."""

from dataclasses import dataclass, field

from decision_ha.actions import ParamError, ServiceCall, build_service_call
from decision_ha.config import CATALOG_PATH, CHROMA_DIR
from decision_ha.catalog import load_catalog
from decision_ha.decide import Decision, choose_value, decide
from decision_ha.execute import describe_state
from decision_ha.index import ActionIndex, Candidate
from decision_ha.rerank import Reranker
from decision_ha.templates import candidate_description, fits_question


@dataclass
class Result:
    text: str
    retrieved: list[Candidate] = field(default_factory=list)
    reranked: list[Candidate] = field(default_factory=list)
    decision: Decision | None = None
    call: ServiceCall | None = None
    answer: str | None = None       # query_state answer, or the reason nothing happens
    executed: bool = False

    @property
    def entity_intent(self):
        if self.decision and self.decision.accepted:
            return tuple(self.decision.choice.split("::", 1))
        return None


class Pipeline:
    def __init__(self, settings, typesafe_client, ha=None):
        self.settings = settings
        self.ts = typesafe_client
        self.ha = ha
        self.catalog = load_catalog(CATALOG_PATH)
        self.index = ActionIndex(CHROMA_DIR, settings.embed_model)
        self.reranker = Reranker(settings.rerank_model)
        areas = sorted({e.area for e in self.catalog.values() if e.area})
        self.home = "Pomieszczenia: " + ", ".join(areas)

    def warm_up(self):
        """Load both models and the Chroma collection now (they load lazily) — no TypeSafe call."""
        candidates = self.index.search("włącz światło", 1)
        self.reranker.rerank("włącz światło", candidates, self.describe, 1)

    def entity_name(self, key):
        return self.catalog[key.split("::", 1)[0]].name

    def describe(self, candidate):
        return candidate_description(self.catalog[candidate.entity_id], candidate.intent)

    def run(self, text, execute=False):
        result = Result(text=text)
        result.retrieved = [c for c in self.index.search(text, self.settings.retrieve_k)
                            if c.entity_id in self.catalog]
        result.reranked = self.reranker.rerank(text, list(result.retrieved), self.describe,
                                               self.settings.rerank_k)
        if not result.reranked:
            result.answer = "Brak kandydatów — czy indeks jest zbudowany?"
            return result
        result.decision = decide(self.ts, text, result.reranked, self.describe, self.fits_question,
                                 self.settings, home=self.home)
        if not result.decision.accepted:
            names = [self.describe_key(k) for k in result.decision.alternatives]
            result.answer = f"Niepewne — {result.decision.reason}. Czy chodziło o: " + " | ".join(names)
            return result

        entity_id, intent = result.entity_intent
        entity = self.catalog[entity_id]
        if intent == "query_state":
            if self.ha is None:
                result.answer = f"(dry-run) odczytałbym stan {entity_id}"
            else:
                result.answer = describe_state(entity, self.ha.state(entity_id))
            return result

        chooser = lambda values, what: choose_value(self.ts, text, values, what, self.settings)
        try:
            result.call = build_service_call(entity, intent, text, chooser)
        except ParamError as error:
            result.answer = f"Nie mogę wykonać: {error}"
            return result
        if execute:
            self.ha.call_service(result.call.domain, result.call.service, result.call.data)
            result.executed = True
        return result

    def fits_question(self, candidate):
        return fits_question(self.catalog[candidate.entity_id], candidate.intent)

    def describe_key(self, key):
        entity_id, intent = key.split("::", 1)
        return self.describe(Candidate(entity_id, intent))
