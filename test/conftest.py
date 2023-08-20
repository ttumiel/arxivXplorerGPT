import logging
import os

import pytest

from xplorer.download import (download_arxiv_pdf, download_arxiv_source,
                              extract_tar_file)
from xplorer.latex_paper import LatexPaper, guess_main_tex_file
from xplorer.pdf_paper import PDFPaper

latex_paper_logger = logging.getLogger("xplorer.latex_paper")
pdf_paper_logger = logging.getLogger("xplorer.pdf_paper")

latex_paper_logger.setLevel(logging.DEBUG)
pdf_paper_logger.setLevel(logging.DEBUG)


DATA_DIR = "test/data"
PAPER_IDS = {
    "transformer": "1706.03762",
    # "resnet": "1512.03385",
    "ada": "2301.07608",
    "instructgpt": "2203.02155",
}

for name, paper_id in PAPER_IDS.items():
    output_dir = os.path.join(DATA_DIR, name)
    if not os.path.exists(output_dir):
        logging.info("Downloading test files for", name)
        download_arxiv_pdf(paper_id, output_dir)
        download_arxiv_source(paper_id, output_dir)
        tgz_path = os.path.join(output_dir, paper_id)
        extract_tar_file(tgz_path + ".tar.gz", tgz_path)
        os.remove(os.path.join(output_dir, f"{paper_id}.tar.gz"))

def latex_paper_from_name(paper_name):
    paper_dir = os.path.join(DATA_DIR, paper_name, PAPER_IDS[paper_name])
    main_tex_file = guess_main_tex_file(paper_dir)
    return LatexPaper(main_tex_file)

def pdf_paper_from_name(paper_name):
    paper_file = os.path.join(DATA_DIR, paper_name, f"{PAPER_IDS[paper_name]}.pdf")
    return PDFPaper(paper_file)


paper_types = ["latex", "pdf"]
@pytest.fixture(params=[(ptype, pname) for ptype in paper_types for pname in PAPER_IDS.keys()])
def paper(request):
    paper_type, paper_name = request.param

    if paper_type == 'latex':
        return latex_paper_from_name(paper_name)

    if paper_type == 'pdf':
        return pdf_paper_from_name(paper_name)

@pytest.fixture(params=PAPER_IDS.keys())
def latex_pdf_paper_pair(request):
    paper_name = request.param
    return latex_paper_from_name(paper_name), pdf_paper_from_name(paper_name)
