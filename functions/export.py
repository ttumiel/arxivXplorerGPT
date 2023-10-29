from xplorer.functions import ArxivXplorerAPI

if __name__ == "__main__":
    api = ArxivXplorerAPI()
    api.build(".", export_source=False)
