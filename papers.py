import re
from dataclasses import dataclass
from typing import List, Optional

import texttable
from plasTeX import DOM, TeX
from pylatexenc.latex2text import (
    LatexNodes2Text,
    MacroTextSpec,
    get_default_latex_context_db,
)


@dataclass
class Section:
    title: str
    content: str
    subsections: Optional[List["Section"]] = None


def handle_cite(node, l2tobj: LatexNodes2Text):
    citation_key = l2tobj.nodelist_to_text(node.nodeargd.argnlist)
    return f"<cit. {citation_key}>"


def handle_includegraphics(node):
    return "<image>"


class Paper:
    def __init__(self, filename):
        assert filename.endswith(".tex") and os.path.isfile(filename)

        l2t_context_db = get_default_latex_context_db()
        l2t_context_db.add_context_category(
            "custom",
            prepend=True,
            macros=[
                MacroTextSpec("cite", simplify_repl=handle_cite),
                MacroTextSpec("citep", simplify_repl=handle_cite),
                MacroTextSpec("includegraphics", simplify_repl=handle_includegraphics),
            ],
        )
        self.l2t = LatexNodes2Text(latex_context=l2t_context_db)

        tex = TeX.TeX(file=filename)
        self.tex_doc = tex.parse()
        self.tree = Section(
            title=self.title,
            content=self.to_text(self.tex_doc),
            subsections=self.extract_nodes(),
        )

    def table_of_contents(self, sections, level=0):
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
            contents.append(f"{indent}{i}. {title}")

            # Recursively generate the table of contents for the subsections
            if section.subsections:
                subsection_contents = self.table_of_contents(
                    section.subsections, level=level + 1
                )
                contents.extend(subsection_contents)

        return contents

    def bibliography(self):
        return {
            bibitem.id: bibitem.textContent.strip()
            for bibitem in self.tex_doc.getElementsByTagName("bibitem")
        }

    @property
    def title(self):
        title = self.tex_doc.userdata.get("title", None)
        if title is None:
            return "No Title"
        return title.textContent

    @property
    def sections(self):
        return self.tree.subsections

    @property
    def subsections(self):
        return [sub for section in self.tree.subsections for sub in section.subsections]

    @property
    def content(self):
        return self.tree.content

    @property
    def toc(self):
        return "\n".join(self.table_of_contents(self.tree.subsections))

    def __getitem__(self, key: int):
        return self.tree.subsections[key]

    def __repr__(self):
        return "\n".join(self.table_of_contents([self.tree]))

    def encode(self, latex: str):
        try:
            return self.l2t.latex_to_text(latex)
        except Exception:
            return latex

    def clean(self, text: str):
        result = text.strip()
        result = re.sub(r"[ \t]*([.,;:!?])[ \t]+", r"\1 ", result)
        return result

    def to_text(self, tex_doc: TeX.TeXDocument):
        """Get the text content of the current node"""
        try:
            output = ""
            for item in tex_doc:
                name = item.nodeName
                if name.endswith("section"):
                    title = item.attributes["title"].textContent.strip()
                    underline = (
                        ("\n" + ("=" if name == "section" else "-") * len(title))
                        if "subsub" not in name
                        else ""
                    )
                    value = "\n\n" + title + underline + "\n" + self.to_text(item)
                elif name == "thebibliography":
                    value = "\n\nReferences\n" + "=" * 10 + "\n" + self.to_text(item)
                elif name == "table":
                    try:
                        value = "\n\n" + self.parse_table(item.source) + "\n\n"
                    except:
                        value = self.to_text(item)
                elif name in ("equation", "math", "displaymath"):
                    value = item.source
                elif item.hasChildNodes():
                    value = self.to_text(item)
                else:
                    value = item.source

                if item.attributes and not name.endswith("section"):
                    title = item.attributes.get("title", None)
                    if title:
                        value = title.textContent + " " + value

                output += self.encode(value)
        except Exception as e:
            print("ERROR", e)
            return tex_doc.textContent

        return output

    def node_text(self, node):
        """Get the text content of the current node"""
        if isinstance(node, str):
            return node

        output = ""
        for item in node:
            if item.nodeType == DOM.Node.TEXT_NODE:
                output += item.textContent
            else:
                output += self.encode(item.source)

        # TODO: do I want to use the strip inside the clean here?
        return self.clean(output)

    def parse_table(self, latex_src: DOM.Node):
        """
        Parse a LaTeX table, duplicating multicolumn cells, and convert to pretty printed table.

        :param table_node: LaTeX table node.
        :return: Pretty printed table as a string.
        """
        # Remove LaTeX formatting that can't be represented in markdown
        # latex_src = table_node.source
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

    def extract_nodes(self) -> List[Section]:
        """
        Iterate through a latex doc, generating a tree
        of sections and subsections, up to `levels` depth..
        """
        sections = self.tex_doc.getElementsByTagName("section")
        return [
            Section(
                section.attributes["title"].textContent,
                self.clean(self.to_text(section)),
                [
                    Section(
                        subsection.attributes["title"].textContent,
                        self.clean(self.to_text(subsection)),
                    )
                    for subsection in section.getElementsByTagName("subsection")
                ],
            )
            for section in sections
        ]
