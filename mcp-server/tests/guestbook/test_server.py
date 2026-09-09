"""Drive the guestbook over the real MCP protocol, not its Python internals.

The tool is reached the way LibreChat reaches it -- an MCP client speaking
streamable HTTP through the actual Starlette app -- so these tests cover the
tool schema, the header plumbing and the transport, not just the handler."""

from __future__ import annotations

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from printer_mcp.guestbook.server import build_app


async def _call(cfg, hub, *, name: str, message: str, guest_id: str = "guest-1",
                tool: str | None = None):
    """Open a real MCP session against the app and call the tool once."""
    app, aclose = build_app(cfg, hub_client=hub.client())
    import asyncio

    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]
        url = f"http://127.0.0.1:{port}/mcp"
        # The guest id rides a header the chat host sets, so the client has to
        # carry it the same way LibreChat does.
        import httpx
        http_client = httpx.AsyncClient(headers={cfg.guest_id_header: guest_id})
        async with (
            streamable_http_client(url, http_client=http_client) as (r, w, _),
            ClientSession(r, w) as session,
        ):
                init = await session.initialize()
                tools = await session.list_tools()
                result = await session.call_tool(
                    tool or cfg.tool_name, {"from_name": name, "message": message}
                )
                return init, tools, result.content[0].text
    finally:
        server.should_exit = True
        await task
        await aclose()


async def test_exposes_exactly_one_tool_under_the_configured_name(cfg, hub):
    init, tools, text = await _call(cfg, hub, name="Robin", message="hello")
    assert [t.name for t in tools.tools] == ["message_tim"]
    # The instructions carry the "ask who they are" rule to hosts that inject them.
    assert "what they are called" in (init.instructions or "")
    assert "Never invent" in (tools.tools[0].description or "")
    assert "Sent." in text


async def test_sends_a_common_core_document_naming_the_guest(cfg, hub):
    await _call(cfg, hub, name="Robin", message="hi there")
    assert len(hub.sends) == 1
    sent = hub.sends[0]
    assert sent["to"] == ["owner"]
    blocks = sent["document"]["blocks"]
    assert [b["type"] for b in blocks] == ["header", "paragraph"]
    assert blocks[0]["text"] == "Message for Tim"
    assert blocks[1]["text"] == "From: Robin\n\nhi there"


async def test_placeholder_name_is_refused_without_reaching_the_hub(cfg, hub):
    _, _, text = await _call(cfg, hub, name="anonymous", message="hi")
    assert "Not sent" in text and "placeholder" in text
    assert hub.sends == []


async def test_blank_line_flood_is_collapsed_before_it_becomes_paper(cfg, hub):
    await _call(cfg, hub, name="Robin", message="top" + "\n" * 40 + "bottom")
    body = hub.sends[0]["document"]["blocks"][1]["text"]
    assert body == "From: Robin\n\ntop\n\nbottom"


async def test_oversized_message_is_refused_without_reaching_the_hub(cfg, hub):
    _, _, text = await _call(cfg, hub, name="Robin", message="x" * 500)
    assert "Not sent" in text and "shorten" in text
    assert hub.sends == []


async def test_per_guest_hourly_cap_stops_one_conversation(cfg, hub):
    for _ in range(cfg.per_guest_per_hour):
        _, _, ok = await _call(cfg, hub, name="Robin", message="hi", guest_id="g1")
        assert "Sent." in ok
    _, _, text = await _call(cfg, hub, name="Robin", message="hi again", guest_id="g1")
    assert "Not sent" in text and "hour" in text
    assert len(hub.sends) == cfg.per_guest_per_hour


async def test_daily_total_survives_a_fresh_guest_id(cfg, hub):
    """The per-guest cap resets with every new session, so the daily total is
    the control that actually bounds the paper. A new guest id must not reset it."""
    for i in range(cfg.global_per_day):
        _, _, ok = await _call(cfg, hub, name="Robin", message=f"hi {i}",
                               guest_id=f"fresh-{i}")
        assert "Sent." in ok
    _, _, text = await _call(cfg, hub, name="Robin", message="one more",
                             guest_id="fresh-99")
    assert "Not sent" in text and "today" in text
    assert len(hub.sends) == cfg.global_per_day


async def test_same_guest_same_text_reuses_one_idempotency_key(cfg, hub):
    await _call(cfg, hub, name="Robin", message="hi", guest_id="g1")
    await _call(cfg, hub, name="Robin", message="hi", guest_id="g1")
    assert hub.sends[0]["idempotency_key"] == hub.sends[1]["idempotency_key"]


async def test_different_guests_saying_the_same_thing_are_distinct_notes(cfg, hub):
    """The hub dedups on (sender, key) and every guest shares one sender, so two
    people both saying hello must not collapse into a single printed note."""
    await _call(cfg, hub, name="Robin", message="hello", guest_id="g1")
    await _call(cfg, hub, name="Sam", message="hello", guest_id="g2")
    assert hub.sends[0]["idempotency_key"] != hub.sends[1]["idempotency_key"]
