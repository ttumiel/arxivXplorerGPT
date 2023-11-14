import logging
import os
import re
from typing import List, Optional, Tuple

import fitz
from xplorer.paper import FigureData, Paper, Section

logger = logging.getLogger(__name__)


class PDFPaper(Paper):
    def build(self, filename) -> Section:
        assert filename.endswith(".pdf") and os.path.isfile(
            filename
        ), "Invalid PDF file"

        doc = fitz.open(filename)
        self.title = self.title or self.get_title(doc)
        content = ""
        images = {}
        for page_num, page in enumerate(doc):
            content += page.get_text()

            # Extract images
            page_images = {}
            try:
                image_list = page.get_images(full=True)
                for i, img in enumerate(image_list, start=1):
                    xref = img[0]
                    label = f"fig_{xref}_page{page_num}_{i}"
                    if label not in page_images:
                        page_images[label] = FigureData(label=label, path=[xref])

            except Exception as e:
                logger.error("Error extracting images: " + str(e))

            if page_images:
                images[page_num] = page_images

        tree = Section(self.title, content, [])

        try:
            outline = [
                (level, self._clean_title(title), page)
                for level, title, page in doc.get_toc()
            ]
            tree.subsections = self.unflatten_sections(content, outline, images)
            leftover_images = {}
            for page_images in images.values():
                leftover_images.update(page_images)
            tree.figures = leftover_images
        except Exception as e:
            logger.error("Error parsing PDF: " + str(e))

        return tree

    def build_bibliography(self):
        return {}

    def _clean_title(self, title):
        return re.sub(r"^\s*\d+(\.\d+)*\.\s*", "", title).strip()

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
        self, text: str, section_numbers: List[Tuple[str, str]], images: dict
    ) -> List[Section]:

        sections = []
        i = 0
        while i < len(section_numbers):
            level, title, page = section_numbers[i]

            # if there are subsections, then recursively create those
            # otherwise just append the section to the subsections list
            sub_numbers = []
            for l, t, p in section_numbers[i + 1 :]:
                if l == level:
                    break
                elif l > level:
                    sub_numbers.append((l, t, p))
            i += len(sub_numbers) + 1
            next_section = section_numbers[i][1] if i < len(section_numbers) else None
            body_text = self._try_fetch_content(text, title, next_section)
            section_images = images.pop(page, {})
            if body_text or section_images:
                subsections = self.unflatten_sections(body_text, sub_numbers, images)
                section = Section(title.strip(), body_text, subsections, section_images)
                sections.append(section)

        return sections

    def get_title(self, doc: fitz.Document):
        title = doc.metadata.get("title", None)
        if title:
            return title
