"""Vector index of action documents: bge-m3 embeddings in a persistent ChromaDB collection."""

from dataclasses import dataclass

from decision_ha.templates import action_documents

COLLECTION = "actions"


@dataclass
class Candidate:
    entity_id: str
    intent: str
    retrieval_score: float = 0.0
    rerank_score: float | None = None

    @property
    def key(self):
        return f"{self.entity_id}::{self.intent}"


def group_hits(hits):
    """Collapse document hits [(meta, similarity)] to unique (entity, intent) candidates,
    keeping each one's best similarity, in descending order."""
    best = {}
    for meta, similarity in hits:
        key = (meta["entity_id"], meta["intent"])
        if key not in best or similarity > best[key]:
            best[key] = similarity
    ranked = sorted(best.items(), key=lambda kv: -kv[1])
    return [Candidate(entity_id=e, intent=i, retrieval_score=s) for (e, i), s in ranked]


class ActionIndex:
    def __init__(self, path, model_name):
        self.path = path
        self.model_name = model_name
        self._model = None
        self._collection = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def _client(self):
        import chromadb
        return chromadb.PersistentClient(path=str(self.path))

    def embed(self, texts):
        return self.model.encode(texts, normalize_embeddings=True, batch_size=64).tolist()

    def build(self, catalog):
        client = self._client()
        if COLLECTION in [c.name for c in client.list_collections()]:
            client.delete_collection(COLLECTION)
        collection = client.create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})
        ids, texts, metas = [], [], []
        for entity in catalog:
            for doc_id, text, meta in action_documents(entity):
                ids.append(doc_id)
                texts.append(text)
                metas.append(meta)
        embeddings = self.embed(texts)
        for start in range(0, len(ids), 1000):
            end = start + 1000
            collection.add(ids=ids[start:end], documents=texts[start:end],
                           metadatas=metas[start:end], embeddings=embeddings[start:end])
        return len(ids)

    def search(self, text, k):
        if self._collection is None:
            self._collection = self._client().get_collection(COLLECTION)
        result = self._collection.query(query_embeddings=self.embed([text]), n_results=k)
        hits = [(meta, 1.0 - dist) for meta, dist in zip(result["metadatas"][0], result["distances"][0])]
        return group_hits(hits)
