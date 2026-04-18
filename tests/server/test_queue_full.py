import asyncio

import pytest


async def test_queue_full_returns_503(client, fake_printer):
    # Block the worker by making every write hang.
    gate = asyncio.Event()

    async def hang(**kwargs):
        fake_printer.calls.append(("print_text", kwargs))
        await gate.wait()

    fake_printer.print_text = hang  # type: ignore[method-assign]

    # queue_max_size=3 → first fills the worker, next 3 fill the queue.
    for i in range(4):
        r = await client.post("/api/print/text", json={"text": "x"})
        assert r.status_code == 202
        if i == 0:
            # Let the worker dequeue job #1 and block inside hang() before
            # we fill the remaining queue slots. Python 3.14's asyncio
            # scheduler does not always run the worker between our
            # sequential posts otherwise, which would cause POST #4 (not
            # #5) to hit the 503.
            await asyncio.sleep(0.05)

    r = await client.post("/api/print/text", json={"text": "x"})
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "queue full"
    assert r.json()["detail"]["retry_after_s"] == 2

    gate.set()  # let worker drain so shutdown doesn't hang
