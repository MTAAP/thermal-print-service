from __future__ import annotations

from typing import Protocol

from PIL import Image


class BlockRenderer(Protocol):
    def __call__(self, block, ctx) -> Image.Image: ...


_REGISTRY: dict[str, BlockRenderer] = {}


def register(type_name: str):
    def deco(fn: BlockRenderer):
        _REGISTRY[type_name] = fn
        return fn
    return deco


def renderer_for(type_name: str) -> BlockRenderer | None:
    return _REGISTRY.get(type_name)
