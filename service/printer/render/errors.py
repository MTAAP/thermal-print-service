from __future__ import annotations


class RenderInputError(Exception):
    """Renderer received user content that cannot be processed.

    Distinguishes client-caused render failures (malformed PNG bytes inside
    an ``image`` block, invalid characters for an EAN13 barcode, etc.) from
    genuine server faults (FreeType crashes, OOM, registry corruption). The
    HTTP layer maps this to a structured 400 response so senders can fix
    their payload, instead of 500 which encourages blind retries.

    ``block_index`` is filled by the document renderer; individual block
    renderers don't know their position.
    """

    def __init__(
        self, message: str, *, block_index: int | None = None,
        field: str | None = None,
    ) -> None:
        super().__init__(message)
        self.block_index = block_index
        self.field = field
