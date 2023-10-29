import gzip
import logging
import os
import random
import shutil
import tarfile
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Dict, List, Optional, Union

import arxiv
import requests
from firebase_admin import db, firestore
from google.cloud import firestore as g_firestore
from typing_extensions import TypedDict
from xplorer.latex_paper import LatexPaper, Paper, guess_main_tex_file
from xplorer.pdf_paper import PDFPaper
from xplorer.vector_store import VectorStore

logger = logging.getLogger(__name__)


class PaperSearchResult(TypedDict, total=False):
    id: str
    title: str
    date: str
    first_author: str
    abstract_snippet: str


class PaperMetadata(TypedDict, total=False):
    id: str
    title: str
    date: str
    authors: str
    abstract: str
    table_of_contents: str
    can_read_citation: bool


@dataclass
class PaperData:
    id: str
    title: str
    date: str
    authors: str
    abstract: str
    table_of_contents: Optional[str] = None
    can_read_citation: Optional[bool] = False
    paper: Optional[Paper] = None

    def to_dict(self, show_abstract=True) -> PaperMetadata:
        return {
            f.name: attr
            for f in fields(self)
            if (attr := getattr(self, f.name))
            and (show_abstract or f.name != "abstract")
            and f.name != "paper"
        }

    def dump(self) -> Dict[str, Optional[str]]:
        return {
            "id": self.id,
            "title": self.title,
            "date": self.date,
            "authors": self.authors,
            "abstract": self.abstract,
            "table_of_contents": self.table_of_contents,
            "can_read_citation": self.can_read_citation,
            "paper": self.paper.dumps(vectors=False),
        }

    @classmethod
    def load(cls, data: Dict[str, Optional[str]]):
        data = cls(**data)
        data.paper = Paper.loads(data.paper)
        return data


class PaperCache:
    def __init__(self, firestore_collection: Optional[str] = None):
        self.local_db = LocalPaperCache(limit=15)
        if firestore_collection:
            self.firestore_db = FirestorePaperCache(firestore_collection, limit=5000)
            self.realtime_db = RealtimeDBPaperCache(limit=5000)
        else:
            self.firestore_db = self.realtime_db = None

    def __getitem__(self, paper_id: str) -> PaperData:
        """Read a paper from the cache if it exists, otherwise download and parse it."""
        paper_data = self.local_db[paper_id]

        if self.firestore_db is not None and paper_data is None:
            paper_data = self.firestore_db[paper_id]
            if paper_data is not None:
                self.local_db[paper_id] = paper_data

        if paper_data is None:
            paper_data = self.get_paper_details(paper_id)
            paper = self.fetch_paper(paper_id, paper_data.title)
            paper_data.paper = paper
            paper_data.can_read_citation = paper.can_read_citation
            paper_data.table_of_contents = paper.table_of_contents

            self[paper_id] = paper_data

        return paper_data

    def get_vector_store(self, paper_id: str) -> VectorStore:
        if paper_id in self.local_db.chunk_db:
            return self.local_db.chunk_db[paper_id]

        store = self.realtime_db[paper_id]
        if store is not None:
            self.local_db.chunk_db[paper_id] = store
            return store

        paper_data = self[paper_id]
        store = VectorStore()
        store.embed(paper_data.paper.chunk_tree())
        self.local_db.chunk_db[paper_id] = store
        self.realtime_db[paper_id] = store
        return store

    def __setitem__(self, paper_id: str, paper: PaperData):
        self.local_db[paper_id] = paper
        self.firestore_db[paper_id] = paper
        if paper.paper.store is not None:
            self.realtime_db[paper_id] = paper.paper.store

    def get_paper_details(self, paper_id: str) -> PaperData:
        """
        Get partial paper details from arXiv given a paper_id.
        """
        search = arxiv.Search(id_list=[paper_id], max_results=1)
        results = list(search.results())

        if not results:
            raise ValueError(f"No paper found for ID {paper_id}")

        paper = results[0]
        return PaperData(
            paper_id,
            paper.title,
            paper.published.strftime("%Y-%m-%d"),
            ", ".join(str(a) for a in paper.authors),
            paper.summary,
        )

    def extract_source(self, file_path, output_dir):
        "Arxiv source is either a tar.gz folder or a gzipped tex file."
        if tarfile.is_tarfile(file_path):
            with tarfile.open(file_path, "r:gz") as tar:
                tar.extractall(path=output_dir)
        else:
            with gzip.open(file_path, "rb") as f_in:
                output_file_path = os.path.join(output_dir, "main.tex")
                os.makedirs(output_dir, exist_ok=True)
                with open(output_file_path, "wb") as f_out:
                    f_out.write(f_in.read())

    def fetch_pdf_paper(self, arxiv_id: str, title: Optional[str] = None) -> PDFPaper:
        try:
            paper = next(arxiv.Search(id_list=[arxiv_id], max_results=1).results())
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
                directory, filename = os.path.split(temp_file.name)
                paper.download_pdf(directory, filename)
                return PDFPaper(temp_file.name, title=title)
        except Exception as e:
            logger.error(f"Error fetching pdf paper: {e}")
            return None

    def download_arxiv_source(self, arxiv_id) -> str:
        source_url = f"https://export.arxiv.org/e-print/{arxiv_id}"

        response = requests.get(source_url)
        response.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".gz", delete=False) as temp_file:
            temp_file.write(response.content)
            temp_file_path = temp_file.name

        return temp_file_path

    def fetch_source_paper(self, paper_id, title: Optional[str] = None) -> LatexPaper:
        # TODO: parallel download, and set timeout for parsing
        try:
            # Download the source
            filename = self.download_arxiv_source(paper_id)

            # extract the tar file
            datadir = filename.replace(".gz", "")
            self.extract_source(filename, datadir)

            # delete the tar file
            os.remove(filename)

            # Extract the text
            main_file = guess_main_tex_file(datadir)
            paper = LatexPaper(main_file, title=title)

            # Remove the extracted files
            shutil.rmtree(datadir)

            return paper
        except Exception as e:
            import traceback

            logger.error(f"Error fetching latex paper: {e}\n {traceback.format_exc()}")
            return None

    def fetch_paper(self, paper_id: str, title: str) -> Paper:
        """Attempt to download and parse an arxiv paper. First from latex source
        and then from the PDF, if the source fails.
        """
        paper = self.fetch_source_paper(paper_id, title)
        if paper is None:
            paper = self.fetch_pdf_paper(paper_id, title)

        assert paper is not None, "Couldn't fetch paper."
        return paper

    def lru_delete_remote(self) -> int:
        deleted_ids = self.firestore_db.lru_delete()
        for paper_id in deleted_ids:
            self.realtime_db.delete(paper_id)
        return len(deleted_ids)


class DBCache(ABC):
    def __init__(self, limit: int):
        super().__init__()
        self.limit = limit

    @abstractmethod
    def __getitem__(self, paper_id: str) -> Optional[PaperData]:
        "Reads a paper from the database, returning None if not present."

    @abstractmethod
    def __setitem__(self, paper_id: str, paper: PaperData):
        "Adds a paper to the database with a timestamp."

    @abstractmethod
    def lru_delete(self):
        "Deletes the least recently used entries in the DB beyond the db's max size."

    def _sanitize_path(self, path: str) -> str:
        return path.replace("/", "_").replace(".", "_")


class LocalPaperCache(DBCache):
    def __init__(self, limit: int = 2):
        super().__init__(limit)
        self.db: Dict[str, Dict[str, Union[PaperMetadata, datetime]]] = {}
        self.chunk_db: Dict[str, VectorStore] = {}

    def __setitem__(self, paper_id: str, paper: PaperData):
        self.db[paper_id] = {"paper": paper.dump(), "timestamp": datetime.now()}
        if paper.paper.store is not None:
            self.chunk_db[paper_id] = paper.paper.store
        self.lru_delete()

    def __getitem__(self, paper_id: str) -> Optional[PaperData]:
        if paper_id in self.db:
            record = self.db[paper_id]
            record["timestamp"] = datetime.now()
            return PaperData.load(record["paper"])
        else:
            return None

    def lru_delete(self):
        # Calculate the number of documents to delete
        num_to_delete = max(0, len(self.db) - self.limit)

        if num_to_delete > 0:
            keys = sorted(self.db, key=lambda k: self.db[k]["timestamp"])[
                :num_to_delete
            ]
            for key in keys:
                del self.db[key]
                if key in self.chunk_db:
                    del self.chunk_db[key]


class FirestorePaperCache(DBCache):
    def __init__(self, collection_name: str = "papers", limit: int = 10000):
        super().__init__(limit)
        self.db: g_firestore.Client = firestore.client()
        self.collection_name = collection_name

    def __setitem__(self, paper_id: str, paper: PaperData):
        paper_id = self._sanitize_path(paper_id)
        with self.db.transaction():
            doc_ref = self.db.collection(self.collection_name).document(paper_id)
            doc_ref.set(
                {"paper": paper.dump(), "timestamp": g_firestore.SERVER_TIMESTAMP}
            )

    def __getitem__(self, paper_id: str) -> Optional[PaperData]:
        paper_id = self._sanitize_path(paper_id)
        doc_ref = self.db.collection(self.collection_name).document(paper_id)
        doc = doc_ref.get()
        if doc.exists:
            # TODO: Should I update the timestamp on every get?
            if random.random() < 0.1:
                doc_ref.update({"timestamp": g_firestore.SERVER_TIMESTAMP})

            data = doc.to_dict()
            if "paper" in data:
                return PaperData.load(data["paper"])

        return None

    def lru_delete(self) -> List[str]:
        # Get the count of documents in the collection
        results = self.db.collection(self.collection_name).count(alias="all").get()
        docs_count = results[0][0].value if results else 0

        # Calculate the number of documents to delete
        num_to_delete = max(0, docs_count - self.limit)
        paper_ids = []

        if num_to_delete > 0:
            # Query for the oldest documents, limited to the number to delete
            query = (
                self.db.collection(self.collection_name)
                .order_by("timestamp")
                .limit(num_to_delete)
            )

            for doc in query.stream():
                doc.reference.delete()
                paper_ids.append(doc.id)

        return paper_ids


class RealtimeDBPaperCache(DBCache):
    def __init__(self, ref_path: str = "vectors", limit: int = 1000):
        "The realtime DB is just used to cache the vector stores due to larger value size limit."
        super().__init__(limit)
        self.ref = db.reference(ref_path)

    def __setitem__(self, paper_id: str, vector_store: VectorStore):
        self.ref.child(self._sanitize_path(paper_id)).set(vector_store.dump())

    def __getitem__(self, paper_id: str) -> Optional[PaperData]:
        record = self.ref.child(self._sanitize_path(paper_id)).get()
        if record:
            return VectorStore.load(record)
        return None

    def delete(self, paper_id: str):
        self.ref.child(self._sanitize_path(paper_id)).delete()

    def lru_delete(self) -> int:
        raise NotImplementedError
