"""Detection of a model's vision (image) capability.

- Ollama: whether "vision" appears in `/api/show` capabilities (in ollama_client, cached).
- OpenAI-compatible: no capability API → name heuristic.
- In both cases the config override (config/vision_models.yml) has the final say:
  force_text (not vision) > force_vision (vision) > base detection.
"""
import os

import yaml

VISION_OVERRIDES_PATH = os.environ.get("VISION_OVERRIDES_PATH", "/config/vision_models.yml")

# Hints for the name heuristic used on OpenAI-compatible models (and as a general fallback).
_VISION_HINTS = (
    "vision", "-vl", "vl-", "vl:", "-4o", "4o-", "gpt-4o", "gpt-4.1", "gpt-5",
    "gemini", "claude-3", "claude-4", "claude-opus", "claude-sonnet",
    "pixtral", "llava", "minicpm-v", "moondream", "qwen2-vl", "qwen2.5-vl", "qwen3-vl",
    "internvl", "llama-3.2-vision", "phi-3-vision", "phi-4-multimodal",
)


def name_looks_vision(model: str) -> bool:
    m = model.lower()
    return any(h in m for h in _VISION_HINTS)


def _load_overrides() -> tuple[list[str], list[str]]:
    """(force_vision, force_text) substring lists (lowercase). Hot-reloaded (read on every request)."""
    try:
        with open(VISION_OVERRIDES_PATH) as f:
            data = yaml.safe_load(f) or {}
        fv = [str(s).lower() for s in data.get("force_vision", []) or []]
        ft = [str(s).lower() for s in data.get("force_text", []) or []]
        return fv, ft
    except (OSError, yaml.YAMLError):
        return [], []


def apply_overrides(model: str, base: bool) -> bool:
    fv, ft = _load_overrides()
    m = model.lower()
    if any(s in m for s in ft):
        return False
    if any(s in m for s in fv):
        return True
    return base
