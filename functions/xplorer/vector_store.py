from typing import List, Optional

import numpy as np
import openai
from tenacity import retry, stop_after_attempt, wait_random_exponential


class VectorStore:
    vectors: np.ndarray = None
    chunks: List[str] = None
    transform: Optional[np.ndarray] = None

    def embed(self, chunks: List[str], compress_dim: Optional[int] = 384):
        self.chunks = chunks
        embeddings = self._embed_query(chunks)

        if compress_dim:
            embeddings, self.transform = self.compress(embeddings, compress_dim)

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
        compression_dim = min(compression_dim, *data.shape)

        # Perform Singular Value Decomposition
        U, S, VT = np.linalg.svd(data, full_matrices=False)

        # Truncate to compression_dim dimensions
        X_k = U[:, :compression_dim] * S[:compression_dim]
        VT_k = VT[:compression_dim]

        return X_k, VT_k.T

    @retry(wait=wait_random_exponential(min=2, max=10), stop=stop_after_attempt(3))
    def _embed_query(self, queries: List[str]) -> np.ndarray:
        data = openai.Embedding.create(input=queries, engine="text-embedding-ada-002")[
            "data"
        ]
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

    def dump(self):
        transform = self.transform.tolist() if self.transform is not None else None
        return {
            "vectors": self.vectors.tolist(),
            "transform": transform,
            "chunks": self.chunks,
        }

    @classmethod
    def load(cls, data):
        store = cls()
        store.vectors = data["vectors"]
        store.transform = data["transform"]
        store.chunks = data["chunks"]
        return store
