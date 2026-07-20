import os

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user, require_admin
from app.config import SYSTEM_PROMPTS_PATH, SEARCH_CONFIG_PATH, TOOLS_CONFIG_PATH
from app.vision import VISION_OVERRIDES_PATH

# Reading is open to every signed-in user; WRITING is admin-only (system_prompts enter
# every user's chat as a system layer — if a regular user could write them they could
# inject a persistent prompt for everyone else).
router = APIRouter(prefix="/api/config", tags=["config"], dependencies=[Depends(get_current_user)])

# Name → file path whitelist (prevents writing arbitrary files).
FILES = {
    "system_prompts": SYSTEM_PROMPTS_PATH,
    "vision_models": VISION_OVERRIDES_PATH,
    "search": SEARCH_CONFIG_PATH,
    "tools": TOOLS_CONFIG_PATH,
}

# Factory defaults: baked into the image, read-only (separate from the mounted /config).
# The "Default" button restores from here if a user wipes the content by accident.
DEFAULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "defaults")


class ConfigIn(BaseModel):
    content: str


@router.get("/{name}")
def get_config(name: str):
    path = FILES.get(name)
    if not path:
        raise HTTPException(404, "Unknown config")
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        content = ""
    return {"name": name, "content": content}


@router.get("/{name}/default")
def get_config_default(name: str):
    """Returns the factory-default content for that config (baked into the image, immutable)."""
    if name not in FILES:
        raise HTTPException(404, "Unknown config")
    try:
        with open(os.path.join(DEFAULTS_DIR, f"{name}.yml"), encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        content = ""
    return {"name": name, "content": content}


@router.put("/{name}", dependencies=[Depends(require_admin)])
def put_config(name: str, payload: ConfigIn):
    path = FILES.get(name)
    if not path:
        raise HTTPException(404, "Unknown config")
    try:
        yaml.safe_load(payload.content)
    except yaml.YAMLError as e:
        raise HTTPException(400, f"YAML error: {e}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(payload.content)
    return {"ok": True}
