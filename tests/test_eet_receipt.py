"""scripts/eet_receipt.py: specimen EET receipts (online FIK / offline PKP) and their codes."""
import base64
import hashlib
import importlib.util
import random
import re
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image

from goojprt.template import ITEM_TYPES, print_template

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("eet_receipt", ROOT / "scripts" / "eet_receipt.py")
eet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(eet)

NOW = datetime(2026, 10, 23, 17, 4, 21, tzinfo=timezone(timedelta(hours=2)))
FIK_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-ff")
BKP_RE = re.compile(r"[0-9A-F]{8}(-[0-9A-F]{8}){4}")


def build(mode, seed=1, count=7, number=2114, now=NOW):
    text, total = eet.build_eet_receipt(mode, count, seed, now, number)
    return text, total, tomllib.loads(text)["items"]


def texts(items):
    """Every string a receipt prints, in order."""
    out = []
    for item in items:
        if "text" in item:
            out.append(item["text"])
        for column in item.get("columns", []):
            out.append(column["text"])
    return out


META_ROWS = ("Provozovna", "Pokladna", "Účtenka č.", "Datum a čas", "Položka", "DPH", "Režim tržby")


def item_rows(items):
    """The table rows that are goods: (name, pieces, price) columns, without headers and the summary."""
    return [g["columns"] for g in items
            if g["type"] == "grid" and g["columns"][0]["text"] not in META_ROWS
            and g["columns"][1]["text"].isdigit() and not g["columns"][0]["text"].startswith("Položek")]


def ico_is_valid(ico: str) -> bool:
    """Czech IČ check digit: weights 8..2 over the first seven digits."""
    remainder = sum(int(d) * w for d, w in zip(ico[:7], range(8, 1, -1))) % 11
    return int(ico[7]) == {0: 1, 1: 0}.get(remainder, 11 - remainder)


# ── the fictional business ───────────────────────────────────────────────────

def test_the_ico_cannot_belong_to_a_real_business():
    assert not ico_is_valid(eet.ICO)
    assert ico_is_valid("25596641")                 # sanity check of the checker itself
    assert eet.DIC == "CZ" + eet.ICO


# ── PKP / BKP / FIK follow the decree ────────────────────────────────────────

class TestCodes:
    def test_the_signed_string_has_the_decrees_fields_in_order(self):
        assert eet.signing_string("CZ12345678", 273, "1", 2114, "2026-10-23T16:24:10+02:00", 49700) == \
            "CZ12345678|273|1|2114|2026-10-23T16:24:10+02:00|497.00"

    @pytest.mark.parametrize("cents, amount", [(0, "0.00"), (5, "0.05"), (100, "1.00"),
                                               (123456, "1234.56"), (99999999, "999999.99")])
    def test_the_amount_has_a_decimal_point_and_two_places(self, cents, amount):
        assert eet.signing_string("D", 1, "1", 1, "t", cents).endswith("|" + amount)

    def test_the_specimen_signature_is_256_deterministic_bytes(self):
        a = eet.specimen_signature("x")
        assert len(a) == 256 and a == eet.specimen_signature("x")
        assert a != eet.specimen_signature("y")

    def test_pkp_is_344_base64_characters_for_256_bytes(self):
        signature = eet.specimen_signature("x")
        text = eet.pkp(signature)
        assert len(text) == 344 and re.fullmatch(r"[A-Za-z0-9+/]{342}==", text)
        assert base64.b64decode(text) == signature

    def test_bkp_is_sha1_of_the_signature_bytes_in_five_groups(self):
        signature = eet.specimen_signature("x")
        code = eet.bkp(signature)
        assert len(code) == 44 and BKP_RE.fullmatch(code)
        assert code.replace("-", "") == hashlib.sha1(signature).hexdigest().upper()

    def test_bkp_is_not_the_hash_of_the_base64_text(self):
        # The decree hashes the 8-bit signature ("otisk PKP v osmibitovém kódování").
        signature = eet.specimen_signature("x")
        wrong = hashlib.sha1(eet.pkp(signature).encode("ascii")).hexdigest().upper()
        assert eet.bkp(signature).replace("-", "") != wrong

    def test_fik_has_the_39_character_shape_and_the_test_environment_marker(self):
        code = eet.fik(random.Random(1))
        assert len(code) == 39 and FIK_RE.fullmatch(code)
        assert code.endswith("-ff")

    def test_fik_is_deterministic_per_seed_and_differs_between_seeds(self):
        assert eet.fik(random.Random(1)) == eet.fik(random.Random(1))
        assert eet.fik(random.Random(1)) != eet.fik(random.Random(2))


# ── VAT ──────────────────────────────────────────────────────────────────────

class TestVat:
    def test_known_case(self):
        assert eet.vat_recap([(12, 49700)]) == [(12, 49700, 44375, 5325)]

    def test_rates_are_listed_higher_first_and_grouped(self):
        recap = eet.vat_recap([(12, 1000), (21, 2000), (12, 500)])
        assert [r[0] for r in recap] == [21, 12]
        assert recap[1][1] == 1500

    def test_base_plus_vat_is_the_gross_and_vat_is_correctly_rounded(self):
        rng = random.Random(5)
        for _ in range(500):
            lines = [(rng.choice((12, 21)), rng.randrange(10, 400_000)) for _ in range(rng.randrange(1, 12))]
            recap = eet.vat_recap(lines)
            assert sum(r[1] for r in recap) == sum(g for _, g in lines)
            for rate, gross, base, vat in recap:
                assert base + vat == gross
                assert abs(vat * (100 + rate) - gross * rate) <= (100 + rate) / 2     # within half a haléř

    def test_rate_per_product(self):
        assert eet.vat_rate("Toaletní papír") == 21 and eet.vat_rate("Pivo Gambrinus") == 21
        assert eet.vat_rate("Mléko 1 l") == 12
        assert {eet.vat_rate(name) for name, _ in eet.choose_rows.__globals__["PRODUCTS"]} == {12, 21}


# ── the receipts ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mode", ["online", "offline"])
class TestBothModes:
    def test_valid_template_with_known_item_types(self, mode):
        _, _, items = build(mode)
        assert {i["type"] for i in items} <= ITEM_TYPES

    def test_it_is_marked_as_a_specimen_at_the_top_and_the_bottom(self, mode):
        _, _, items = build(mode)
        printed = [i["text"] for i in items if i["type"] == "text_image"]
        assert printed[0] == "UKÁZKA – NEPLATNÝ DOKLAD"
        assert "UKÁZKA – NEPLATNÝ DOKLAD" in printed[-2:]
        assert "Kódy jsou vymyšlené" in printed[-1] and "EET byla zrušena" in printed[-1]

    def test_the_time_is_baked_in_with_seconds_never_a_variable(self, mode):
        text, _, items = build(mode)
        assert "{{" not in text
        assert "23.10.2026 17:04:21" in texts(items)

    def test_the_ten_eet_items_are_there(self, mode):
        _, _, items = build(mode)
        printed = " | ".join(texts(items))
        for needed in ("DIČ CZ12345678", "Provozovna", "273", "Pokladna", "Účtenka č.", "2114",
                       "Datum a čas", "Celková částka tržby včetně DPH", "Režim tržby", "běžný", "BKP:"):
            assert needed in printed, needed

    def test_the_mode_is_beznu_never_zjednoduseny(self, mode):
        text, _, _ = build(mode)
        assert "zjednodušen" not in text.lower()

    def test_the_total_and_the_vat_recap_agree_with_the_rows(self, mode):
        _, total, items = build(mode)
        grids = [i for i in items if i["type"] == "grid"]
        rows = item_rows(items)
        assert len(rows) == 7
        cents = lambda t: int(t.replace(" ", "").replace(",", ""))
        assert sum(cents(r[2]["text"]) for r in rows) == total
        recap = [g["columns"] for g in grids if g["columns"][0]["text"].endswith(" %")]
        assert sum(cents(c[1]["text"]) + cents(c[2]["text"]) for c in recap) == total
        assert any(f"CELKEM  {eet.czk(total)} Kč" == t for t in texts(items))

    def test_it_is_deterministic(self, mode):
        assert build(mode, seed=3) == build(mode, seed=3)
        assert build(mode, seed=3)[0] != build(mode, seed=4)[0]

    def test_the_header_records_how_to_regenerate_it(self, mode):
        header = build(mode, seed=9)[0].splitlines()[1]
        assert f"eet_receipt.py {mode} --seed 9 --now 2026-10-23T17:04:21+02:00 (receipt no. 2114)" in header

    @pytest.mark.parametrize("count", [0, 99])
    def test_an_impossible_item_count_is_rejected(self, mode, count):
        with pytest.raises(ValueError, match="items must be between"):
            eet.build_eet_receipt(mode, count, 1, NOW, 1)


class TestOnline:
    def test_it_prints_a_fik_and_a_bkp_but_no_pkp(self):
        text, _, items = build("online")
        printed = texts(items)
        fiks = [t for t in printed if FIK_RE.fullmatch(t)]
        assert len(fiks) == 1 and fiks[0].endswith("-ff")
        assert sum(1 for t in printed if BKP_RE.fullmatch(t)) == 1
        assert not any(len(t) == 344 for t in printed) and "PKP" not in " ".join(printed)
        assert "ONLINE – FIK přidělen" in " ".join(printed)

    def test_the_bkp_is_derived_from_the_signed_string_of_this_very_receipt(self):
        _, total, items = build("online")
        plaintext = eet.signing_string(eet.DIC, eet.PREMISES, eet.CASH_REGISTER, 2114,
                                       NOW.isoformat(timespec="seconds"), total)
        expected = eet.bkp(eet.specimen_signature(plaintext))
        assert expected in texts(items)

    def test_it_explains_the_test_environment_marker(self):
        assert "-ff" in " ".join(texts(build("online")[2])) and "nebyla zaevidována" in " ".join(texts(build("online")[2]))


class TestOffline:
    def test_it_prints_a_pkp_and_a_bkp_but_no_fik_value(self):
        _, total, items = build("offline")
        printed = texts(items)
        plaintext = eet.signing_string(eet.DIC, eet.PREMISES, eet.CASH_REGISTER, 2114,
                                       NOW.isoformat(timespec="seconds"), total)
        signature = eet.specimen_signature(plaintext)
        assert eet.pkp(signature) in printed
        assert eet.bkp(signature) in printed
        assert not any(FIK_RE.fullmatch(t) for t in printed)
        assert "OFFLINE – bez FIK, s PKP" in " ".join(printed)

    def test_it_says_the_sale_is_sent_later_within_48_hours(self):
        printed = " ".join(texts(build("offline")[2]))
        assert "48 hodin" in printed and "FIK nebyl přidělen" in printed

    def test_it_says_the_signature_is_not_a_real_one(self):
        assert "Podpis je ukázkový" in " ".join(texts(build("offline")[2]))

    def test_the_bkp_matches_the_pkp_printed_next_to_it(self):
        printed = texts(build("offline")[2])
        pkp_text = next(t for t in printed if len(t) == 344)
        bkp_text = next(t for t in printed if BKP_RE.fullmatch(t))
        assert bkp_text == eet.bkp(base64.b64decode(pkp_text))


# ── command line ─────────────────────────────────────────────────────────────

class TestCommandLine:
    ARGS = ["--seed", "4711", "--now", "2026-10-23T17:04:21+02:00"]

    def test_both_receipts_are_written_with_consecutive_numbers_and_times(self, tmp_path, capsys):
        assert eet.main([*self.ARGS, "--out-dir", str(tmp_path)]) == 0
        online = (tmp_path / "eet-online.toml").read_text(encoding="utf-8")
        offline = (tmp_path / "eet-offline.toml").read_text(encoding="utf-8")
        number = random.Random(4711).randrange(1000, 9000)
        assert f"--now 2026-10-23T17:02:21+02:00 (receipt no. {number})" in online      # two minutes earlier
        assert f"--now 2026-10-23T17:04:21+02:00 (receipt no. {number + 1})" in offline
        assert "--seed 4711" in online and "--seed 4712" in offline
        assert capsys.readouterr().err.count("total") == 2

    def test_a_single_mode_writes_one_file(self, tmp_path):
        eet.main(["offline", *self.ARGS, "--out-dir", str(tmp_path)])
        assert [p.name for p in tmp_path.iterdir()] == ["eet-offline.toml"]

    def test_the_output_directory_is_created(self, tmp_path):
        eet.main(["online", *self.ARGS, "--out-dir", str(tmp_path / "a" / "b")])
        assert (tmp_path / "a" / "b" / "eet-online.toml").exists()

    def test_item_count_option(self, tmp_path):
        eet.main(["online", *self.ARGS, "--items", "3", "--out-dir", str(tmp_path)])
        items = tomllib.loads((tmp_path / "eet-online.toml").read_text(encoding="utf-8"))["items"]
        assert len(item_rows(items)) == 3

    def test_a_bad_time_is_a_usage_error(self, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            eet.main(["--now", "yesterday", "--out-dir", str(tmp_path)])
        assert exc.value.code == 2

    def test_a_bad_item_count_is_a_usage_error(self, tmp_path):
        with pytest.raises(SystemExit) as exc:
            eet.main(["--items", "0", "--out-dir", str(tmp_path)])
        assert exc.value.code == 2


# ── the shipped specimens ────────────────────────────────────────────────────

SHIPPED = {mode: ROOT / "examples" / f"eet-{mode}.toml" for mode in ("online", "offline")}


@pytest.mark.parametrize("mode", SHIPPED)
class TestShippedSpecimens:
    def test_the_file_is_exactly_what_its_header_says_the_script_generates(self, mode):
        text = SHIPPED[mode].read_text(encoding="utf-8")
        match = re.search(r"eet_receipt\.py (\w+) --seed (\d+) --now (\S+) \(receipt no\. (\d+)\)", text)
        assert match and match.group(1) == mode
        regenerated, _ = eet.build_eet_receipt(mode, 7, int(match.group(2)),
                                               datetime.fromisoformat(match.group(3)), int(match.group(4)))
        assert text == regenerated

    def test_it_is_clearly_a_specimen(self, mode):
        text = SHIPPED[mode].read_text(encoding="utf-8")
        assert text.splitlines()[0].startswith("# SPECIMEN")
        assert text.count("UKÁZKA – NEPLATNÝ DOKLAD") == 2

    @pytest.mark.asyncio
    async def test_it_renders_in_a_preview(self, mode, tmp_path):
        out = tmp_path / "o.png"
        await print_template(None, str(SHIPPED[mode]), preview=str(out))
        with Image.open(out) as png:
            assert png.width == 384 and png.height > 600
