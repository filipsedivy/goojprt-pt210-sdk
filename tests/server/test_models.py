import pytest
from pydantic import ValidationError

from goojprt_server.models import (
    PrintTextRequest,
    PrintQrRequest,
    PrintPdf417Request,
    FeedRequest,
)


def test_text_defaults():
    r = PrintTextRequest(text="hello")
    assert r.align == "left"
    assert r.bold is False
    assert r.size == "normal"
    assert r.bitmap is False
    assert r.font_size == 24
    assert r.encoding == "gb2312"
    assert r.feed_after == 0


def test_text_rejects_empty_and_too_long():
    with pytest.raises(ValidationError):
        PrintTextRequest(text="")
    with pytest.raises(ValidationError):
        PrintTextRequest(text="x" * 10_001)


def test_text_rejects_bad_align():
    with pytest.raises(ValidationError):
        PrintTextRequest(text="ok", align="middle")


def test_qr_bounds():
    PrintQrRequest(data="x", size=1)
    PrintQrRequest(data="x", size=16)
    with pytest.raises(ValidationError):
        PrintQrRequest(data="x", size=0)
    with pytest.raises(ValidationError):
        PrintQrRequest(data="x", size=17)


def test_pdf417_bounds():
    PrintPdf417Request(data="x", scale=1, columns=1, row_height=2)
    with pytest.raises(ValidationError):
        PrintPdf417Request(data="x", scale=7)
    with pytest.raises(ValidationError):
        PrintPdf417Request(data="x", row_height=1)


def test_feed_bounds():
    FeedRequest(lines=1)
    FeedRequest(lines=20)
    with pytest.raises(ValidationError):
        FeedRequest(lines=0)
    with pytest.raises(ValidationError):
        FeedRequest(lines=21)
