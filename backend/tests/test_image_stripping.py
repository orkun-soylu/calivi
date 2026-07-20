"""Dropping images from history when switching to a non-vision model (llm.py).

`_strip_images_if_not_vision`, added 2026-07-04, prevents the 400 you get when `images`
reach a non-vision model. But users can paste an image WITHOUT typing text (content=""),
and such a message became completely empty once the image was dropped → another 400
("must not be empty", reproduced live against moonshot on 2026-07-20).
"""
import pytest

from app import llm

IMG = "data:image/png;base64,AAAA"


@pytest.fixture
def no_vision_support(monkeypatch):
    """Report the target model as NOT vision-capable → images must be dropped."""

    async def none(server, names):
        return []

    monkeypatch.setattr(llm, "vision_models", none)


@pytest.fixture
def with_vision_support(monkeypatch):
    async def all_of_them(server, names):
        return list(names)

    monkeypatch.setattr(llm, "vision_models", all_of_them)


async def test_a_textless_image_message_does_not_become_empty(no_vision_support):
    """The actual bug: content="" plus an image left an empty user message behind."""
    msgs = [{"role": "user", "content": "", "images": [IMG]}]
    out = await llm._strip_images_if_not_vision({}, "text-model", msgs)
    assert "images" not in out[0]
    assert out[0]["content"] == llm.IMAGE_STRIPPED_PLACEHOLDER
    assert out[0]["content"].strip()


async def test_text_is_preserved_on_an_image_message(no_vision_support):
    msgs = [{"role": "user", "content": "what is this?", "images": [IMG]}]
    out = await llm._strip_images_if_not_vision({}, "text-model", msgs)
    assert out[0]["content"] == "what is this?"
    assert "images" not in out[0]


async def test_whitespace_only_content_is_filled_too(no_vision_support):
    """content="   " is also empty as far as upstream is concerned."""
    msgs = [{"role": "user", "content": "   ", "images": [IMG]}]
    out = await llm._strip_images_if_not_vision({}, "text-model", msgs)
    assert out[0]["content"] == llm.IMAGE_STRIPPED_PLACEHOLDER


async def test_message_count_and_order_are_preserved(no_vision_support):
    """We fill the empty message rather than DROPPING it: dropping would leave the following
    assistant reply without its prompt and break user/assistant alternation."""
    msgs = [
        {"role": "user", "content": "", "images": [IMG]},
        {"role": "assistant", "content": "The image shows a screenshot."},
        {"role": "user", "content": "are you there"},
    ]
    out = await llm._strip_images_if_not_vision({}, "text-model", msgs)
    assert [m["role"] for m in out] == ["user", "assistant", "user"]
    assert all((m.get("content") or "").strip() for m in out)


async def test_images_are_untouched_on_a_vision_model(with_vision_support):
    msgs = [{"role": "user", "content": "", "images": [IMG]}]
    out = await llm._strip_images_if_not_vision({}, "seeing-model", msgs)
    assert out[0]["images"] == [IMG]
    assert out[0]["content"] == ""  # no placeholder: the image is still there, nothing is missing


async def test_history_without_images_passes_through_untouched(no_vision_support):
    """No images → no work at all (the zero-extra-cost guarantee)."""
    msgs = [{"role": "user", "content": "hello"}]
    out = await llm._strip_images_if_not_vision({}, "text-model", msgs)
    assert out is msgs
