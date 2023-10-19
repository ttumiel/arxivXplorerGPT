import logging
import os
import re
import traceback
from typing import Dict, List, Tuple

import texttable
from plasTeX import DOM, Config, TeX, TeXDocument
from plasTeX.Logging import disableLogging
from pylatexenc.latex2text import (EnvironmentTextSpec, LatexNodes2Text,
                                   MacroTextSpec, get_default_latex_context_db)
from pylatexenc.latexwalker import LatexMacroNode
from xplorer.paper import Paper, Section

disableLogging()
logger = logging.getLogger(__name__)


def local_kpsewhich(self, name):
    "Locate the given file in the source directory and TEXINPUTS paths."
    try:
        srcDir = os.path.dirname(self.filename)
    except AttributeError:
        srcDir = '.'

    texinputs = os.environ.get("TEXINPUTS", '.').split(os.path.pathsep)
    search_paths = [srcDir] + texinputs

    # Search for the file in the source directory and TEXINPUTS
    for path in search_paths:
        if not path:
            continue

        # Check with suffix
        candidate_path = os.path.join(path, name)
        if os.path.exists(candidate_path):
            return os.path.abspath(candidate_path)

        # Check without suffix by matching any file that starts with the name
        for candidate in os.listdir(path):
            if candidate.startswith(name + "."):
                return os.path.abspath(os.path.join(path, candidate))

    raise FileNotFoundError(f"Could not find any file named: {name}")

# Monkey patch the method onto the Tex class
TeX.TeX.kpsewhich = local_kpsewhich


def handle_cite(node: LatexMacroNode, l2tobj: LatexNodes2Text):
    citation_key = l2tobj.nodelist_to_text(node.nodeargd.argnlist)
    return f"<cit. {citation_key}>"


def handle_includegraphics(node):
    return "<image>"


def handle_href(node: LatexMacroNode, l2tobj):
    return "[{}]({})".format(
        l2tobj.nodelist_to_text([node.nodeargd.argnlist[1]]),
        l2tobj.nodelist_to_text([node.nodeargd.argnlist[0]]),
    )


def handle_item(node: LatexMacroNode, l2tobj: LatexNodes2Text):
    return l2tobj.node_to_text(node.nodeoptarg) if node.nodeoptarg else "- "


class LatexPaper(Paper):
    def build(self, filename) -> Section:
        assert filename.endswith(".tex") and os.path.isfile(filename)

        l2t_context_db = get_default_latex_context_db()
        l2t_context_db.add_context_category(
            "custom",
            prepend=True,
            macros=[
                MacroTextSpec("cite", simplify_repl=handle_cite),
                MacroTextSpec("citep", simplify_repl=handle_cite),
                MacroTextSpec("includegraphics", simplify_repl=handle_includegraphics),
                MacroTextSpec("href", simplify_repl=handle_href),
                MacroTextSpec("url", simplify_repl="%s"),
                MacroTextSpec("item", simplify_repl=handle_item),
            ],
            environments=[
                EnvironmentTextSpec("enumerate", simplify_repl="\n%s"),
                EnvironmentTextSpec("exenumerate", simplify_repl="\n%s"),
                EnvironmentTextSpec("itemize", simplify_repl="\n%s"),
            ],
        )
        self.l2t = LatexNodes2Text(latex_context=l2t_context_db)

        config = Config.defaultConfig()
        config["general"]["load-tex-packages"] = False
        ownerDocument = TeXDocument(config=config)
        tex = TeX.TeX(file=filename, ownerDocument=ownerDocument)
        self.tex_doc = tex.parse()
        self._title = self.get_title(self.tex_doc)
        tree = self.build_tree()
        return tree

    def build_bibliography(self) -> Dict[str, str]:
        return {
            bibitem.id: bibitem.textContent.strip()
            for bibitem in self.tex_doc.getElementsByTagName("bibitem")
        }

    def build_title(self):
        return self._title

    def get_title(self, tex_doc):
        title = tex_doc.userdata.get("title", None)
        if title is not None:
            return title.textContent

    def encode(self, latex: str):
        try:
            return self.l2t.latex_to_text(latex)
        except Exception:
            return latex

    def clean(self, text: str):
        result = text.strip()
        result = re.sub(r"[ \t]*([.,;:!?])[ \t]+", r"\1 ", result)
        return result

    def build_tree(self):
        content, subsections = self.build_content(self.tex_doc)
        main_section = Section(
            title=self.title,
            content=content,
            subsections=subsections,
        )

        return main_section

    def build_content(self, tex_doc: TeX.TeXDocument) -> Tuple[str, List[Section]]:
        """Get the text content of the current node"""

        content = ""
        subsections = []
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
                    subcontent, subsubsections = self.build_content(item)
                    value = "\n\n" + title + underline + "\n" + subcontent
                    subsections.append(Section(title, subcontent, subsubsections))

                elif name == "thebibliography":
                    # TODO: bibliography should be another section, outside of the last section.
                    bibcontent, _ = self.build_content(item)
                    value = "\n\nReferences\n" + "=" * 10 + "\n" + bibcontent
                    subsections.append(Section("References", bibcontent))

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

                elif item.hasChildNodes():
                    value, innersubsections = self.build_content(item)
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

        return content, subsections

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
