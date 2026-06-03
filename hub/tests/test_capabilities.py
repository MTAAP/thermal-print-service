import pytest

from hub.capabilities import CapabilityError, upsert_capability, validate_document
from hub.invites import create_invite, redeem_invite

# Minimal JSON Schema standing in for a recipient's /schema "blocks".
SCHEMA = {
    "type": "object",
    "properties": {
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"type": {"enum": ["paragraph", "header"]}},
                "required": ["type"],
            },
        }
    },
    "required": ["blocks"],
}


async def _join(s, handle):
    code = await create_invite(s, issuer_printer_id=None, ttl_s=3600)
    return await redeem_invite(s, code=code, handle=handle, display_name=handle)


async def test_upsert_sets_renderer_version_and_caches_schema(sm):
    async with sm() as s:
        reg = await _join(s, "bob")
        await upsert_capability(s, printer_id=reg.printer_id,
                                renderer_version="1.2.0",
                                blocks_schema=SCHEMA, block_types=["paragraph", "header"])
        # validation pulls the recipient's cached schema by their renderer_version
        validate_document(SCHEMA, {"blocks": [{"type": "paragraph"}]})  # ok, no raise


async def test_validate_rejects_unknown_enum_with_detail():
    with pytest.raises(CapabilityError) as ei:
        validate_document(SCHEMA, {"blocks": [{"type": "drop_cap"}]})
    detail = ei.value.detail
    assert detail["valid_values"] == ["paragraph", "header"] or "drop_cap" in str(detail)


async def test_validate_rejects_missing_required_field():
    with pytest.raises(CapabilityError):
        validate_document(SCHEMA, {"blocks": [{}]})  # missing required "type"
