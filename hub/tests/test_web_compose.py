async def _friend(deps, alice, handle="bob"):
    from hub.capabilities import upsert_capability
    from hub.invites import create_invite, redeem_invite
    async with deps.sessionmaker() as s:
        bob = await redeem_invite(
            s, code=await create_invite(s, issuer_printer_id=alice.printer_id, ttl_s=3600),
            handle=handle, display_name=handle.title())
        # a permissive schema so the common-core doc validates
        await upsert_capability(s, printer_id=bob.printer_id, renderer_version="1.0.0",
                                blocks_schema={"type": "object"}, block_types=["paragraph"])
    return bob


async def test_compose_get_lists_friends_as_recipients(web_client):
    client, deps, alice = web_client
    await _friend(deps, alice)
    r = await client.get("/compose")
    assert r.status_code == 200
    assert 'data-testid="compose-view"' in r.text
    assert 'value="bob"' in r.text  # selectable recipient


# Markers that appear ONLY in base.html. Their presence in an HTMX (innerHTML)
# response is the duplicate-UI bug: the whole console nests inside #results-slot.
_FULL_PAGE_MARKERS = ("app-shell", 'data-testid="nav"', 'data-testid="compose-view"')


async def test_compose_htmx_returns_results_fragment_only(web_client):
    client, deps, alice = web_client
    await _friend(deps, alice)
    r = await client.post(
        "/compose",
        data={"to": ["bob"], "title": "", "message": "thinking of you"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert 'data-testid="send-results"' in r.text
    assert 'data-result-to="bob"' in r.text
    assert 'data-result-status="queued"' in r.text
    # The fragment must NOT carry the base layout -- returning the full page into
    # an hx-swap="innerHTML" target is exactly what duplicated the console.
    for marker in _FULL_PAGE_MARKERS:
        assert marker not in r.text, f"HTMX fragment leaked full-page marker {marker!r}"


async def test_compose_no_js_returns_full_page_with_results(web_client):
    # A plain form POST (no HX-Request header) is the no-JS fallback: the whole
    # page comes back, with results rendered in its slot, shell and nav intact.
    client, deps, alice = web_client
    await _friend(deps, alice)
    r = await client.post("/compose", data={"to": ["bob"], "title": "", "message": "hi"})
    assert r.status_code == 200
    assert 'data-testid="send-results"' in r.text
    assert 'data-result-status="queued"' in r.text
    assert "app-shell" in r.text
    assert 'data-testid="nav"' in r.text


async def test_compose_htmx_multi_recipient_partial(web_client):
    client, deps, alice = web_client
    await _friend(deps, alice, handle="bob")
    # carol exists but is NOT alice's friend
    from hub.invites import create_invite, redeem_invite
    async with deps.sessionmaker() as s:
        await redeem_invite(
            s, code=await create_invite(s, issuer_printer_id=None, ttl_s=3600),
            handle="carol", display_name="Carol")

    r = await client.post(
        "/compose",
        data={"to": ["bob", "carol", "ghost"], "title": "Hi", "message": "hello"},
        headers={"HX-Request": "true"},
    )
    assert 'data-result-to="bob"' in r.text and 'data-result-status="queued"' in r.text
    assert 'data-result-to="carol"' in r.text and 'data-result-status="not_friend"' in r.text
    assert 'data-result-to="ghost"' in r.text and 'data-result-status="recipient_unknown"' in r.text
    for marker in _FULL_PAGE_MARKERS:
        assert marker not in r.text, f"HTMX fragment leaked full-page marker {marker!r}"


async def test_compose_requires_session(app_client):
    client, _ = app_client
    r = await client.get("/compose", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/console/login" in r.headers["location"]


async def test_compose_htmx_post_without_session_redirects_browser(app_client):
    client, _ = app_client
    r = await client.post(
        "/compose",
        data={"to": ["bob"], "title": "", "message": "hi"},
        headers={"HX-Request": "true"},
        follow_redirects=False,
    )
    assert r.status_code == 204
    assert r.headers["HX-Redirect"] == "/console/login"
    assert r.text == ""
