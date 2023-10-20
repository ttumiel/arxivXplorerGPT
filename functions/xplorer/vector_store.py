import base64
import json
from typing import List, Optional, Tuple

import numpy as np
import openai
from tenacity import retry, stop_after_attempt, wait_random_exponential


class VectorStore:
    vectors: np.ndarray = None
    chunks: List[str] = None
    transform: Optional[np.ndarray] = None

    def embed(self, chunks: List[str], compress_dim: Optional[int] = 384):
        self.chunks = chunks
        self.compress_dim = compress_dim
        embeddings = self._embed_query(chunks)

        if self.compress_dim:
            embeddings, self.transform = self.compress(embeddings, self.compress_dim)

        self.vectors = embeddings

    def compress(self, data: np.ndarray, compression_dim: int):
        """Use SVD to compress a 2D np array to compression_dim dimensions.

        Parameters:
        - data (np.ndarray): Input data with shape [N, K]
        - compression_dim (int): Target number of dimensions

        Returns:
        - np.ndarray: Compressed data with shape [N, compression_dim]
        - np.ndarray: Transform matrix with shape [K, compression_dim]
        """
        self.compress_dim = min(compression_dim, *data.shape)

        # Perform Singular Value Decomposition
        U, S, VT = np.linalg.svd(data, full_matrices=False)

        # Truncate to compression_dim dimensions
        X_k = U[:, : self.compress_dim] * S[: self.compress_dim]
        VT_k = VT[: self.compress_dim]

        return X_k, VT_k.T

    @retry(
        wait=wait_random_exponential(min=2, max=10),
        stop=stop_after_attempt(2),
        reraise=True,
    )
    def _embed_query(self, queries: List[str]) -> np.ndarray:
        try:
            data = openai.Embedding.create(
                input=queries, engine="text-embedding-ada-002"
            )["data"]
        except Exception as e:
            raise ValueError(f"OpenAI embedding failed with {e}")

        return np.array(
            [v["embedding"] for v in sorted(data, key=lambda x: x["index"])],
            dtype=np.float32,
        )

    def search(self, query: str, count: int = 3) -> List[str]:
        if self.vectors is None or self.chunks is None:
            raise ValueError("Vectors and chunks must be initialized before search.")

        query = self._embed_query([query])[0]
        if self.transform is not None:
            query = query @ self.transform

        similarity = self.vectors @ query
        arg_count = count if count < len(similarity) else len(similarity) - 1
        partitioned_indices = np.argpartition(-similarity, kth=arg_count)[:count]
        top_indices = partitioned_indices[np.argsort(-similarity[partitioned_indices])]

        return [self.chunks[i] for i in top_indices]

    def _to_base64(self, arr: np.ndarray):
        if arr is None:
            return
        return base64.b64encode(arr.tobytes()).decode("ascii")

    def _from_base64(self, b64: str, shape: Tuple[int, int]):
        if b64 is None:
            return
        return np.frombuffer(base64.b64decode(b64), dtype=np.float32).reshape(shape)

    def dump(self):
        return {
            "vectors": self._to_base64(self.vectors),
            "transform": self._to_base64(self.transform),
            "chunks": json.dumps(self.chunks),
            "dim": self.compress_dim,
        }

    @classmethod
    def load(cls, data):
        store = cls()
        dim = data["dim"]
        store.compress_dim = dim
        store.chunks = json.loads(data["chunks"])
        store.vectors = store._from_base64(data["vectors"], (len(store.chunks), dim))
        store.transform = store._from_base64(data["transform"], (1536, dim))
        return store
