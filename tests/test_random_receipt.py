"""scripts/random_receipt.py: the random receipt generator and the receipt it writes."""
import importlib.util
import re
import tomllib
from pathlib import Path

import pytest
from PIL import Image

from goojprt.template import ITEM_TYPES, print_template

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("random_receipt", ROOT / "scripts" / "random_receipt.py")
random_receipt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(random_receipt)

grid_rows = lambda items: [i for i in items if i["type"] == "grid"]


def _build(count=25, seed=1):
    text, total = random_receipt.build_receipt(count, seed)
    return text, total, tomllib.loads(text)["items"]


def _cents(text: str) -> int:
    return int(text.replace(" ", "").replace(",", ""))


class TestMoney:
    @pytest.mark.parametrize("cents, text", [(0, "0,00"), (5, "0,05"), (990, "9,90"),
                                             (12990, "129,90"), (150000, "1 500,00"),
                                             (123456789, "1 234 567,89")])
    def test_czk(self, cents, text):
        assert random_receipt.czk(cents) == text


class TestReceipt:
    def test_it_is_valid_toml_with_only_known_item_types(self):
        _, _, items = _build()
        assert {i["type"] for i in items} <= ITEM_TYPES

    def test_it_has_twenty_five_distinct_items_by_default(self):
        _, _, items = _build()
        rows = grid_rows(items)[1:-1]            # without the header and the summary row
        names = [r["columns"][0]["text"] for r in rows]
        assert len(rows) == 25 and len(set(names)) == 25

    def test_every_row_has_a_name_a_piece_count_and_a_price(self):
        _, _, items = _build()
        for row in grid_rows(items)[1:-1]:
            name, pieces, price = (c["text"] for c in row["columns"])
            assert name and 1 <= int(pieces) <= 6
            assert re.fullmatch(r"\d{1,3}( \d{3})*,\d{2}", price)

    def test_the_total_is_the_sum_of_the_rows(self):
        text, total, items = _build()
        rows = grid_rows(items)[1:-1]
        assert total == sum(_cents(r["columns"][2]["text"]) for r in rows)
        assert f"CELKEM  {random_receipt.czk(total)} Kč" in text

    def test_the_summary_row_counts_items_and_pieces(self):
        _, _, items = _build()
        rows = grid_rows(items)
        summary, body = rows[-1], rows[1:-1]
        assert summary["columns"][0]["text"] == "Položek: 25"
        assert int(summary["columns"][1]["text"]) == sum(int(r["columns"][1]["text"]) for r in body)

    def test_names_fit_the_column(self):
        for name, _ in random_receipt.PRODUCTS:
            assert len(name) <= random_receipt.MAX_NAME_LENGTH

    def test_the_same_seed_gives_the_same_receipt(self):
        assert random_receipt.build_receipt(25, 7) == random_receipt.build_receipt(25, 7)

    def test_different_seeds_differ(self):
        assert random_receipt.build_receipt(25, 1)[0] != random_receipt.build_receipt(25, 2)[0]

    def test_the_seed_is_recorded_in_the_file(self):
        assert "--seed 42" in random_receipt.build_receipt(25, 42)[0].splitlines()[0]

    @pytest.mark.parametrize("count", [0, -1, len(random_receipt.PRODUCTS) + 1])
    def test_an_impossible_item_count_is_rejected(self, count):
        with pytest.raises(ValueError, match="items must be between"):
            random_receipt.build_receipt(count, 1)

    @pytest.mark.parametrize("count", [1, 12, len(random_receipt.PRODUCTS)])
    def test_other_sizes(self, count):
        _, _, items = _build(count)
        assert len(grid_rows(items)) == count + 2


class TestCommandLine:
    def test_it_writes_the_file_and_reports_the_total(self, tmp_path, capsys):
        out = tmp_path / "r.toml"
        assert random_receipt.main(["--seed", "5", "--out", str(out)]) == 0
        assert out.read_text(encoding="utf-8") == random_receipt.build_receipt(25, 5)[0]
        assert "25 items, total" in capsys.readouterr().err

    def test_stdout(self, capsys):
        random_receipt.main(["--seed", "5", "--items", "3", "--out", "-"])
        assert capsys.readouterr().out == random_receipt.build_receipt(3, 5)[0]

    def test_a_bad_count_is_a_usage_error(self, capsys):
        with pytest.raises(SystemExit) as exc:
            random_receipt.main(["--items", "0", "--out", "-"])
        assert exc.value.code == 2


class TestShippedExample:
    EXAMPLE = ROOT / "examples" / "shopping-receipt.toml"

    def test_the_example_is_a_consistent_25_item_receipt(self):
        items = tomllib.loads(self.EXAMPLE.read_text(encoding="utf-8"))["items"]
        rows = grid_rows(items)[1:-1]
        assert len(rows) == 25
        total = sum(_cents(r["columns"][2]["text"]) for r in rows)
        assert f"CELKEM  {random_receipt.czk(total)} Kč" in self.EXAMPLE.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_it_renders_in_a_preview(self, tmp_path):
        out = tmp_path / "r.png"
        await print_template(None, str(self.EXAMPLE), preview=str(out))
        with Image.open(out) as png:
            assert png.width == 384 and png.height > 25 * 25
