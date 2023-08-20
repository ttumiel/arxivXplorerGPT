import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple, Union


@dataclass
class Section:
    title: str
    content: str
    subsections: Optional[List["Section"]] = None

    @property
    def num_words(self):
        return len(self.content.split())

    def __repr__(self) -> str:
        return self.title + "\n" + self.content

    @classmethod
    def from_dict(cls, data):
        subsections = [cls.from_dict(d) for d in data['subsections']] if data.get('subsections', None) else []
        return cls(data['title'], data['content'], subsections)


class Paper(ABC):
    tree: Section
    bibliography: Dict[str, str]
    abstract: str
    original_title: Optional[str] = None
    methods: Dict[str, bool]

    def __init__(self, filename, title=None, abstract=None):
        self.tree = self.build(filename)
        self.original_title = title or self.build_title()
        self.methods = {"read_content": True, "table_of_contents": bool(self.sections)}

        self.bibliography = self.build_bibliography()
        self.methods['get_citation'] = bool(self.bibliography)

        self.abstract = abstract
        self.methods['read_abstract'] = bool(self.abstract)


    @abstractmethod
    def build(self, filename) -> Section:
        "Build and return the paper tree and available methods"
        raise NotImplementedError

    @abstractmethod
    def build_title(self) -> Optional[str]:
        raise NotImplementedError

    @abstractmethod
    def build_bibliography(self) -> Dict[str, str]:
        raise NotImplementedError

    def get_citation(self, key):
        return self.bibliography.get(key, "Unknown citation.")

    def __getitem__(self, key: Union[int, Tuple[int]]) -> Section:
        if isinstance(key, int):
            return self.tree.subsections[key]
        else:
            sections = self.tree.subsections
            for i in key:
                section = sections[i]
                sections = section.subsections
            return section

    @property
    def title(self):
        return self.original_title if self.original_title else "Unknown Title."

    @property
    def content(self):
        return self.tree.content

    @property
    def sections(self):
        return self.tree.subsections

    @property
    def table_of_contents(self):
        return "\n".join(self.section_contents(self.tree.subsections))

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
        return json.dumps(
            {
                "tree": asdict(self.tree),
                "bibliography": self.bibliography,
                "abstract": self.abstract,
                "original_title": self.original_title,
            }
        )

    @classmethod
    def loads(cls, data):
        data = json.loads(data)
        class JSONPaper(cls):
            def __init__(self):
                super().__init__(None, data['original_title'], data['abstract'])
            def build(self, filename=None):
                return Section.from_dict(data['tree'])
            def build_bibliography(self) -> Dict[str, str]:
                return data['bibliography']
            def build_title(self) -> str | None:
                return data['original_title']
        return JSONPaper()
