import yaml

from app.config import SYSTEM_PROMPTS_PATH


def get_system_prompt(model: str) -> str | None:
    """Returns the system prompt for a model (falls back to 'default', then None).

    The file is read on every call (hot-reload) — no restart needed after editing.
    If the file is missing or malformed it silently returns None and the chat proceeds
    without a system message.
    """
    try:
        with open(SYSTEM_PROMPTS_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (FileNotFoundError, yaml.YAMLError):
        return None

    prompt = data.get(model) or data.get("default")
    if isinstance(prompt, str) and prompt.strip():
        return prompt.strip()
    return None
