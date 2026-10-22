"""Detection of a model's vision (image) capability, and of image-generation models.

- Ollama: whether "vision" appears in `/api/show` capabilities (in ollama_client, cached).
- OpenAI-compatible: no capability API → name heuristic.
- In both cases the config override (config/vision_models.yml) has the final say:
  force_text (not vision) > force_vision (vision) > base detection.

Image generation (text → image, `/images/generations`) is the other image capability a model
name can carry. Only OpenAI-compatible servers are asked (Ollama has no such endpoint), by name,
with its own pair of overrides in the same file: force_chat > force_image > the name.
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


# Image-generation models served on an OpenAI-compatible `/images/generations`. Kept narrow on
# purpose: a chat model mistaken for one would never get a chat turn again.
_IMAGE_GEN_HINTS = (
    "qwen-image", "flux", "sdxl", "stable-diffusion", "sd3", "dall-e", "gpt-image", "hidream",
)


def _lists(*keys: str) -> list[list[str]]:
    """Substring lists (lowercase) from the override file. Hot-reloaded (read on every request)."""
    try:
        with open(VISION_OVERRIDES_PATH) as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            data = {}
    except (OSError, yaml.YAMLError):
        data = {}
    return [[str(s).lower() for s in data.get(k, []) or []] for k in keys]


def _load_overrides() -> tuple[list[str], list[str]]:
    """(force_vision, force_text) substring lists (lowercase)."""
    fv, ft = _lists("force_vision", "force_text")
    return fv, ft


def is_image_generator(model: str) -> bool:
    """Whether `model` makes images rather than text (OpenAI-compatible servers only)."""
    fi, fc = _lists("force_image", "force_chat")
    m = model.lower()
    if any(s in m for s in fc):
        return False
    if any(s in m for s in fi):
        return True
    return any(h in m for h in _IMAGE_GEN_HINTS)


def apply_overrides(model: str, base: bool) -> bool:
    fv, ft = _load_overrides()
    m = model.lower()
    if any(s in m for s in ft):
        return False
    if any(s in m for s in fv):
        return True
    return base
