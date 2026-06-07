from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Protocol
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]:
        ...


class HashEmbeddingProvider:
    def __init__(self, dim: int = 1536) -> None:
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        words = text.lower().split()
        if not words:
            words = [text[:128]]
        for word in words:
            digest = hashlib.sha256(word.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = sum(value * value for value in vector) ** 0.5 or 1.0
        return [value / norm for value in vector]


class OpenAICompatibleEmbeddingProvider:
    def __init__(self, api_base: str, api_key: str, model: str, dim: int = 1536) -> None:
        if not api_base or not api_key or not model:
            raise ValueError("embedding API base, key, and model are required")
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        payload = json.dumps({"model": self.model, "input": text}).encode("utf-8")
        request = Request(
            f"{self.api_base}/embeddings",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        for attempt in range(3):
            try:
                with urlopen(request, timeout=30) as response:  # noqa: S310 - configured internal API.
                    data = json.loads(response.read().decode("utf-8"))
                embedding = data["data"][0]["embedding"]
                if len(embedding) != self.dim:
                    raise ValueError("embedding dimension mismatch")
                return [float(value) for value in embedding]
            except (KeyError, URLError, TimeoutError, ValueError) as exc:
                if attempt == 2:
                    raise RuntimeError("embedding API request failed") from exc
                logger.warning("embedding API request failed; retrying")
                time.sleep(1 + attempt)
        raise RuntimeError("embedding API request failed")


def get_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()
    if settings.embedding_provider == "openai_compatible":
        return OpenAICompatibleEmbeddingProvider(
            api_base=settings.embedding_api_base,
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            dim=settings.embedding_dim,
        )
    return HashEmbeddingProvider(dim=settings.embedding_dim)

