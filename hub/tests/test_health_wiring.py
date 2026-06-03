def test_package_imports():
    import hub
    assert hub.__version__ == "0.1.0"


async def test_healthz(app_client):
    client, _ = app_client
    r = await client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True}
