import pytest

from hub.capabilities import (
    CapabilityConflict,
    CapabilityError,
    capability_for_recipient,
    upsert_capability,
    validate_document,
)
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

CONFLICTING_SCHEMA = {
    "type": "object",
    "properties": {
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"type": {"enum": ["paragraph", "image"]}},
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


async def test_upsert_allows_identical_rereport_but_rejects_conflict(sm):
    async with sm() as s:
        bob = await _join(s, "bob")
        carol = await _join(s, "carol")
        await upsert_capability(
            s, printer_id=bob.printer_id, renderer_version="1.2.0",
            blocks_schema=SCHEMA, block_types=["paragraph", "header"])

        await upsert_capability(
            s, printer_id=carol.printer_id, renderer_version="1.2.0",
            blocks_schema=SCHEMA, block_types=["paragraph", "header"])

        with pytest.raises(CapabilityConflict, match="renderer_version"):
            await upsert_capability(
                s, printer_id=carol.printer_id, renderer_version="1.2.0",
                blocks_schema=CONFLICTING_SCHEMA, block_types=["paragraph", "image"])
        version, schema, block_types = await capability_for_recipient(s, carol.printer_id)
        assert version == "1.2.0"
        assert schema == SCHEMA
        assert block_types == ["paragraph", "header"]


async def test_capabilities_route_conflicts_on_changed_renderer_report(app_client):
    client, deps = app_client
    async with deps.sessionmaker() as s:
        bob = await _join(s, "bob")

    first = await client.put(
        "/capabilities",
        headers={"Authorization": f"Bearer {bob.device_token}"},
        json={
            "renderer_version": "1.2.0",
            "blocks_schema": SCHEMA,
            "block_types": ["paragraph", "header"],
        },
    )
    assert first.status_code == 200

    same = await client.put(
        "/capabilities",
        headers={"Authorization": f"Bearer {bob.device_token}"},
        json={
            "renderer_version": "1.2.0",
            "blocks_schema": SCHEMA,
            "block_types": ["paragraph", "header"],
        },
    )
    assert same.status_code == 200

    conflict = await client.put(
        "/capabilities",
        headers={"Authorization": f"Bearer {bob.device_token}"},
        json={
            "renderer_version": "1.2.0",
            "blocks_schema": CONFLICTING_SCHEMA,
            "block_types": ["paragraph", "image"],
        },
    )
    assert conflict.status_code == 409


async def test_validate_rejects_unknown_enum_with_detail():
    with pytest.raises(CapabilityError) as ei:
        validate_document(SCHEMA, {"blocks": [{"type": "drop_cap"}]})
    detail = ei.value.detail
    assert detail["valid_values"] == ["paragraph", "header"] or "drop_cap" in str(detail)


async def test_validate_rejects_missing_required_field():
    with pytest.raises(CapabilityError):
        validate_document(SCHEMA, {"blocks": [{}]})  # missing required "type"
