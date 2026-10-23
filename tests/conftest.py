"""Keep the test suite independent of the developer's machine."""
import pytest


@pytest.fixture(autouse=True)
def isolated_native_text_profile(monkeypatch, tmp_path_factory):
    """Point GOOJPRT_PROFILE at a file that does not exist.

    A profile saved by ``goojprt --calibrate`` lives in the user's config
    directory and would otherwise be picked up by every test that goes
    through the CLI.
    """
    monkeypatch.setenv("GOOJPRT_PROFILE", str(tmp_path_factory.getbasetemp() / "no-such-profile.toml"))
