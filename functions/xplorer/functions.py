import logging
import re
import traceback
from enum import Enum
from functools import wraps
from typing import Dict, List, Optional, Union
from urllib.parse import urlencode

import arxiv
import requests
from chat2func import json_schema
from chat2func.server import FunctionServer
from xplorer.db import PaperCache, PaperData, PaperDataDict

logger = logging.getLogger(__name__)


class SearchMethod(Enum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    SIMILARITY = "similarity"


def error_logger(func):
    @wraps(func)
    def inner(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {func.__name__}:\n{traceback.format_exc()}")
            return {"Error": str(e)}

    return inner


class ArxivXplorerAPI:
    ARXIV_URL = re.compile(
        r"https?:\/\/arxiv\.org\/(?:abs|pdf)\/((?:[\w.-]+\/[\d]+)|([\d]+\.[\d]+))(?:v\d+)?"
    )
    ARXIV_ID = re.compile(r"((?:[\w.-]+\/[\d]+)|([\d]+\.[\d]+))(?:v\d+)?")
    URLS = {
        SearchMethod.SIMILARITY: "https://us-west1-semanticxplorer.cloudfunctions.net/semantic-xplorer-db-similarity",
        SearchMethod.SEMANTIC: "https://us-west1-semanticxplorer.cloudfunctions.net/semantic-xplorer-db",
    }

    def __init__(self):
        self.cache = PaperCache()

    def __getitem__(self, paper_id: str) -> PaperData:
        paper_id = self.clean_arxiv_id(paper_id)
        return self.cache[paper_id]

    def __setitem__(self, paper_id: str, paper_data: PaperData):
        paper_id = self.clean_arxiv_id(paper_id)
        self.cache[paper_id] = paper_data

    def build(self, path: str, export_source: bool = False):
        server = FunctionServer(
            {
                "search": self.search,
                "read_paper_metadata": self.read_paper_metadata,
                # "read_full_paper": self.read_full_paper,
                "read_section": self.read_section,
                "read_citation": self.read_citation,
                "chunk_search": self.chunk_search,
            }
        )
        server.export(path, export_source=export_source)

    @json_schema(full_docstring=True)
    @error_logger
    def search(
        self,
        query: str,
        count: int = 5,
        page: int = 1,
        year: int = None,
        method: SearchMethod = SearchMethod.SEMANTIC,
    ) -> List[PaperDataDict]:
        """Searches for arxiv articles using the user's query.

        Semantic search is preferred unless you want an exact keyword, or you want an exact paper.
        Similarity search will find similar results given an arxiv paper ID or URL.

        Args:
            query (str): The user's query.
            count (int): The number of results to return. Defaults to 5.
            page (int): Pagination index. Defaults to 1.
            year (int): The year to filter results by. Defaults to None, for any year.
            method (SearchMethod): The search method to use. Defaults to semantic search.
        """
        if method == SearchMethod.KEYWORD:
            return self._arxiv_search(query, count, page)
        else:
            return self._xplorer_search(query, count, page, year)

    @json_schema
    @error_logger
    def chunk_search(
        self, paper_id: str, query: str, count: int = 3, page: int = 1
    ) -> List[str]:
        """Perform semantic search for a query across 250 word chunks of a paper's sections.

        Args:
            paper_id (str): arxiv ID.
            query (str): The user's query.
            count (int): The number of results to return. Defaults to 3.
            page (int): Pagination index. Defaults to 1.
        """
        paper_data = self[paper_id]
        paper = paper_data.paper
        should_update = paper.store is None
        # TODO: implement pagination
        result = paper.chunk_search(query, count)
        if should_update:
            self[paper_id] = paper_data
        return result

    @json_schema(full_docstring=True)
    @error_logger
    def read_paper_metadata(self, paper_id: str, show_abstract=False) -> PaperDataDict:
        """Read the metadata of a paper, where available. Including the paper's id,
        title, date, authors, abstract, table_of_contents, has_bibliography.

        Args:
            paper_id (str): arxiv ID.
            show_abstract (bool): Include the abstract in the response. Defaults to False.

        Returns: PaperData(
            id: str,
            title: str,
            date: str,
            authors: Optional[str] = None,
            abstract: Optional[str] = None,
            table_of_contents: Optional[str] = None,
            has_bibliography: Optional[bool] = False,
        )
        """
        return self[paper_id].to_dict(show_abstract=show_abstract)

    @json_schema(full_docstring=True)
    @error_logger
    def read_full_paper(self, paper_id: str) -> str:
        """Read an entire paper's contents.

        Warning: This method returns the entire paper's content as a str, which may
        overflow the context window. Use carefully.
        """
        return self[paper_id].paper.content

    @json_schema
    @error_logger
    def read_section(self, paper_id: str, section_id: Union[int, List[int]]) -> str:
        """Read a specific section from the table of contents of a paper.

        Args:
            paper_id (str): arxiv ID.
            section_id (Union[int, List[int]]): 1-indexed section ID, or list of subsection ids.

        Returns: Section(
            title: str,
            content: str,
            subsections: Optional[List["Section"]] = None,
        )
        """
        # Zero-indexed inside paper
        if isinstance(section_id, int):
            section_id -= 1
        else:
            section_id = [i - 1 for i in section_id]

        return str(self[paper_id].paper[section_id])

    @json_schema
    @error_logger
    def read_citation(self, paper_id: str, citation: str) -> str:
        """Lookup a particular citation id of a paper, if paper_metadata.has_bibliography == True.

        Args:
            paper_id (str): arxiv ID.
            citation (str): The citation ID to lookup. e.g. `demo` from the citation `<cit. demo>`
        """
        # TODO: some of the citations look mangled: <cit. J>onasFaceNet2017
        paper = self[paper_id].paper
        assert paper.has_bibliography, "Paper does not support getting citations."
        return paper.get_citation(citation)

    def parse_query_string(
        self, query: str, count: int, page: int = 1, year: Optional[int] = None
    ) -> str:
        q = {"query": query, "count": count}
        if page > 1:
            q["p"] = page

        if year is not None:
            q["y"] = year

        return "?" + urlencode(q)

    def _filter_papers(self, papers: List[Dict], skip_first=False) -> List[PaperData]:
        "Filter raw json arxiv xplorer response into PaperData"
        filtered_papers = [
            PaperData(
                paper["id"],
                paper["metadata"]["title"],
                paper["metadata"]["date"],
                paper["metadata"]["short_author"],
                paper["metadata"]["abstract"],
            ).to_dict()
            for paper in papers
        ]
        if skip_first:
            filtered_papers = filtered_papers[1:]
        return filtered_papers

    def _xplorer_search(
        self, query: str, count: int, page: int = 1, year: int = None
    ) -> List[PaperData]:
        "Searches arxiv xplorer for papers."
        sim_paper_id = self.clean_arxiv_id(query)
        is_sim = bool(sim_paper_id)
        if is_sim:
            query = f"https://arxiv.org/abs/{sim_paper_id}"
            url = self.URLS[SearchMethod.SIMILARITY]
            count += 1
        else:
            url = self.URLS[SearchMethod.SEMANTIC]

        url += self.parse_query_string(query, count, page, year)
        resp = requests.get(url)
        if resp.status_code != 200:
            resp.raise_for_status()
        return self._filter_papers(resp.json(), skip_first=is_sim)

    def _arxiv_search(self, query: str, count: int, page: int = 1) -> List[PaperData]:
        "Search arxiv using arxiv's keyword search."
        # TODO: fix page
        """Searches for arxiv articles that contain the user's keyword query."""
        search = arxiv.Search(
            query=query, max_results=count, sort_by=arxiv.SortCriterion.Relevance
        )
        return [
            PaperData(
                self.clean_arxiv_id(r.get_short_id()),
                r.title,
                r.published.strftime("%Y-%m-%d"),
                f"{r.authors[0]}{', et al.' if len(r.authors) > 1 else ''}",
                r.summary,
            ).to_dict()
            for r in search.results()
        ]

    def clean_arxiv_id(self, input_str: str) -> Optional[str]:
        url_match = self.ARXIV_URL.search(input_str)
        if url_match:
            return url_match.group(1)

        # If input is already an arXiv ID
        id_match = self.ARXIV_ID.fullmatch(input_str)
        if id_match:
            return id_match.group(1)

        return None


# api = ArxivXplorerAPI()
# server = FunctionServer(
#     {
#         "search": api.search,
#         "read_paper_metadata": api.read_paper_metadata,
#         "read_full_paper": api.read_full_paper,
#         "read_section": api.read_section,
#         "read_citation": api.read_citation,
#         "chunk_search": api.chunk_search,
#     }
# )
# server.run(debug=True)

# import json
# server.app.config["TESTING"] = True
# client = server.app.test_client()

# paper_id = "1706.03762v2"

# rv = client.post("/read_section", json={"paper_id": paper_id, "section_id": [6,2]})
# print(json.loads(rv.data))
