async def test_all_views_carry_stable_hooks_after_design(web_client):
    """Hallmark restyles freely, but these semantic hooks are load-bearing for
    every other web test. This guards them against being stripped in the redesign."""
    client, deps, alice = web_client
    from hub.invites import create_invite, redeem_invite
    async with deps.sessionmaker() as s:
        await redeem_invite(
            s, code=await create_invite(s, issuer_printer_id=alice.printer_id, ttl_s=3600),
            handle="bob", display_name="Bob")

    friends = await client.get("/")
    compose = await client.get("/compose")
    history = await client.get("/history")
    assert 'data-testid="friends-view"' in friends.text
    assert 'data-friend="bob"' in friends.text
    assert 'data-testid="compose-view"' in compose.text
    assert 'data-testid="recipient-picker"' in compose.text
    assert 'data-testid="history-view"' in history.text


async def test_static_assets_served_locally(web_client):
    """No CDN: HTMX and the stylesheet must be served from /static so the hub
    stays a single deployable."""
    client, _deps, _alice = web_client
    css = await client.get("/static/app.css")
    js = await client.get("/static/htmx.min.js")
    assert css.status_code == 200
    assert js.status_code == 200


async def test_stylesheet_is_designed_not_placeholder(web_client):
    """The design pass must replace the structural placeholder with a real
    stylesheet: the placeholder marker is gone and substantive rules are present
    (a type system and paper-like body treatment), so the views can be visually
    verified at all."""
    client, _deps, _alice = web_client
    css = (await client.get("/static/app.css")).text
    assert "Structural placeholder" not in css
    assert "font-family" in css
    assert "body" in css
    # Hallmark wraps the shell with a branded app frame; the hook must exist so
    # the layout has a stable, restyleable container around every view.
    home = await client.get("/")
    assert 'class="app-shell"' in home.text
