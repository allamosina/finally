from __future__ import annotations


async def test_root_serves_index(client):
    r = await client.get("/")
    assert r.status_code == 200 and "INDEX" in r.text


async def test_exact_file(client):
    r = await client.get("/_next/app.js")
    assert r.status_code == 200 and "console.log" in r.text


async def test_html_extension_fallback(client):
    r = await client.get("/about")
    assert r.status_code == 200 and "ABOUT" in r.text


async def test_unknown_path_falls_back_to_index(client):
    r = await client.get("/some/client/route")
    assert r.status_code == 200 and "INDEX" in r.text


async def test_unknown_api_path_is_json_404(client):
    r = await client.get("/api/nope")
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found"}


async def test_traversal_does_not_escape_static_dir(client):
    r = await client.get("/..%2Fsecret.txt")
    assert "SECRET" not in r.text


async def test_missing_build_gives_404(env, tmp_path):
    import httpx

    from app.main import create_app

    app = create_app(static_dir=tmp_path / "nowhere")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            assert (await c.get("/")).status_code == 404
            assert (await c.get("/api/health")).status_code == 200
