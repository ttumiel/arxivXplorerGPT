import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Tuple, TypedDict, Union

import regex as re

from .vector_store import VectorStore


def chunk(text: str, chunksize: int = 250, overlap: int = 15, min_len: int = 50):
    """String chunking method that splits strings with chunksize words
    with overlap words shared at the start and end."""

    if len(text.split()) <= chunksize + min_len:
        return [text]

    chunks = []
    start = 0
    end = 1
    num_words = 0
    while end < len(text):
        if text[end] in (" ", "\n") and end - start > 1:
            num_words += 1
            if num_words >= chunksize:
                next_chunk = text[start:end]
                if len(chunks) > 0:
                    chunks[-1] += "..."
                    next_chunk = "... " + next_chunk

                chunks.append(next_chunk)
                chr_overlap = (
                    sum(len(c) for c in next_chunk.split()[-overlap:]) - 1 + overlap
                )
                start = end - chr_overlap
                end = start
                num_words = 0
        end += 1

    if num_words < min_len:
        chunks[-1] += text[start + chr_overlap :]
    else:
        chunks[-1] += "..."
        chunks.append("... " + text[start:end])
    return chunks


def get_unique_content(section: "Section") -> str:
    if not section.subsections:
        return section.content

    unique_content = section.content
    for subsection in section.subsections:
        pattern = rf"{re.escape(subsection.title)}.*?{re.escape(subsection.content)}"
        unique_content = re.sub(pattern, "", unique_content, flags=re.S)

    return unique_content


class FigureData(TypedDict, total=False):
    label: str
    url: List[str]
    path: List[str]
    caption: Optional[str]
    section: Optional[str]
    size: Optional[List[Dict[str, float]]]


@dataclass
class Section:
    title: str
    content: str
    subsections: Optional[List["Section"]] = None
    figures: Optional[Dict[str, FigureData]] = None

    @property
    def num_words(self):
        return len(self.content.split())

    @property
    def num_figures(self):
        return len(self.figures) if self.figures else 0

    @property
    def chunks(self):
        return chunk(self.content)

    def __repr__(self) -> str:
        return self.title + "\n" + self.content

    @classmethod
    def from_dict(cls, data):
        subsections = (
            [cls.from_dict(d) for d in data["subsections"]]
            if data.get("subsections", None)
            else []
        )
        return cls(
            data["title"], data["content"], subsections, data.get("figures", None)
        )


class Paper(ABC):
    tree: Section
    bibliography: Dict[str, str]
    title: str
    methods: Dict[str, bool]
    store: VectorStore = None
    figures: Dict[str, FigureData] = None

    def __init__(self, filename, title=None):
        self.title = title
        self.tree = self.build(filename)
        self.methods = {"read_content": True, "table_of_contents": bool(self.sections)}
        self.figures = self.collect_figures()

        self.bibliography = self.build_bibliography()
        self.methods["get_citation"] = bool(self.bibliography)
        self.title = self.title or "Unknown Title."

    @abstractmethod
    def build(self, filename) -> Section:
        "Build and return the paper tree and available methods"
        raise NotImplementedError

    @abstractmethod
    def build_bibliography(self) -> Dict[str, str]:
        raise NotImplementedError

    def chunk_tree(
        self, chunk_size: int = 250, overlap: int = 15, min_len: int = 50
    ) -> List[str]:
        chunks = []
        for title, section in self.flatten_sections(
            self.tree, show_images=False, show_words=False
        ):
            unique_content = get_unique_content(section)
            for c in chunk(unique_content, chunk_size, overlap, min_len):
                chunks.append(f"{title.strip()}\n{c}")

        return chunks

    def chunk_search(self, query: str, count: int = 3):
        "Search for a particular chunk based on a text query"
        if self.store is None:
            chunks = self.chunk_tree()
            self.store = VectorStore()
            self.store.embed(chunks)

        return self.store.search(query, count)

    def get_citation(self, key):
        return self.bibliography.get(key, "Unknown citation.")

    def __getitem__(self, key: Union[int, Tuple[int]]) -> Section:
        # TODO: add assert checks
        # TODO: change to 1 indexing
        if isinstance(key, int):
            return self.tree.subsections[key]
        else:
            sections = self.tree.subsections
            for i in key:
                section = sections[i]
                sections = section.subsections
            return section

    @property
    def content(self):
        return self.tree.content

    @property
    def sections(self):
        return self.tree.subsections

    @property
    def table_of_contents(self):
        return "\n".join(
            title for title, _ in self.flatten_sections(self.tree.subsections)
        )

    @property
    def can_read_citation(self):
        return self.methods["get_citation"]

    def collect_figures(self) -> Dict[str, FigureData]:
        figures = {}
        for title, section in self.flatten_sections(
            self.tree.subsections, show_images=False, show_words=False
        ):
            if section.figures:
                for im in section.figures.values():
                    im["section"] = title.strip()
                figures.update(section.figures)

        return figures

    def flatten_sections(
        self,
        sections: Section,
        level: int = 0,
        prefix: str = "",
        show_images: bool = True,
        show_words: bool = True,
    ):
        """
        Generate a table of contents from a list of sections.

        Each section is represented as a dictionary with keys 'title', 'content',
        and 'subsections', where 'subsections' is a list of subsections in the
        same format.

        Yields:
            String line from the table of contents.
        """
        if isinstance(sections, Section):
            yield sections.title, sections
            sections = sections.subsections

        for i, section in enumerate(sections, start=1):
            section_number = f"{prefix}{i}."
            indent = "  " * level
            info = []

            if show_words:
                info.append(f"{section.num_words} words")

            n_images = section.num_figures
            if show_images and n_images:
                im_info = f"{n_images} figure"
                if n_images > 1:
                    im_info += "s"
                info.append(im_info)

            info = ", ".join(info)
            if info:
                info = " (" + info + ")"

            yield f"{indent}{section_number} {section.title}{info}", section

            # Recursively generate the table of contents for the subsections
            if section.subsections:
                yield from self.flatten_sections(
                    section.subsections,
                    level=level + 1,
                    prefix=section_number,
                    show_images=show_images,
                    show_words=show_words,
                )

    def __repr__(self):
        return self.title + "\n" + self.table_of_contents

    def dumps(self, vectors: bool = True) -> dict:
        data = {
            "tree": json.dumps(asdict(self.tree)),
            "bibliography": json.dumps(self.bibliography),
            "title": self.title,
        }
        if vectors:
            data["store"] = (self.store.dump() if self.store else None,)

        if self.figures:
            data["figures"] = json.dumps(self.figures)

        return data

    @classmethod
    def loads(cls, data: dict):
        class JSONPaper(cls):
            def __init__(self):
                super().__init__(None, data["title"])
                if "store" in data and data["store"] is not None:
                    self.store = VectorStore.load(data["store"])

                if "figures" in data:
                    self.figures = json.loads(data["figures"])

            def build(self, filename=None):
                return Section.from_dict(json.loads(data["tree"]))

            def build_bibliography(self) -> Dict[str, str]:
                return json.loads(data["bibliography"])

        return JSONPaper()
