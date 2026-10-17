"""Cross-encoder reranking of retrieved candidates (bge-reranker-v2-m3, multilingual)."""


class Reranker:
    def __init__(self, model_name):
        self.model_name = model_name
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.model_name)
        return self._model

    def rerank(self, query, candidates, describe, top_n):
        """Score (query, describe(candidate)) pairs; return the top_n candidates, best first."""
        if not candidates:
            return []
        scores = self.model.predict([(query, describe(c)) for c in candidates])
        for candidate, score in zip(candidates, scores):
            candidate.rerank_score = float(score)
        return sorted(candidates, key=lambda c: -c.rerank_score)[:top_n]
