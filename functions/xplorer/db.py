import logging
import os
import re
import shutil
import tarfile
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Dict, List, Optional, TypedDict, Union

import arxiv
import requests
from firebase_admin import firestore
from google.cloud import firestore as g_firestore
from google.cloud import storage
from xplorer.latex_paper import LatexPaper, Paper, guess_main_tex_file
from xplorer.pdf_paper import PDFPaper

logger = logging.getLogger(__name__)


class PaperDataDict(TypedDict, total=False):
    id: str
    title: str
    date: str
    authors: Optional[str]
    abstract: Optional[str]
    table_of_contents: Optional[str]
    has_bibliography: Optional[bool]


@dataclass
class PaperData:
    id: str
    title: str
    date: str
    authors: Optional[List[str]] = None
    abstract: Optional[str] = None
    table_of_contents: Optional[str] = None
    has_bibliography: Optional[bool] = False
    paper: Optional[Paper] = None

    def to_dict(self, show_abstract=True) -> PaperDataDict:
        return {
            f.name: ", ".join(attr) if isinstance(attr, list) else attr
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
            "has_bibliography": self.has_bibliography,
            "paper": self.paper.dumps(),
        }

    @classmethod
    def load(cls, data: Dict[str, Optional[str]]):
        data = cls(**data)
        data.paper = Paper.loads(data.paper)
        return data


class PaperCache:
    def __init__(self, firestore_collection: Optional[str] = None):
        self.local_db: DBCache = LocalPaperCache(limit=2)
        if firestore_collection:
            self.remote_db: DBCache = FirestorePaperCache(firestore_collection, limit=2)
        else:
            self.remote_db = None

    def __getitem__(self, paper_id: str) -> PaperData:
        """Read a paper from the cache if it exists, otherwise download and parse it."""
        paper_data = self.local_db[paper_id]

        if self.remote_db is not None and paper_data is None:
            paper_data = self.remote_db[paper_id]
            if paper_data is not None:
                self.local_db[paper_id] = paper_data

        if paper_data is None:
            paper_data = self.get_paper_details(paper_id)
            paper = self.fetch_paper(paper_id, paper_data.title)
            paper_data.paper = paper
            paper_data.has_bibliography = paper.has_bibliography
            paper_data.table_of_contents = paper.table_of_contents

            self[paper_id] = paper_data

        return paper_data

    def __setitem__(self, paper_id: str, paper: PaperData):
        self.local_db[paper_id] = paper
        self.remote_db[paper_id] = paper

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
            [str(a) for a in paper.authors],
            paper.summary,
        )

    def extract_tar_file(self, tar_path, output_dir):
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(path=output_dir)

    def fetch_pdf_paper(
        self, arxiv_id, output_dir, title: Optional[str] = None
    ) -> PDFPaper:
        try:
            bucket_name = "arxiv-dataset"
            storage_client = storage.Client()
            bucket = storage_client.bucket(bucket_name)

            prefix = f"arxiv/arxiv/pdf/{arxiv_id[:4]}/{arxiv_id}"
            blob_name = max(blob.name for blob in bucket.list_blobs(prefix=prefix))
            blob = bucket.blob(blob_name)

            os.makedirs(output_dir, exist_ok=True)
            destination_file_name = os.path.join(output_dir, f"{arxiv_id}.pdf")
            blob.download_to_filename(destination_file_name)

            return PDFPaper(destination_file_name, title=title)
        except Exception as e:
            logger.error(f"Error fetching pdf paper: {e}")
            return None

    def download_arxiv_source(self, arxiv_id, output_dir) -> str:
        source_url = f"https://export.arxiv.org/e-print/{arxiv_id}"
        os.makedirs(output_dir, exist_ok=True)

        response = requests.get(source_url)
        response.raise_for_status()
        output_dir = os.path.join(output_dir, f"{arxiv_id}.tar.gz")
        with open(output_dir, "wb") as f:
            f.write(response.content)

        return output_dir

    def fetch_source_paper(
        self, paper_id, output_dir, title: Optional[str] = None
    ) -> LatexPaper:
        # TODO: parallel download, and set timeout for parsing
        try:
            # Download the source
            filename = self.download_arxiv_source(paper_id, output_dir)

            # extract the tar file
            datadir = re.sub(r"\.(tgz|tar\.gz)$", "", filename)
            self.extract_tar_file(filename, datadir)

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
        with tempfile.TemporaryDirectory() as tmpdirname:
            paper = self.fetch_source_paper(paper_id, tmpdirname, title)
            if paper is None:
                paper = self.fetch_pdf_paper(paper_id, tmpdirname, title)

        assert paper, "Couldn't fetch paper."
        return paper


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


class LocalPaperCache(DBCache):
    def __init__(self, limit: int = 2):
        super().__init__(limit)
        self.db: Dict[str, Dict[str, Union[PaperDataDict, datetime]]] = {}

    def __setitem__(self, paper_id: str, paper: PaperData):
        self.db[paper_id] = {"paper": paper.dump(), "timestamp": datetime.now()}
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


class FirestorePaperCache(DBCache):
    def __init__(self, collection_name: str = "papers", limit: int = 10000):
        super().__init__(limit)
        self.db: g_firestore.Client = firestore.client()
        self.collection_name = collection_name

    def __setitem__(self, paper_id: str, paper: PaperData):
        with self.db.transaction():
            doc_ref = self.db.collection(self.collection_name).document(paper_id)
            doc_ref.set(
                {"paper": paper.dump(), "timestamp": g_firestore.SERVER_TIMESTAMP}
            )

    def __getitem__(self, paper_id: str) -> Optional[PaperData]:
        doc_ref = self.db.collection(self.collection_name).document(paper_id)
        doc = doc_ref.get()
        if doc.exists:
            # TODO: Should I update the timestamp on every get
            # doc_ref.update({"timestamp": g_firestore.SERVER_TIMESTAMP})
            data = doc.to_dict()
            if "paper" in data:
                return PaperData.load(data["paper"])

        return None

    def lru_delete(self) -> int:
        # Get the count of documents in the collection
        results = self.db.collection(self.collection_name).count(alias="all").get()
        docs_count = results[0][0].value if results else 0

        # Calculate the number of documents to delete
        num_to_delete = max(0, docs_count - self.limit)

        if num_to_delete > 0:
            # Query for the oldest documents, limited to the number to delete
            query = (
                self.db.collection(self.collection_name)
                .order_by("timestamp")
                .limit(num_to_delete)
            )

            for doc in query.stream():
                doc.reference.delete()

        return num_to_delete
