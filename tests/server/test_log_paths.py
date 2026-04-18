from pathlib import Path

import pytest

from goojprt_server.log_paths import default_server_log_path


def test_linux_uses_xdg_state_home(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("XDG_STATE_HOME", "/home/u/.local/state")
    p = default_server_log_path()
    assert p == Path("/home/u/.local/state/goojprt-server/server.log")


def test_linux_falls_back_without_xdg(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    p = default_server_log_path()
    assert p == tmp_path / ".local/state/goojprt-server/server.log"


def test_macos_uses_library_logs(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    p = default_server_log_path()
    assert p == tmp_path / "Library/Logs/goojprt-server/server.log"


def test_windows_uses_localappdata(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\u\AppData\Local")
    p = default_server_log_path()
    # Path equality is filesystem-flavor-sensitive; on POSIX hosts the
    # returned path is a PosixPath whose internal separators differ from
    # a literal raw-string Path. Compare by normalized structure instead.
    s = str(p).replace("\\", "/")
    assert s.endswith("/goojprt-server/logs/server.log")
    assert "C:/Users/u/AppData/Local" in s or r"C:\Users\u\AppData\Local" in str(p)


def test_unknown_platform_falls_back_to_tmp(monkeypatch):
    monkeypatch.setattr("sys.platform", "plan9")
    p = default_server_log_path()
    assert p.name == "server.log"
    assert "goojprt-server" in str(p)
