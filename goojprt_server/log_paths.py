"""Platform-aware resolution of the default server log file path.

Used only when the dashboard is active and the user did not pass
``--log-file``. Non-dashboard modes do not create a log file at all.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def default_server_log_path() -> Path:
    """Return the platform-default location for ``server.log``.

    The parent directory is NOT created here; callers are responsible
    for ``mkdir(parents=True, exist_ok=True)`` before opening the file.
    """
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "goojprt-server" / "server.log"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "goojprt-server" / "logs" / "server.log"
        return Path(tempfile.gettempdir()) / "goojprt-server" / "server.log"
    if sys.platform.startswith("linux"):
        xdg = os.environ.get("XDG_STATE_HOME")
        base = Path(xdg) if xdg else Path.home() / ".local" / "state"
        return base / "goojprt-server" / "server.log"
    return Path(tempfile.gettempdir()) / "goojprt-server" / "server.log"
