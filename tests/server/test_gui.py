async def test_index_renders_html(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "GoojPrt PT-210 Print Server" in r.text
    assert "Queue" in r.text


async def test_post_returns_303_and_location(client, fake_printer):
    r = await client.post(
        "/",
        data={"_type": "text", "text": "hi"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/?job=")


async def test_post_text_bitmap_checkbox(client, fake_printer):
    r = await client.post(
        "/",
        data={"_type": "text", "text": "ě", "bitmap": "on"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    # Eventually print_text_image should be called.
    import asyncio
    for _ in range(200):
        if any(c[0] == "print_text_image" for c in fake_printer.calls):
            break
        await asyncio.sleep(0.01)
    else:
        raise AssertionError("print_text_image was never called")


async def test_post_unknown_type_400(client):
    r = await client.post("/", data={"_type": "bogus"})
    assert r.status_code == 400
