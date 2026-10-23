"""Native-text profile: which code page (and mode) prints your language correctly.

Low-cost printers differ in which ``ESC t`` tables they ship and whether they
start in a double-byte Chinese mode, so the right combination for Czech or any
other language has to be found once per unit (``goojprt <addr> --calibrate``).
A :class:`TextProfile` records the result:

* the ``ESC t`` code page number,
* the Python codec that produces bytes for that table, and
* whether ``FS .`` must cancel the Chinese mode first.

It is stored as a small TOML file and, once applied to a printer with
:meth:`~goojprt.printer.GoojPrtPT210.apply_profile`, survives ``ESC @`` and
reconnects. Pure and I/O-free apart from :func:`load_profile` /
:func:`save_profile`.
"""

import codecs
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

#: Environment variable that overrides the profile location.
PROFILE_ENV = "GOOJPRT_PROFILE"

#: A sentence that uses every Czech letter with a diacritic (lower and upper case).
CZECH_TEST_TEXT = "ěščřžýáíéó ĚŠČŘŽÝÁÍÉ ůúďťň"


@dataclass(frozen=True)
class TextProfile:
    """A code page / encoding / Chinese-mode combination for native text."""

    #: ``ESC t`` table number (0-255).
    code_page: int
    #: Python codec name that encodes text for that table, e.g. ``"cp852"``.
    encoding: str
    #: Send ``FS .`` first so bytes ≥ 0x80 are single characters.
    chinese_mode_off: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.code_page, bool) or not isinstance(self.code_page, int) \
                or not 0 <= self.code_page <= 255:
            raise ValueError(f"code_page must be an integer 0-255, got {self.code_page!r}")
        try:
            codecs.lookup(self.encoding)
        except (LookupError, TypeError) as exc:
            raise ValueError(f"unknown encoding {self.encoding!r}") from exc
        if not isinstance(self.chinese_mode_off, bool):
            raise ValueError(f"chinese_mode_off must be true or false, got {self.chinese_mode_off!r}")

    def describe(self) -> str:
        """A short human-readable summary."""
        mode = "FS . (Chinese mode off)" if self.chinese_mode_off else "default mode"
        return f"ESC t {self.code_page}, {self.encoding}, {mode}"


#: Combinations worth trying for Czech and other Central European text. The
#: numbers are those of the common ESC/POS tables (escpos-printer-db); slot 16
#: is Windows-1252 there but is tried with cp1250 because this SDK used it for
#: that. Each is tried with and without ``FS .``.
CANDIDATES: tuple[TextProfile, ...] = tuple(
    TextProfile(code_page, encoding, chinese_off)
    for chinese_off in (True, False)
    for code_page, encoding in ((18, "cp852"), (45, "cp1250"), (39, "iso8859_2"), (16, "cp1250"))
)

#: Letters that identify the candidates on a calibration sheet.
CANDIDATE_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[: len(CANDIDATES)]


def candidate_for(letter: str) -> TextProfile:
    """The candidate a calibration sheet labelled ``letter``.

    :raises ValueError: For a letter that is not on the sheet.
    """
    index = CANDIDATE_LETTERS.find(letter.strip().upper()[:1]) if letter.strip() else -1
    if index < 0:
        raise ValueError(f"{letter!r} is not on the sheet; choose one of {', '.join(CANDIDATE_LETTERS)}")
    return CANDIDATES[index]


def default_profile_path() -> Path:
    """Where the profile lives: ``$GOOJPRT_PROFILE``, else the user config directory."""
    override = os.environ.get(PROFILE_ENV)
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "goojprt" / "profile.toml"


def load_profile(path: "str | os.PathLike[str] | None" = None) -> TextProfile | None:
    """Read a profile file.

    :param path: File to read; defaults to :func:`default_profile_path`.
    :returns: The profile, or ``None`` when the file does not exist.
    :raises ValueError: When the file exists but is not a valid profile.
    """
    file = Path(path) if path is not None else default_profile_path()
    try:
        with open(file, "rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        return None
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{file}: not valid TOML: {exc}") from exc
    section = data.get("text")
    if not isinstance(section, dict):
        raise ValueError(f"{file}: missing a [text] table")
    unknown = set(section) - {"code_page", "encoding", "chinese_mode_off"}
    if unknown:
        raise ValueError(f"{file}: unknown keys in [text]: {', '.join(sorted(unknown))}")
    try:
        return TextProfile(
            code_page=section["code_page"],
            encoding=section["encoding"],
            chinese_mode_off=section.get("chinese_mode_off", True),
        )
    except KeyError as exc:
        raise ValueError(f"{file}: [text] needs {exc.args[0]!r}") from exc
    except ValueError as exc:
        raise ValueError(f"{file}: {exc}") from exc


def save_profile(profile: TextProfile, path: "str | os.PathLike[str] | None" = None) -> Path:
    """Write ``profile`` as TOML, creating the directory if needed.

    :returns: The file that was written.
    """
    file = Path(path) if path is not None else default_profile_path()
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(
        "# Native text profile written by `goojprt --calibrate`.\n"
        "# Delete this file to go back to the printer's defaults.\n"
        "[text]\n"
        f"code_page = {profile.code_page}\n"
        f'encoding = "{profile.encoding}"\n'
        f"chinese_mode_off = {'true' if profile.chinese_mode_off else 'false'}\n",
        encoding="utf-8",
    )
    return file
