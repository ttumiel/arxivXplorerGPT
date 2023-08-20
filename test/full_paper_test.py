import pytest
from xplorer.paper import Paper

def test_paper(paper: Paper):
    # all papers should have content, title and methods
    assert paper.content
    assert paper.title

    methods = paper.methods
    assert len(methods) == 4

    if methods['table_of_contents']:
        # There might be words in the preamble, before any sections (abstract, ...)
        # section_words = sum((section.num_words + len(section.title.split())) for section in paper.tree.subsections)
        # assert paper.tree.num_words <= section_words

        # if toc then should be able to get all sections
        for i, section in enumerate(paper.sections):
            assert paper[i] == section

            if section.subsections:
                for j, subsection in enumerate(section.subsections):
                    assert paper[i, j] == subsection

                    if subsection.subsections:
                        for k, subsubsection in enumerate(subsection.subsections):
                            assert paper[i, j, k] == subsubsection

    else:
        assert len(paper.sections) == 0

    # if bibliography, should be able to fetch all citations
    if methods['get_citation']:
        assert len(paper.bibliography) > 0
    else:
        assert len(paper.bibliography) == 0

    # if abstract, should be able to fetch
    if methods['read_abstract']:
        assert paper.abstract


def test_latex_pdf_equivalence(latex_pdf_paper_pair: (Paper, Paper)):
    latex_paper, pdf_paper = latex_pdf_paper_pair

    # Check that we find have the same number of sections
    if pdf_paper.sections and latex_paper.sections:
        if len(latex_paper.sections) != len(pdf_paper.sections):
            print(" ".join(s.title for s in latex_paper.sections))
            print(" ".join(s.title for s in pdf_paper.sections))
        assert len(latex_paper.sections) == len(pdf_paper.sections)
        assert len(latex_paper.section_contents(latex_paper.sections)) == len(pdf_paper.section_contents(pdf_paper.sections))

        for s1, s2 in zip(latex_paper.sections, pdf_paper.sections):
            assert s1.title.lower() == s2.title.lower()
            assert abs(s1.num_words - s2.num_words) < 500 # Loose bounds since pdf may expand quite a bit!


def test_dumping(paper):
    data = paper.dumps()
    print(data)
    loaded_paper = Paper.loads(data)
    print(loaded_paper)

    assert loaded_paper.methods == paper.methods
    assert loaded_paper.table_of_contents == paper.table_of_contents
