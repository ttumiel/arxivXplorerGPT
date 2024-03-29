import functools
import json
import traceback
from typing import List, Union

from chat2func import function_call
from firebase_admin import initialize_app
from firebase_functions import https_fn, options, scheduler_fn
from xplorer.functions import ArxivXplorerAPI, SearchMethod

initialize_app()
api = ArxivXplorerAPI(firestore_db="papers")


def request_handler(fn=None, allow_cors=True, secrets=None):
    if fn is None:
        return functools.partial(
            request_handler, allow_cors=allow_cors, secrets=secrets
        )

    @https_fn.on_request(
        secrets=secrets,
        cors=options.CorsOptions(cors_origins=[r"*"], cors_methods=["get", "post"]),
        memory=options.MemoryOption.GB_1,
        region=options.SupportedRegion.US_WEST1,
        max_instances=10,
        cpu=1,
    )
    @functools.wraps(fn)
    def thunk(request: https_fn.Request):
        try:
            args = request.json if request.is_json else {}
            result = function_call(
                fn, args, validate=True, from_json=False, return_json=False
            )
            result = json.dumps(result, ensure_ascii=False, indent=2)
            return https_fn.Response(result, mimetype="application/json")
        except Exception as e:
            print(f"ERROR :: Function {fn.__name__} failed:\n", traceback.format_exc())
            return (f"Function call error: {e}", 400)

    return thunk


@request_handler(secrets=["OPENAI_API_KEY"])
def chunk_search(paper_id: str, query: str, count: int = 3, page: int = 1):
    return api.chunk_search(paper_id, query, count, page)


@request_handler
def read_paper_metadata(paper_id: str, show_abstract=True):
    return api.read_paper_metadata(paper_id, show_abstract)


@request_handler
def read_section(paper_id: str, section_id: Union[int, List[int]]):
    return api.read_section(paper_id, section_id)


@request_handler
def read_citation(paper_id: str, citation: str):
    return api.read_citation(paper_id, citation)


@request_handler
def search(
    query: str,
    count: int = 8,
    page: int = 1,
    year: int = None,
    method: SearchMethod = SearchMethod.SEMANTIC,
):
    return api.search(query, count, page, year, method)


@request_handler
def get_figure(paper_id: str, figure_id: str):
    return api.get_figure(paper_id, figure_id)


@scheduler_fn.on_schedule(
    schedule="0 5 * * 0",
    timezone=scheduler_fn.Timezone("Etc/UTC"),
    region=options.SupportedRegion.US_WEST1,
    memory=options.MemoryOption.MB_256,
    max_instances=1,
    cpu=1,
)
def db_clean(event: scheduler_fn.ScheduledEvent):
    "Delete the least recently used papers from firestore"
    try:
        num_deleted = api.cache.lru_delete_remote()
    except Exception as e:
        print(f"ERROR :: Function db_clean failed:\n", traceback.format_exc())
        raise e

    print("Deleted", num_deleted, "papers from firestore")
