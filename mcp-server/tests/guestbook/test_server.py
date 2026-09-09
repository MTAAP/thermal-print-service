"""Drive the guestbook over the real MCP protocol, not its Python internals.

The tool is reached the way LibreChat reaches it -- an MCP client speaking
streamable HTTP through the actual Starlette app -- so these tests cover the
tool schema, the header plumbing and the transport, not just the handler."""

from __future__ import annotations

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from printer_mcp.guestbook.server import build_app


async def _call(cfg, hub, *, name: str, message: str, guest_id: str = "guest-1",
                tool: str | None = None, preformatted: bool | None = None):
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
                args = {"from_name": name, "message": message}
                if preformatted is not None:
                    args["preformatted"] = preformatted
                result = await session.call_tool(tool or cfg.tool_name, args)
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
    the control that actually bounds the paper. A new guest id must not reset it.

    The hourly total is lifted out of the way here so the daily one is what is
    actually under test; they are separately covered."""
    import dataclasses

    cfg = dataclasses.replace(cfg, global_per_hour=1000)
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


CAT = "  /\\_/\\\n ( o.o )\n  > ^ <"


async def test_preformatted_keeps_its_spacing_and_line_breaks(cfg, hub):
    """The bug this covers: a drawing sent as prose came out as a few mangled
    lines, because the paragraph block reflows text to the paper width and the
    sanitiser collapsed the runs of spaces the picture is made of."""
    _, _, text = await _call(cfg, hub, name="Robin", message=CAT, preformatted=True)
    assert "Sent." in text
    blocks = hub.sends[0]["document"]["blocks"]
    art = [b for b in blocks if b["type"] == "ascii_art"]
    assert len(art) == 1, f"expected an ascii_art block, got {[b['type'] for b in blocks]}"
    assert art[0]["text"] == CAT
    # The wider of the two fonts by columns, which is what art needs.
    assert art[0]["font"] == "small"
    # The sender still gets named, just not inside the drawing.
    assert any(b["type"] == "paragraph" and b["text"] == "From: Robin" for b in blocks)


async def test_prose_still_collapses_and_still_uses_a_paragraph(cfg, hub):
    """The art path must not loosen the prose path: runs of spaces and blank
    lines are still the cheap way to feed paper when the text is not a drawing.

    The sample is real prose, because the detector reads the shape of the text:
    a double space anywhere would (correctly) make this a drawing."""
    note = "Hi Tim, the lift is broken again.\n\n\n\nSorry to be the one to say."
    await _call(cfg, hub, name="Robin", message=note, preformatted=False)
    blocks = hub.sends[0]["document"]["blocks"]
    assert [b["type"] for b in blocks] == ["header", "paragraph"]
    assert blocks[1]["text"] == (
        "From: Robin\n\nHi Tim, the lift is broken again.\n\nSorry to be the one to say."
    )


async def test_art_survives_even_when_the_model_forgets_the_flag(cfg, hub):
    """The bug Tim hit: an ASCII poop emoji sent with preformatted unset went
    into a paragraph, which reflows every line onto one, so the drawing printed
    as a single mangled row beside the sender's name.

    A flag the model has to remember is not a mechanism. The shape of the text
    decides, and the flag only ever adds to that."""
    poop = ")('\n ) )\n ( o o )\n ( ___ )\n (_______)"
    _, _, text = await _call(cfg, hub, name="tim", message=poop, preformatted=False)
    assert "Sent." in text
    blocks = hub.sends[0]["document"]["blocks"]
    art = [b for b in blocks if b["type"] == "ascii_art"]
    assert art, f"drawing rendered as {[b['type'] for b in blocks]}, not ascii_art"
    assert art[0]["text"] == poop


async def test_art_wider_than_the_paper_is_refused_not_clipped(cfg, hub):
    """The renderer draws each line from x=0 without wrapping, so an over-wide
    line loses its right-hand side silently. Refusing gives the model something
    it can act on instead."""
    wide = "\n".join(["#" * (cfg.max_art_cols + 8)] * 3)
    _, _, text = await _call(cfg, hub, name="Robin", message=wide, preformatted=True)
    assert "Not sent" in text
    assert str(cfg.max_art_cols) in text and "wide" in text
    assert hub.sends == []


async def test_art_gets_a_bigger_budget_than_prose(cfg, hub):
    """Art that would be refused as prose goes through, because a drawing needs
    lines that prose does not."""
    tall = "\n".join(f"line {i} of an ordinary note" for i in range(cfg.max_message_lines + 5))
    _, _, refused = await _call(cfg, hub, name="Robin", message=tall, preformatted=False)
    assert "Not sent" in refused
    _, _, sent = await _call(cfg, hub, name="Robin", message=tall, preformatted=True)
    assert "Sent." in sent, "the flag must still force the larger budget on its own"


async def test_art_is_still_bounded(cfg, hub):
    """A bigger budget is still a budget: the art path is not an unlimited one."""
    too_tall = "\n".join("x" for _ in range(cfg.max_art_lines + 5))
    _, _, text = await _call(cfg, hub, name="Robin", message=too_tall, preformatted=True)
    assert "Not sent" in text and "lines" in text
    assert hub.sends == []


async def test_hourly_total_refuses_before_the_relay_silently_would(cfg, hub):
    """The recipient's relay has its own per-sender hourly ceiling and rejects
    below the hub, which has already answered "queued" -- so tripping THAT
    ceiling tells the guest "Sent." and prints nothing.

    Keeping an hourly total here, set under the relay's, means the refusal
    happens where somebody is listening."""
    for i in range(cfg.global_per_hour):
        _, _, ok = await _call(cfg, hub, name="Robin", message=f"note {i}",
                               guest_id=f"g-{i}")
        assert "Sent." in ok
    _, _, text = await _call(cfg, hub, name="Robin", message="one more",
                             guest_id="g-late")
    assert "Not sent" in text and "hour" in text
    assert len(hub.sends) == cfg.global_per_hour
