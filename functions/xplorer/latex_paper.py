import logging
import os
import re
import traceback
from typing import Dict, List, Tuple

import texttable
from plasTeX import DOM, TeX
from xplorer.latex import TeXParser, TextEncoder
from xplorer.paper import FigureData, Paper, Section

logger = logging.getLogger(__name__)


class LatexPaper(Paper):
    def build(self, filename) -> Section:
        assert filename.endswith(".tex") and os.path.isfile(filename)
        self.encode = TextEncoder()
        self.tex_doc = TeXParser(filename).parse()
        self.title = self.title or self.get_title(self.tex_doc)
        tree = self.build_tree()
        return tree

    def build_bibliography(self) -> Dict[str, str]:
        return {
            bibitem.id: bibitem.textContent.strip()
            for bibitem in self.tex_doc.getElementsByTagName("bibitem")
        }

    def get_title(self, tex_doc):
        title = tex_doc.userdata.get("title", None)
        if title is not None:
            return title.textContent

    def clean(self, text: str):
        result = text.strip()
        result = re.sub(r"[ \t]*([.,;:!?])[ \t]+", r"\1 ", result)
        return result

    def build_tree(self):
        content, subsections, images = self.build_content(self.tex_doc)
        main_section = Section(
            title=self.title,
            content=content,
            subsections=subsections,
            figures=images,
        )

        return main_section

    def build_content(
        self, tex_doc: TeX.TeXDocument
    ) -> Tuple[str, List[Section], Dict[str, FigureData]]:
        """Get the text content of the current node"""

        content = ""
        subsections = []
        images = {}
        for item in tex_doc:
            try:
                name = item.nodeName

                if name.endswith("section"):
                    title = item.attributes["title"].textContent.strip()
                    underline = (
                        ("\n" + ("=" if name == "section" else "-") * len(title))
                        if "subsub" not in name
                        else ""
                    )
                    subcontent, subsubsections, inner_images = self.build_content(item)
                    value = "\n\n" + title + underline + "\n" + subcontent
                    subsections.append(
                        Section(title, subcontent, subsubsections, inner_images)
                    )

                elif name == "thebibliography":
                    # TODO: bibliography should be another section, outside of the last section.
                    bibcontent, _, inner_images = self.build_content(item)
                    value = "\n\nReferences\n" + "=" * 10 + "\n" + bibcontent
                    subsections.append(
                        Section("References", bibcontent, figures=inner_images)
                    )

                elif name == "table":
                    try:
                        value = "\n\n" + self.parse_table(item.source) + "\n\n"
                    except Exception as e:
                        logger.error(f"Failed to parse table: {e}")
                        value = "\n\n" + item.source + "\n\n"
                    value = self.encode(value)

                elif name in (
                    "equation",
                    "equation*",
                    "math",
                    "displaymath",
                    "itemize",
                    "enumerate",
                    "bibitem",
                    "align",
                    "align*",
                ):
                    value = self.encode(item.source)

                elif name in ("figure", "figure*", "includeimage"):
                    if getattr(item, "label", None) is not None:
                        value = f"<figure. {item.label}"
                        data = FigureData(
                            label=item.label, path=item.path, size=item.size
                        )
                        caption = getattr(item, "caption", "")
                        caption = self.encode(caption)
                        if caption:
                            data["caption"] = caption
                            value += " - " + caption

                        value += ">"
                        if item.label:
                            images[item.label] = data
                    else:
                        value = ""

                elif item.hasChildNodes():
                    value, innersubsections, child_images = self.build_content(item)
                    images.update(child_images)
                    subsections.extend(innersubsections)

                else:
                    value = self.encode(item.source)

                if item.attributes and not name.endswith("section"):
                    title = item.attributes.get("title", None)
                    if title:
                        value = title.textContent + " " + value

                content += value
            except Exception as e:
                logger.error(
                    "Error parsing latex: "
                    + str(e)
                    + "\n"
                    + traceback.format_exc()
                    + "\n"
                    + item.source
                )
                content += item.textContent

        return content, subsections, images

    def parse_table(self, latex_src: DOM.Node):
        """
        Parse a LaTeX table, duplicating multicolumn cells, and convert to pretty printed table.

        :param table_node: LaTeX table node.
        :return: Pretty printed table as a string.
        """
        table_content = re.search(
            r".*\\begin{tabular}{[^}]*}(.*?)\\end{tabular}.*",
            latex_src,
            flags=re.DOTALL,
        )
        assert table_content, "No table content found."
        table_content = table_content.group(1).strip()

        rows = re.split(r"\\\\", table_content)
        data = []
        for i, row in enumerate(rows):
            cols = []
            split_cols = re.split(r"(?<!\\)&", row)
            if len(split_cols) == 1 and i == len(rows) - 1:
                continue

            for col in split_cols:
                multicolumn_match = re.match(
                    r".*\\multicolumn{(\d+)}{.*}{(.*)}.*", col, flags=re.DOTALL
                )
                if multicolumn_match:
                    n_columns = int(multicolumn_match.group(1))
                    cell_content = multicolumn_match.group(2)
                    cols.extend([cell_content] * n_columns)
                else:
                    cols.append(col)
            data.append(cols)

        for i, row in enumerate(data):
            for j in range(len(row)):
                multirow_match = re.match(
                    r".*\\multirow{(\d+)}{.*}{(.*)}.*", row[j], flags=re.DOTALL
                )
                if multirow_match:
                    n_rows = int(multirow_match.group(1))
                    cell_content = multirow_match.group(2)
                    for k in range(n_rows):
                        data[i + k][j] = cell_content

                row[j] = self.clean(self.encode(data[i][j]))

        # Create texttable
        table = texttable.Texttable(
            max_width=min(
                140, max((sum(len(c) for c in row) + len(row) * 2) for row in data)
            )
        )
        alignment = ["c"] * len(data[0])
        align_match = re.search(r"\\begin{tabular}{([^}]*)}", latex_src)
        if align_match:
            tab_alignment = [v for v in align_match.group(1) if v in "lcr"]
            if len(alignment) == len(data[0]):
                alignment = tab_alignment

        table.set_cols_align(alignment)
        table.set_deco(texttable.Texttable.HEADER)
        table.add_rows(data)
        output = table.draw()

        output += f"\nTable"
        caption_match = re.search(r"\\caption{([^}]*)}", latex_src)
        if caption_match:
            output += ": " + caption_match.group(1)

        return output


def guess_main_tex_file(directory):
    candidates = []

    for filename in os.listdir(directory):
        if not filename.endswith(".tex"):
            continue

        with open(os.path.join(directory, filename), "r") as file:
            contents = file.read()

        if re.search(r"\\documentclass", contents) or (
            re.search(r"\\begin{document}", contents)
            and re.search(r"\\end{document}", contents)
        ):
            candidates.append(filename)

    if not candidates:
        if os.path.exists(os.path.join(directory, "main.tex")):
            logger.info("Guessing main.tex")
            return "main.tex"

        candidates = os.listdir(directory)

    # If there are multiple candidates, guess the largest file is the main one
    largest_candidate = max(
        candidates,
        key=lambda filename: os.path.getsize(os.path.join(directory, filename)),
    )
    logger.info(f"Guessing largest file: {largest_candidate}")
    return os.path.join(directory, largest_candidate)
