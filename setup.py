from setuptools import setup

setup(
    name='xplorer',
    version='1.0',
    packages=['xplorer'],
    install_requires=[
        "plasTeX",
        "pylatexenc",
        "texttable",
        "requests",
        "pdfminer.six",
    ],
)
