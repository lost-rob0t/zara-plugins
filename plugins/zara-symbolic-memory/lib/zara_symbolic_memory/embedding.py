from __future__ import annotations

import json
import math
import urllib.request
from dataclasses import dataclass
from typing import Protocol, Sequence


MAX_EMBEDDING_DIMENSIONS = 8192
MAX_EMBED_BATCH = 64


class EmbeddingError(RuntimeError):
    pass


class Embedder(Protocol):
    model: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        ...


def _validate_vectors(vectors: object, expected: int) -> list[list[float]]:
    if not isinstance(vectors, list) or len(vectors) != expected:
        raise EmbeddingError("embedding response count mismatch")
    rendered: list[list[float]] = []
    for vector in vectors:
        if not isinstance(vector, list) or not vector or len(vector) > MAX_EMBEDDING_DIMENSIONS:
            raise EmbeddingError("embedding vector is invalid")
        values: list[float] = []
        for item in vector:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise EmbeddingError("embedding vector contains a non-number")
            value = float(item)
            if not math.isfinite(value):
                raise EmbeddingError("embedding vector contains a non-finite value")
            values.append(value)
        rendered.append(values)
    dimensions = {len(vector) for vector in rendered}
    if len(dimensions) != 1:
        raise EmbeddingError("embedding vectors have inconsistent dimensions")
    return rendered


@dataclass(frozen=True)
class OpenAICompatibleEmbedder:
    endpoint: str
    model: str
    api_key: str = ""
    timeout_seconds: float = 10.0

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        items = list(texts)
        if not items or len(items) > MAX_EMBED_BATCH:
            raise EmbeddingError("embedding batch size is out of range")
        payload = json.dumps({"model": self.model, "input": items}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            self.endpoint.rstrip("/") + "/embeddings",
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except Exception as error:
            raise EmbeddingError("embedding provider request failed") from error
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            raise EmbeddingError("embedding provider response is invalid")
        ordered = sorted(data, key=lambda item: item.get("index", 0) if isinstance(item, dict) else 0)
        vectors = [item.get("embedding") if isinstance(item, dict) else None for item in ordered]
        return _validate_vectors(vectors, len(items))


@dataclass(frozen=True)
class OllamaEmbedder:
    base_url: str
    model: str
    timeout_seconds: float = 10.0

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        items = list(texts)
        if not items or len(items) > MAX_EMBED_BATCH:
            raise EmbeddingError("embedding batch size is out of range")
        payload = json.dumps({"model": self.model, "input": items}).encode("utf-8")
        request = urllib.request.Request(
            self.base_url.rstrip("/") + "/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except Exception as error:
            raise EmbeddingError("embedding provider request failed") from error
        vectors = body.get("embeddings") if isinstance(body, dict) else None
        return _validate_vectors(vectors, len(items))
