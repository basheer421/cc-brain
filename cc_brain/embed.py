"""Local embeddings via Ollama (private: brain content never leaves the machine).

Every caller must tolerate None — if Ollama is down, retrieval falls back to BM25.
"""

import logging

import numpy as np

logger = logging.getLogger("cc-brain")

DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "nomic-embed-text"
BATCH = 64


class Embedder:
    def __init__(self, config=None):
        cfg = (config or {}).get("embedding", {})
        self.url = cfg.get("url", DEFAULT_URL).rstrip("/")
        self.model = cfg.get("model", DEFAULT_MODEL)
        self.enabled = cfg.get("enabled", True)
        self._down = False

    def _embed(self, texts):
        import requests

        out = []
        for i in range(0, len(texts), BATCH):
            resp = requests.post(
                f"{self.url}/api/embed",
                json={"model": self.model, "input": texts[i:i + BATCH], "truncate": True},
                timeout=120,
            )
            resp.raise_for_status()
            out.extend(resp.json()["embeddings"])
        arr = np.asarray(out, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return arr / norms

    def _safe(self, texts):
        if not self.enabled or self._down or not texts:
            return None
        try:
            return self._embed(texts)
        except Exception as e:  # network, model missing, bad response
            logger.warning("Embedding unavailable (%s); falling back to BM25", e)
            self._down = True
            return None

    # nomic-embed-text is trained with task prefixes
    def documents(self, texts):
        return self._safe([f"search_document: {t}" for t in texts])

    def query(self, text):
        arr = self._safe([f"search_query: {text}"])
        return None if arr is None else arr[0]


def to_blob(vec):
    return None if vec is None else np.asarray(vec, dtype=np.float32).tobytes()


def from_blob(blob):
    return np.frombuffer(blob, dtype=np.float32)
