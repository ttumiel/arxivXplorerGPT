# arXiv Xplorer Plugin

[Try it on ChatGPT](https://chat.openai.com/g/g-WeT9tE7SR-arxiv-xplorer)
[Read the Docs](https://arxivxplorer.com/plugin/)

## Functions

- `search`: Find relevant papers based on a search query.
- `read_paper_metadata`: Read the metadata of a paper, where available: id, title, date, authors, abstract, table_of_contents, can_read_citation.
- `read_section`: Read a particular section of a paper. Can be innacurate for pdfs.
- `read_citation`: Read a citation from a paper. For latex docs only.
- `chunk_search`: Search for a particular chunk inside a paper.


## Example Plugin workflows:

1. Generate a literature review:
   1. Search for relevant terms and collect papers (`search`). Expand the terms and relevant papers using the related work sections inside the papers (`read_section`, `get_citation`).
   2. Read the most relevant sections of different papers (`read_section`, `chunk_search`).
   3. Write the literature review from the collected information.
2. Summarize a particular paper:
   1. If not given the `paper_id`, use keyword search to find the paper (`search`).
   2. Read the basic contents of the paper (`read_paper_metadata`).
   3. If the abstract and introduction have enough info, use that for the summary (`read_section`).
   4. Write a summary based on the information collected.
3. Find a particular detail from a paper:
   1. Read the table of contents and abstract of the paper (`read_paper_metadata`).
   2. Use the `chunk_search` function to find the detail in the paper.
   3. Report back the detail from the search.
4. Implement a paper in code:
   1. Read the basic contents of the paper (`read_paper_metadata`).
   2. If there is a implementation section, read that, as well as any code appendices, otherwise read the algorithm details (`read_section`).
   3. Write code based on the information collected from the paper.
5. Find related papers:
   1. Search by Similarity method (`search`) if given the `paper_id`
   2. Look inside the related work section for citations, and read those papers (`read_section`, `get_citation`, `search`).
