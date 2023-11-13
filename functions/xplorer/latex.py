import logging
import os
from typing import Optional

from plasTeX import Base, Command, Config, Macro, TeX, TeXDocument
from plasTeX.Packages import xcolor
from pylatexenc.latex2text import (EnvironmentTextSpec, LatexNodes2Text,
                                   MacroTextSpec, get_default_latex_context_db)
from pylatexenc.latexwalker import LatexMacroNode
from xplorer.images import figure, includegraphics

logger = logging.getLogger(__name__)


def labeller(name: str):
    def handle(node: LatexMacroNode, l2tobj: LatexNodes2Text):
        try:
            key = l2tobj.nodelist_to_text(node.nodeargd.argnlist)
            return f"<{name}. {key}>"
        except Exception:
            return f"<{name}>"

    return handle


def handle_href(node: LatexMacroNode, l2tobj):
    return "[{}]({})".format(
        l2tobj.nodelist_to_text([node.nodeargd.argnlist[1]]),
        l2tobj.nodelist_to_text([node.nodeargd.argnlist[0]]),
    )


def handle_item(node: LatexMacroNode, l2tobj: LatexNodes2Text):
    return l2tobj.node_to_text(node.nodeoptarg) if node.nodeoptarg else "- "


class TextEncoder:
    def __init__(self) -> None:
        l2t_context_db = get_default_latex_context_db()
        l2t_context_db.add_context_category(
            "custom",
            prepend=True,
            macros=[
                MacroTextSpec("cite", simplify_repl=labeller("cit")),
                MacroTextSpec("citep", simplify_repl=labeller("cit")),
                MacroTextSpec("ref", simplify_repl=labeller("ref")),
                MacroTextSpec("label", simplify_repl=labeller("label")),
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

    def __call__(self, latex: str) -> str:
        try:
            return self.l2t.latex_to_text(latex)
        except Exception:
            return latex


class TeXParser(TeX.TeX):
    def __init__(
        self, file: Optional[str] = None, ownerDocument: Optional[TeXDocument] = None
    ):
        self.disableLogging()
        if ownerDocument is None:
            config = Config.defaultConfig()
            config["general"]["load-tex-packages"] = False
            ownerDocument = TeXDocument(config=config)
            ownerDocument.context.contexts[0]["citep"] = Base.cite
            ownerDocument.context.contexts[0]["citet"] = Base.cite
            ownerDocument.context.contexts[0]["figure"] = figure
            ownerDocument.context.contexts[0]["figure*"] = figure
            ownerDocument.context.contexts[0]["includegraphics"] = includegraphics
            ownerDocument.rootDir = os.path.dirname(file)

        super().__init__(ownerDocument, file)

    def kpsewhich(self, name: str):
        "Locate the given file in the source directory and TEXINPUTS paths."
        try:
            srcDir = os.path.dirname(self.filename)
        except AttributeError:
            srcDir = "."

        texinputs = os.environ.get("TEXINPUTS", ".").split(os.path.pathsep)
        search_paths = [self.ownerDocument.rootDir, srcDir] + texinputs

        # Search for the file in the source directory and TEXINPUTS
        for path in search_paths:
            if not path:
                continue

            # Check with suffix
            candidate_path = os.path.join(path, name)
            if os.path.exists(candidate_path):
                return os.path.abspath(candidate_path)

            # Check without suffix by matching any file that starts with the name
            folder = os.path.join(path, os.path.dirname(name))
            filename = os.path.basename(name)
            if os.path.exists(folder) and os.path.isdir(folder):
                for candidate in os.listdir(folder):
                    if candidate.startswith(filename + "."):
                        return os.path.abspath(os.path.join(folder, candidate))

        raise FileNotFoundError(f"Could not find any file named: {name}")

    def parse(self, output=None) -> TeXDocument:
        """Parse stream content until it is empty

        Args:
            output: object to put the content in.  This should be either
                a TeXDocument or a TeXFragment

        Returns:
            `TeXDocument' instance
        """
        tokens = TeX.bufferediter(self)

        if output is None:
            output = self.ownerDocument

        try:
            for item in tokens:
                try:
                    if item.nodeType == Macro.ELEMENT_NODE:
                        item.parentNode = output
                        item.digest(tokens)
                    output.append(item)
                except Exception as e:
                    logger.warning(f"Error parsing item {item}: {e}")

        except Exception as e:
            logger.error(f"Failed to parse Tex doc: {e}")
            raise

        if self.toplevel:
            for _, callbacks in sorted(self.ownerDocument.postParseCallbacks.items()):
                for callback in callbacks:
                    callback()

        return output


# Patches


class textcolor(xcolor.ColorCommand):
    r"""The \textcolor command (c.f. pg 22, xcolor v2.12, 2016/05/11)"""
    args = "[ model:str ] color:str self"

    def digest(self, tokens) -> None:
        Command.digest(self, tokens)


xcolor.textcolor = textcolor
