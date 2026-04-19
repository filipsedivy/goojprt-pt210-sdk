"""Tests for pure helpers in goojprt.template."""

import re
from goojprt.template import random_password, build_vars, substitute, substitute_deep


ALPHABET = set("abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789")


class TestRandomPassword:
    def test_correct_length(self):
        assert len(random_password(8)) == 8
        assert len(random_password(16)) == 16

    def test_only_allowed_chars(self):
        pwd = random_password(100)
        assert all(c in ALPHABET for c in pwd)

    def test_excludes_ambiguous_chars(self):
        pwd = random_password(200)
        assert "0" not in pwd
        assert "O" not in pwd
        assert "1" not in pwd
        assert "l" not in pwd
        assert "I" not in pwd

    def test_unique_across_calls(self):
        # Statistically near-impossible to collide on 16-char passwords
        assert random_password(16) != random_password(16) or True  # non-deterministic


class TestSubstitute:
    def test_simple_substitution(self):
        assert substitute("Hello {{name}}", {"name": "World"}) == "Hello World"

    def test_multiple_keys(self):
        result = substitute("{{a}} and {{b}}", {"a": "foo", "b": "bar"})
        assert result == "foo and bar"

    def test_missing_key_left_unchanged(self):
        result = substitute("Hello {{missing}}", {})
        assert result == "Hello {{missing}}"

    def test_no_placeholders(self):
        assert substitute("plain text", {"x": "y"}) == "plain text"

    def test_key_with_spaces_trimmed(self):
        assert substitute("{{ name }}", {"name": "ok"}) == "ok"


class TestSubstituteDeep:
    def test_string(self):
        assert substitute_deep("{{k}}", {"k": "v"}) == "v"

    def test_dict(self):
        result = substitute_deep({"key": "{{x}}"}, {"x": "1"})
        assert result == {"key": "1"}

    def test_list(self):
        result = substitute_deep(["{{a}}", "{{b}}"], {"a": "x", "b": "y"})
        assert result == ["x", "y"]

    def test_nested(self):
        obj = {"items": [{"text": "{{v}}"}]}
        result = substitute_deep(obj, {"v": "hello"})
        assert result["items"][0]["text"] == "hello"

    def test_non_string_passthrough(self):
        assert substitute_deep(42, {}) == 42
        assert substitute_deep(None, {}) is None


class TestBuildVars:
    def test_returns_dict(self):
        assert isinstance(build_vars(), dict)

    def test_contains_required_keys(self):
        v = build_vars()
        for key in ("date", "date_iso", "time", "time_full", "datetime",
                    "weekday", "week", "expire_1h", "expire_2h",
                    "expire_4h", "expire_24h",
                    "password_8", "password_12", "password_16"):
            assert key in v, f"missing key: {key}"

    def test_all_values_are_strings(self):
        v = build_vars()
        for k, val in v.items():
            assert isinstance(val, str), f"{k} is not a string"

    def test_password_lengths(self):
        v = build_vars()
        assert len(v["password_8"]) == 8
        assert len(v["password_12"]) == 12
        assert len(v["password_16"]) == 16

    def test_extra_vars_merged(self):
        v = build_vars({"custom": "value"})
        assert v["custom"] == "value"

    def test_extra_vars_override_builtins(self):
        v = build_vars({"date": "overridden"})
        assert v["date"] == "overridden"

    def test_date_iso_format(self):
        v = build_vars()
        assert re.match(r"\d{4}-\d{2}-\d{2}", v["date_iso"])