"""goojprt.profile: validation, candidates, file format and locations."""
from types import SimpleNamespace

import pytest

from goojprt import profile as profile_module
from goojprt.profile import (
    CANDIDATE_LETTERS,
    CANDIDATES,
    CZECH_TEST_TEXT,
    PROFILE_ENV,
    TextProfile,
    candidate_for,
    default_profile_path,
    load_profile,
    save_profile,
)


class TestTextProfile:
    def test_fields_and_default(self):
        p = TextProfile(18, "cp852")
        assert (p.code_page, p.encoding, p.chinese_mode_off) == (18, "cp852", True)

    @pytest.mark.parametrize("bad", [-1, 256, 1000, "18", 1.5, None, True])
    def test_code_page_must_be_a_byte(self, bad):
        with pytest.raises(ValueError, match="code_page"):
            TextProfile(bad, "cp852")

    @pytest.mark.parametrize("bad", ["no-such-codec", "", None, 5])
    def test_encoding_must_be_a_known_codec(self, bad):
        with pytest.raises(ValueError, match="encoding"):
            TextProfile(18, bad)

    @pytest.mark.parametrize("bad", ["yes", 1, None])
    def test_chinese_mode_flag_must_be_boolean(self, bad):
        with pytest.raises(ValueError, match="chinese_mode_off"):
            TextProfile(18, "cp852", bad)

    def test_it_is_hashable_and_comparable(self):
        assert TextProfile(18, "cp852") == TextProfile(18, "cp852", True)
        assert len({TextProfile(18, "cp852"), TextProfile(18, "cp852")}) == 1

    def test_describe(self):
        assert TextProfile(18, "cp852").describe() == "ESC t 18, cp852, FS . (Chinese mode off)"
        assert TextProfile(45, "cp1250", False).describe() == "ESC t 45, cp1250, default mode"


class TestCandidates:
    def test_every_candidate_is_valid_and_distinct(self):
        assert len(set(CANDIDATES)) == len(CANDIDATES) == 8

    def test_czech_text_survives_the_czech_capable_encodings(self):
        for candidate in CANDIDATES:
            # 16 is tried with cp1250 on purpose; every codec must hold all Czech letters.
            assert CZECH_TEST_TEXT.encode(candidate.encoding)        # no UnicodeEncodeError

    def test_test_text_covers_every_czech_letter_with_a_diacritic(self):
        letters = set("áčďéěíňóřšťúůýž")
        assert letters <= set(CZECH_TEST_TEXT)
        assert set("ĚŠČŘŽÝÁÍÉ") <= set(CZECH_TEST_TEXT)

    def test_letters_match_the_candidates(self):
        assert CANDIDATE_LETTERS == "ABCDEFGH"

    def test_each_page_is_tried_with_and_without_fs_dot(self):
        assert [c.chinese_mode_off for c in CANDIDATES] == [True] * 4 + [False] * 4
        assert [(c.code_page, c.encoding) for c in CANDIDATES[:4]] == \
               [(c.code_page, c.encoding) for c in CANDIDATES[4:]]

    @pytest.mark.parametrize("letter, index", [("A", 0), ("a", 0), (" c ", 2), ("H", 7), ("dx", 3)])
    def test_candidate_for(self, letter, index):
        assert candidate_for(letter) == CANDIDATES[index]

    @pytest.mark.parametrize("letter", ["", " ", "Z", "9", "I", "?"])
    def test_candidate_for_rejects_letters_not_on_the_sheet(self, letter):
        with pytest.raises(ValueError, match="not on the sheet"):
            candidate_for(letter)


class TestLocation:
    def test_environment_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv(PROFILE_ENV, str(tmp_path / "mine.toml"))
        assert default_profile_path() == tmp_path / "mine.toml"

    def test_xdg_config_home(self, monkeypatch, tmp_path):
        monkeypatch.delenv(PROFILE_ENV, raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        assert default_profile_path() == tmp_path / "goojprt" / "profile.toml"

    def test_falls_back_to_dot_config_in_the_home_directory(self, monkeypatch):
        monkeypatch.delenv(PROFILE_ENV, raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        assert default_profile_path().parts[-3:] == (".config", "goojprt", "profile.toml")

    def test_windows_uses_appdata(self, monkeypatch, tmp_path):
        fake_os = SimpleNamespace(name="nt", environ={"APPDATA": str(tmp_path)})
        monkeypatch.setattr(profile_module, "os", fake_os)
        assert default_profile_path() == tmp_path / "goojprt" / "profile.toml"

    def test_tilde_in_the_override_is_expanded(self, monkeypatch):
        monkeypatch.setenv(PROFILE_ENV, "~/x.toml")
        assert "~" not in str(default_profile_path())


class TestFile:
    def test_round_trip(self, tmp_path):
        for original in CANDIDATES:
            file = tmp_path / "p.toml"
            assert save_profile(original, file) == file
            assert load_profile(file) == original

    def test_save_creates_missing_directories(self, tmp_path):
        file = tmp_path / "a" / "b" / "profile.toml"
        save_profile(TextProfile(18, "cp852"), file)
        assert file.is_file()

    def test_the_file_is_readable_and_explains_itself(self, tmp_path):
        file = tmp_path / "p.toml"
        save_profile(TextProfile(45, "cp1250", False), file)
        text = file.read_text(encoding="utf-8")
        assert "[text]" in text and "code_page = 45" in text
        assert 'encoding = "cp1250"' in text and "chinese_mode_off = false" in text
        assert text.startswith("#")

    def test_defaults_come_from_the_environment(self, monkeypatch, tmp_path):
        monkeypatch.setenv(PROFILE_ENV, str(tmp_path / "env.toml"))
        assert load_profile() is None
        save_profile(TextProfile(18, "cp852"))
        assert load_profile() == TextProfile(18, "cp852")
        assert (tmp_path / "env.toml").exists()

    def test_a_missing_file_is_not_an_error(self, tmp_path):
        assert load_profile(tmp_path / "nope.toml") is None

    def test_chinese_mode_defaults_to_off_when_omitted(self, tmp_path):
        file = tmp_path / "p.toml"
        file.write_text('[text]\ncode_page = 18\nencoding = "cp852"\n')
        assert load_profile(file) == TextProfile(18, "cp852", True)

    @pytest.mark.parametrize("content, message", [
        ("this is = not [valid", "not valid TOML"),
        ("[other]\nx = 1\n", r"missing a \[text\] table"),
        ('[text]\nencoding = "cp852"\n', "needs 'code_page'"),
        ("[text]\ncode_page = 18\n", "needs 'encoding'"),
        ('[text]\ncode_page = 999\nencoding = "cp852"\n', "code_page"),
        ('[text]\ncode_page = 18\nencoding = "nope"\n', "unknown encoding"),
        ('[text]\ncode_page = 18\nencoding = "cp852"\nchinese_mode_off = "yes"\n', "chinese_mode_off"),
        ('[text]\ncode_page = 18\nencoding = "cp852"\nextra = 1\n', "unknown keys in"),
    ])
    def test_invalid_files_are_rejected_with_the_path_in_the_message(self, tmp_path, content, message):
        file = tmp_path / "bad.toml"
        file.write_text(content)
        with pytest.raises(ValueError, match=message) as exc:
            load_profile(file)
        assert str(file) in str(exc.value)
