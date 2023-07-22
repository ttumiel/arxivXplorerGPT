import json

import aiohttp
import quart
import quart_cors
from quart import request

app = quart_cors.cors(quart.Quart(__name__), allow_origin="https://chat.openai.com")

QUERY_URL = "https://us-west1-semanticxplorer.cloudfunctions.net/semantic-xplorer-db"
SIMILARITY_URL = "https://us-west1-semanticxplorer.cloudfunctions.net/semantic-xplorer-db-similarity"

def filter_papers(papers, skip_first=False):
    filtered_papers = [
        {
            "id": paper["id"],
            "title": paper["metadata"]["title"],
            "authors": paper["metadata"]["short_author"],
            "score": paper["score"],
            "abstract": paper["metadata"]["abstract"],
        }
        for paper in papers
    ]
    if skip_first:
        filtered_papers = filtered_papers[1:]
    return filtered_papers


async def fetch_json(query, method="query"):
    url = QUERY_URL if method == "query" else SIMILARITY_URL

    is_similarity = method == "similarity"
    if is_similarity:
        query = f"https://arxiv.org/abs/{query}"

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{url}?query={query}&count=6") as response:
            if response.status != 200:
                # if there's a problem, return the body for debugging
                return await response.text()
            return filter_papers(await response.json(), skip_first=is_similarity)

@app.route('/xplorer/<string:query>')
async def search(query):
    data = await fetch_json(query, method='query')
    return quart.Response(response=json.dumps(data), status=200)

@app.route('/xplorer-similarity/<string:id>')
async def similarity_search(id):
    print(id)
    data = await fetch_json(id, method='similarity')
    return quart.Response(response=json.dumps(data), status=200)

@app.get("/logo.png")
async def plugin_logo():
    filename = 'logo.png'
    return await quart.send_file(filename, mimetype='image/png')

@app.get("/.well-known/ai-plugin.json")
async def plugin_manifest():
    host = request.headers['Host']
    with open("./.well-known/ai-plugin.json") as f:
        text = f.read()
        return quart.Response(text, mimetype="text/json")

@app.get("/openapi.yaml")
async def openapi_spec():
    host = request.headers['Host']
    with open("openapi.yaml") as f:
        text = f.read()
        return quart.Response(text, mimetype="text/yaml")

def main():
    app.run(debug=True, host="0.0.0.0", port=5003)

if __name__ == "__main__":
    main()
