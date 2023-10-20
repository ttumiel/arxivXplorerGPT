import json
import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Tuple, Union

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
        # unique_content = unique_content.replace(subsection.content, "")
        pattern = rf"{re.escape(subsection.title)}.*?{re.escape(subsection.content)}"
        unique_content = re.sub(pattern, "", unique_content, flags=re.S)

    return unique_content


@dataclass
class Section:
    title: str
    content: str
    subsections: Optional[List["Section"]] = None

    @property
    def num_words(self):
        return len(self.content.split())

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
        return cls(data["title"], data["content"], subsections)


class Paper(ABC):
    tree: Section
    bibliography: Dict[str, str]
    abstract: str
    title: str
    methods: Dict[str, bool]
    store: VectorStore = None

    def __init__(self, filename, title=None, abstract=None):
        self.title = title
        self.tree = self.build(filename)
        self.methods = {"read_content": True, "table_of_contents": bool(self.sections)}

        self.bibliography = self.build_bibliography()
        self.methods["get_citation"] = bool(self.bibliography)

        self.abstract = abstract
        self.methods["read_abstract"] = bool(self.abstract)
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

        def chunk_section(section: Section, section_id: str = ""):
            unique_content = get_unique_content(section)
            for c in chunk(unique_content, chunk_size, overlap, min_len):
                chunks.append(f"{section_id} {section.title}\n{c}")

            if section.subsections:
                for i, subsection in enumerate(section.subsections, start=1):
                    chunk_section(subsection, section_id + f"{i}.")

        chunk_section(self.tree)
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
        return "\n".join(self.section_contents(self.tree.subsections))

    @property
    def has_bibliography(self):
        return self.methods["get_citation"]

    def section_contents(self, sections: Section, level: int = 0):
        """
        Generate a table of contents from a list of sections.

        Each section is represented as a dictionary with keys 'title', 'content',
        and 'subsections', where 'subsections' is a list of subsections in the
        same format.

        Returns:
            List of strings, where each string represents a
            line in the table of contents.
        """
        contents = []

        for i, section in enumerate(sections, start=1):
            title = section.title
            indent = "  " * level
            contents.append(f"{indent}{i}. {title} ({section.num_words} words)")

            # Recursively generate the table of contents for the subsections
            if section.subsections:
                subsection_contents = self.section_contents(
                    section.subsections, level=level + 1
                )
                contents.extend(subsection_contents)

        return contents

    def __repr__(self):
        return self.title + "\n" + self.table_of_contents

    def dumps(self) -> str:
        return {
            "tree": json.dumps(asdict(self.tree)),
            "bibliography": json.dumps(self.bibliography),
            "abstract": self.abstract,
            "title": self.title,
            "store": self.store.dump() if self.store else None,
        }

    @classmethod
    def loads(cls, data):
        class JSONPaper(cls):
            def __init__(self):
                super().__init__(None, data["title"], data["abstract"])
                if data["store"] is not None:
                    self.store = VectorStore.load(data["store"])

            def build(self, filename=None):
                return Section.from_dict(json.loads(data["tree"]))

            def build_bibliography(self) -> Dict[str, str]:
                return json.loads(data["bibliography"])

        return JSONPaper()
