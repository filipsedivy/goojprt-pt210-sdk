"""Tests for goojprt/__main__.py entry point."""
import runpy
from unittest.mock import patch


def test_main_called_when_run_as_module():
    with patch("goojprt.cli.main") as mock_main:
        runpy.run_module("goojprt", run_name="__main__", alter_sys=True)
        mock_main.assert_called_once()
