"""Built-in (in-repo) tools. They register themselves with the registry on import.

Phase 1's only built-in tool is `web_search` (SearXNG). It reuses the existing
`search_client` internals — a read-only, safe reference implementation.
Which tools are active is filtered at spec time via `config/tools.yml` (see tools_config);
registration here always happens so the enable/disable toggle can hot-reload.
"""
from app import search_client
from app.tools_config import get_num_results
from app.tools.registry import Tool, registry

_WEB_SEARCH_DESC = (
    "Searches the web for current or external information (SearXNG). Use it for recent "
    "events, version/price lookups, people or facts beyond the training data. Do not call "
    "it for greetings, code writing, or questions answerable from the existing context."
)

_WEB_SEARCH_PARAMS = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "A concise, single-line search query.",
        }
    },
    "required": ["query"],
}


async def _web_search(args: dict) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "ERROR: empty query."
    results = await search_client.search(query, get_num_results())
    if not results:
        return f"No web results found for '{query}'."
    return search_client.format_results(query, results)


registry.register(
    Tool(
        name="web_search",
        description=_WEB_SEARCH_DESC,
        parameters=_WEB_SEARCH_PARAMS,
        handler=_web_search,
        source="builtin",
        mutating=False,
    )
)
