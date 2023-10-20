import logging
import os
import re
from typing import List, Optional, Tuple

from pdfminer.high_level import extract_text
from pdfminer.pdfdocument import PDFDocument, decode_text
from pdfminer.pdfparser import PDFParser
from xplorer.paper import Paper, Section

logger = logging.getLogger(__name__)


class PDFPaper(Paper):
    def build(self, filename) -> Section:
        assert filename.endswith(".pdf") and os.path.isfile(
            filename
        ), "Invalid PDF file"

        with open(filename, "rb") as f:
            content = extract_text(f)
            parser = PDFParser(f)
            doc = PDFDocument(parser)
            self.title = self.title or self.get_title(doc)
            tree = Section(self.title, content, [])

            if doc.is_extractable:
                try:
                    outline = [
                        (level, self._clean_title(title))
                        for level, title, *_ in doc.get_outlines()
                    ]
                    tree.subsections = self.unflatten_sections(content, outline)
                except Exception as e:
                    logger.error("Error parsing PDF: " + str(e))
            else:
                logger.warning("PDF is not extractable.")

        return tree

    def build_bibliography(self):
        return {}

    def _clean_title(self, title):
        return re.sub(r"^\s*(?:\d+(\.\d*)*\.?|[a-zA-Z\d\.]+\s+)\s*", "", title).strip()

    def _try_fetch_content(
        self, text_group, start: str, end: str = None
    ) -> Optional[str]:
        pattern = rf"(?:^|\n)\s*(?:[A-Z\d\.]+\s*)?(?:\d+(?:\.\d*)*\s*)?{re.escape(start)}\s*\n+([\s\S]+?)"
        if end is not None:
            pattern += rf"\n+\s*(?:[A-Z\d\.]+\s*)?(?:\d+(?:\.\d*)*\s*)?{re.escape(end)}"
        else:
            pattern += r"$"

        match = re.search(pattern, text_group, re.DOTALL | re.IGNORECASE)

        if match:
            return match.group(1)

    def unflatten_sections(
        self, text: str, section_numbers: List[Tuple[str, str]]
    ) -> List[Section]:

        sections = []
        i = 0
        while i < len(section_numbers):
            level, title = section_numbers[i]

            # if there are subsections, then recursively create those
            # otherwise just append the section to the subsections list
            sub_numbers = []
            for l, t in section_numbers[i + 1 :]:
                if l == level:
                    break
                elif l > level:
                    sub_numbers.append((l, t))
            i += len(sub_numbers) + 1
            next_section = section_numbers[i][1] if i < len(section_numbers) else None
            body_text = self._try_fetch_content(text, title, next_section)
            if body_text:
                subsections = self.unflatten_sections(body_text, sub_numbers)
                section = Section(title.strip(), body_text, subsections)
                sections.append(section)

        return sections

    def get_title(self, doc: PDFDocument):
        title = doc.info[0]["Title"]
        if title:
            return decode_text(title)
