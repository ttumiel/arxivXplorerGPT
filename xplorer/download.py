import os
import re
import tarfile
import tempfile

import requests
from google.cloud import storage

from xplorer.latex_paper import LatexPaper, guess_main_tex_file
from xplorer.pdf_paper import PDFPaper


def extract_tar_file(tar_path, output_dir):
    with tarfile.open(tar_path, 'r:gz') as tar:
        tar.extractall(path=output_dir)

def download_arxiv_source(arxiv_id, output_dir):
    source_url = f"https://export.arxiv.org/e-print/{arxiv_id}"
    os.makedirs(output_dir, exist_ok=True)

    response = requests.get(source_url)
    response.raise_for_status()  # Will raise an exception if the response status is not 200
    output_dir = os.path.join(output_dir, f"{arxiv_id}.tar.gz")
    with open(output_dir, "wb") as f:
        f.write(response.content)

    return output_dir

def download_arxiv_pdf(arxiv_id, output_dir):
    bucket_name = "arxiv-dataset"
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)

    prefix = f"arxiv/arxiv/pdf/{arxiv_id[:4]}/{arxiv_id}"
    blob_name = max(blob.name for blob in bucket.list_blobs(prefix=prefix))
    blob = bucket.blob(blob_name)

    os.makedirs(output_dir, exist_ok=True)
    destination_file_name = os.path.join(output_dir, f"{arxiv_id}.pdf")
    blob.download_to_filename(destination_file_name)

    return destination_file_name


def read_arxiv_source(filename):
    # extract the tar file
    datadir = re.sub(r'\.(tgz|tar\.gz)$', '', filename)
    extract_tar_file(filename, datadir)

    # delete the tar file
    # os.remove(filename)

    # Extract the text
    main_file = guess_main_tex_file(datadir)
    paper = LatexPaper(main_file)

    return paper


def process_paper(paper_id):
    # Create tmp directory
    with tempfile.TemporaryDirectory() as tmpdirname:
        try:
            # source = download_arxiv_source(paper_id, tmpdirname)
            source = "data/attention/1706.03762.tar.gz"
            paper = read_arxiv_source(source)
        except:
            path = download_arxiv_pdf(paper_id, tmpdirname)
            paper = PDFPaper(path)

    return paper



# paper_id = '1706.10295'
# paper_id = '1706.03762' # Attention is all you need

# paper, success = process_paper(paper_id)

# if success:
#     print(paper.toc)
#     print()
#     print(paper.sections[3].title)
#     print(paper.sections[3].content)
# else:
#     print(paper)
