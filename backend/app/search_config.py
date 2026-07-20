"""Web search (🔍) config — `config/search.yml`, read on every call (hot-reload).

Falls back to the built-in defaults if the file is missing or malformed; search still works.
"""
import yaml

from app.config import SEARCH_CONFIG_PATH

# Fallback instruction baked into the code so search keeps working if the file is lost.
DEFAULT_QUERY_PROMPT = (
    "You are a web search query generator. Read the conversation context below and "
    "produce a single-line, concise search query that would help answer the user's LAST "
    "message. Output only the query text — no quotes, explanation or extra prose. If no "
    "current or external information is needed (greeting, code writing, a question "
    "answerable from context), output only NONE."
)
DEFAULT_NUM_RESULTS = 5


def _load() -> dict:
    try:
        with open(SEARCH_CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (FileNotFoundError, yaml.YAMLError):
        return {}


def get_query_prompt() -> str:
    prompt = _load().get("query_prompt")
    if isinstance(prompt, str) and prompt.strip():
        return prompt.strip()
    return DEFAULT_QUERY_PROMPT


def get_num_results() -> int:
    n = _load().get("num_results")
    if isinstance(n, int) and 1 <= n <= 20:
        return n
    return DEFAULT_NUM_RESULTS
