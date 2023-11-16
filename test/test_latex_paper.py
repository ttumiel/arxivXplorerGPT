import json
import os

import pytest
from xplorer.latex_paper import LatexPaper, guess_main_tex_file

with open("test/data/test_toc.json") as f:
    EXPECTED_TOC = json.loads(f.read())


@pytest.mark.parametrize(
    "paper",
    [
        "ada",
        "FP8",
        "instructgpt",
        "jarvis_1",
        "llama_2",
        "muzero",
        "resnet",
        "transformer",
    ],
)
def test_latex_paper_toc(paper):
    main_tex = guess_main_tex_file(os.path.join("test/data", paper, "source"))
    latex_paper = LatexPaper(main_tex)
    assert latex_paper.table_of_contents == EXPECTED_TOC[paper]
