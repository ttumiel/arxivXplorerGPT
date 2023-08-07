from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List, Union, Tuple, Dict
import os
from pdfminer.high_level import extract_text
from pdfminer.pdfparser import PDFParser
from pdfminer.pdfdocument import PDFDocument, decode_text, dict_value
import re


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


class Paper(ABC):
    tree: Section
    bibliography: Dict[str, str]
    _title: Optional[str] = None

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
        return self._title if self._title else "No Title."

    @property
    def content(self):
        return self.tree.content

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
        return self.title + "\n" + self.toc


methods: Dict[str, bool] = {
    "table_of_contents": True,
    "get_citation": True,
    "get_section": True,
    "abstract": True,
    # Always available
    "content": True,
}


class PDFPaper(Paper):
    bibliography = {}

    def __init__(self, filename):
        assert filename.endswith(".pdf") and os.path.isfile(filename), "Invalid PDF file"

        with open(filename, 'rb') as f:
            content = extract_text(f)
            parser = PDFParser(f)
            doc = PDFDocument(parser)
            self._title = self.get_title(doc)
            self.tree = Section(self.title, content, [])

            if doc.is_extractable:
                try:
                    outline = [(level, self._clean_title(title)) for level, title, *_ in doc.get_outlines()]
                    body_text = self._fetch_content(content, self.title) if self._title else content
                    self.tree.subsections = self.unflatten_sections(body_text, outline)
                except Exception as e:
                    print("Error:", str(e))
                    raise e

    def _clean_title(self, title):
        return re.sub(r"^\d+(\.\d+)*\.?\s*", "", title).strip()

    def _try_fetch_content(self, text_group, start: str, end: str = None) -> Optional[str]:
        pattern = rf"[^\n]\s*(?:\d+(?:\.\d+)*\s*)?{re.escape(start)}\s*\n+([\s\S]+?)"
        if end is not None:
            pattern += rf"\n+\d+(?:\.\d+)*\s*{re.escape(end)}"
        else:
            pattern += r"$"

        match = re.search(pattern, text_group, re.DOTALL | re.IGNORECASE)

        if match:
            return match.group(1)

    def unflatten_sections(self, text: str, section_numbers: List[Tuple[str, str]]) -> List[Section]:

        sections = []
        i = 0
        while i < len(section_numbers):
            level, title = section_numbers[i]

            # if there are subsections, then recursively create those
            # otherwise just append the section to the subsections list
            sub_numbers = []
            for l, t in section_numbers[i + 1:]:
                if l == level:
                    break
                elif l > level:
                    sub_numbers.append((l, t))
            i += len(sub_numbers) + 1
            next_section = section_numbers[i][1] if i < len(section_numbers) else None
            body_text = self._try_fetch_content(text, title, next_section)
            if body_text is None:
                print(title, next_section)

            if body_text:
                subsections = self.unflatten_sections(body_text, sub_numbers)
                section = Section(title.strip(), body_text, subsections)
                sections.append(section)

        return sections

    def get_title(self, doc: PDFDocument):
        title = doc.info[0]['Title']
        if title:
            return decode_text(title)


def extract_pdf(pdf_file_path):
    with open(pdf_file_path, 'rb') as f:
        text = extract_text(f)
        parser = PDFParser(f)
        doc = PDFDocument(parser)

        # Ensure the document allows text extraction, if not, abort.
        if not doc.is_extractable:
            toc = None
        else:
            toc = []
            try:
                outlines = doc.get_outlines()
                for (level,title,dest,a,se) in outlines:
                    toc.append((level, title))
            except:
                toc = None

    return text, toc

paper = PDFPaper("/home/sara/Documents/semanticXplorer/xplorer-plugin/data/attention/1706.03762.pdf")
print(paper.table_of_contents)
print(paper[2,1,2])
