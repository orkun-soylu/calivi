"""Config for the tool layer — `config/tools.yml`, read on every call (hot-reload).

Falls back to the built-in defaults if the file is missing or malformed (tools still
default to enabled). Turning off `enabled` (the master switch) or a per-tool `enabled`
means the tool is NOT OFFERED to the model — registration always happens, the filtering
occurs at spec time, which is what makes hot-reload work.
"""
import yaml

from app.config import TOOLS_CONFIG_PATH

DEFAULT_MAX_ITERATIONS = 5
DEFAULT_NUM_RESULTS = 5


def _load() -> dict:
    try:
        with open(TOOLS_CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (FileNotFoundError, yaml.YAMLError):
        return {}


def is_enabled() -> bool:
    """Master switch for the tool layer (enabled by default)."""
    v = _load().get("enabled")
    return True if v is None else bool(v)


def get_max_iterations() -> int:
    n = _load().get("max_iterations")
    return n if isinstance(n, int) and 1 <= n <= 20 else DEFAULT_MAX_ITERATIONS


def _tool_cfg(name: str) -> dict:
    return (_load().get("tools") or {}).get(name) or {}


def tool_enabled(name: str) -> bool:
    v = _tool_cfg(name).get("enabled")
    return True if v is None else bool(v)


def get_num_results() -> int:
    """Number of results for the web_search tool (1-20)."""
    n = _tool_cfg("web_search").get("num_results")
    return n if isinstance(n, int) and 1 <= n <= 20 else DEFAULT_NUM_RESULTS
