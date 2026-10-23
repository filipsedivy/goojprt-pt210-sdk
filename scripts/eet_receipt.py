"""Generate SPECIMENS of a Czech EET receipt, online and offline, as print templates.

EET (Elektronická evidence tržeb) was in force in the Czech Republic from 2016
and has been abolished since 2023. These receipts are specimens of the layout
for testing a printer, not documents: every one carries an "UKÁZKA – NEPLATNÝ
DOKLAD" banner, the business is fictional and none of the codes is real.

What an EET receipt shows (zákon č. 112/2016 Sb.; the ten items listed by the
Ministry of Finance): FIK, the taxpayer's DIČ, premises, cash register, serial
number, date and time (with seconds), the total including VAT, BKP, the mode
of recording, and the DIČ of a commissioning taxpayer where there is one.

* **Online** (FIK received in time, *běžný* mode): FIK and BKP are printed.
  The FIK is 39 characters, groups 8-4-4-4-12-2. Here it ends in ``-ff``, the
  official marker of the test environment: "the sale was not recorded".
* **Offline** (no answer within the response timeout, still *běžný* mode): no
  FIK exists yet, so the receipt carries the PKP (the signature) and the BKP,
  and the sale is sent afterwards, at the latest within 48 hours. This is not
  the *zjednodušený* mode, which needs approval and allows five days.

PKP and BKP follow vyhláška č. 269/2016 Sb. The PKP is the RSASSA-PKCS1-v1_5
/ SHA-256 signature, in Base64 (344 characters for a 2048-bit key), of
``DIČ|provozovna|pokladna|pořadové číslo|datum a čas|částka`` with the time as
ISO 8601 and the amount with a decimal point. The BKP is the SHA-1 of the
*signature bytes* in Base16, five groups of eight characters (44 characters).
No private key is involved here: the signature is 256 deterministic
pseudo-random bytes, labelled as a specimen on the paper, so the PKP has the
right shape and the BKP is derived from it exactly as the decree says.

The IČ 12345678 is fictional on purpose: its check digit would have to be 9, so
no business can have it. VAT uses today's rates, 21 % and 12 % (during EET it
was 21, 15 and 10 %).

    python scripts/eet_receipt.py                       # examples/eet-online.toml + eet-offline.toml
    python scripts/eet_receipt.py offline --seed 7 --now 2026-10-23T17:04:21+02:00
    goojprt <address> --template examples/eet-online.toml
"""

import argparse
import base64
import hashlib
import random
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parent))
from random_receipt import choose_rows, czk, toml_item, toml_row  # noqa: E402

Mode = Literal["online", "offline"]

ICO = "12345678"                 # fails the IČ check digit rule: belongs to nobody
DIC = f"CZ{ICO}"
PREMISES = 273
CASH_REGISTER = "1"

#: Products that are not food or drink (21 % VAT); everything else is 12 %.
STANDARD_RATE_PRODUCTS = frozenset({
    "Toaletní papír", "Mýdlo tekuté", "Prací gel", "Houbičky na nádobí", "Zubní pasta",
    "Šampon", "Sáčky na odpad", "Ubrousky", "Pivo Gambrinus",
})
STANDARD_RATE, REDUCED_RATE = 21, 12

PKP_BYTES = 256                  # a 2048-bit RSA signature
PKP_CHARS = 344                  # ... in Base64


def signing_string(dic: str, premises: int, register: str, number: int,
                   sale_time: str, total_cents: int) -> str:
    """The text the PKP signs: six fields in the decree's order, joined by ``|``."""
    amount = f"{total_cents // 100}.{total_cents % 100:02d}"
    return "|".join((dic, str(premises), register, str(number), sale_time, amount))


def specimen_signature(plaintext: str) -> bytes:
    """256 deterministic pseudo-random bytes standing in for the RSA signature. Not a signature."""
    out = b""
    counter = 0
    while len(out) < PKP_BYTES:
        out += hashlib.sha256(f"{counter}|{plaintext}".encode("utf-8")).digest()
        counter += 1
    return out[:PKP_BYTES]


def pkp(signature: bytes) -> str:
    """The signature in Base64, as printed on an offline receipt."""
    return base64.b64encode(signature).decode("ascii")


def bkp(signature: bytes) -> str:
    """SHA-1 of the signature *bytes*, Base16, five groups of eight characters."""
    digest = hashlib.sha1(signature).hexdigest().upper()
    return "-".join(digest[i:i + 8] for i in range(0, 40, 8))


def fik(rng: random.Random) -> str:
    """A FIK-shaped code (UUID plus two hex digits) ending in ``ff``: the test-environment marker."""
    return f"{uuid.UUID(int=rng.getrandbits(128), version=4)}-ff"


def vat_rate(name: str) -> int:
    """VAT rate of a product."""
    return STANDARD_RATE if name in STANDARD_RATE_PRODUCTS else REDUCED_RATE


def vat_recap(lines: list[tuple[int, int]]) -> list[tuple[int, int, int, int]]:
    """``(rate, gross, base, vat)`` per rate, the higher rate first, in haléře.

    ``lines`` are ``(rate, gross cents)``. VAT is the rounded (half up) share of
    the rate's gross sum, and ``base + vat == gross`` holds exactly.
    """
    gross_by_rate: dict[int, int] = defaultdict(int)
    for rate, gross in lines:
        gross_by_rate[rate] += gross
    recap = []
    for rate in sorted(gross_by_rate, reverse=True):
        gross = gross_by_rate[rate]
        vat = (2 * gross * rate + (100 + rate)) // (2 * (100 + rate))
        recap.append((rate, gross, gross - vat, vat))
    return recap


def build_eet_receipt(mode: Mode, count: int, seed: int, now: datetime, number: int) -> tuple[str, int]:
    """Return the template text and the total in cents.

    The time is written into the template as text (never ``{{datetime}}``), so
    what is printed is exactly what the codes were derived from.

    :raises ValueError: For an unknown mode or an impossible item count.
    """
    if mode not in ("online", "offline"):
        raise ValueError(f"mode must be online or offline, not {mode!r}")
    rng = random.Random(seed)
    rows = choose_rows(rng, count)
    total = sum(line for _, _, line in rows)
    recap = vat_recap([(vat_rate(name), line) for name, _, line in rows])

    shown_time = now.strftime("%d.%m.%Y %H:%M:%S")
    plaintext = signing_string(DIC, PREMISES, CASH_REGISTER, number, now.isoformat(timespec="seconds"), total)
    signature = specimen_signature(plaintext)

    def text_image(text: str, size: int, align: str = "left", extra: tuple[str, ...] = (),
                   padding: int = 2) -> str:
        return toml_item('type = "text_image"', f'text = "{text}"', f"font_size = {size}",
                         f'align = "{align}"', f"padding = {padding}", *extra)

    def pair(left: str, right: str, size: int = 18) -> str:
        return toml_item('type = "grid"', f"font_size = {size}", "padding = 2", "columns = [",
                         f'  {{ width = 45, align = "left",  text = "{left}" }},',
                         f'  {{ width = 55, align = "right", text = "{right}" }},', "]")

    small = ("dither = false", "threshold = 170")
    banner = text_image("UKÁZKA – NEPLATNÝ DOKLAD", 22, "center")
    kind = "ONLINE – FIK přidělen" if mode == "online" else "OFFLINE – bez FIK, s PKP"

    out = [
        f"# SPECIMEN of an EET receipt, {mode}. Not a valid document: fictional business, invented codes.",
        f"# Generated by scripts/eet_receipt.py {mode} --seed {seed} --now {now.isoformat(timespec='seconds')} (receipt no. {number})",
        "# See that script for what an EET receipt contains and how FIK, BKP and PKP are formed.",
        "",
        banner,
        text_image("Potraviny U Nováků", 28, "center"),
        text_image(f"Dlouhá 12, Praha 1\\nIČ {ICO}   DIČ {DIC}", 16, "center"),
        toml_item('type = "line"'),
        text_image(f"EET účtenka – {kind}", 18, "center"),
        toml_item('type = "line"'),
        pair("Provozovna", str(PREMISES)),
        pair("Pokladna", CASH_REGISTER),
        pair("Účtenka č.", str(number)),
        pair("Datum a čas", shown_time),
        toml_item('type = "line"'),
        toml_row("Položka", "ks", "Cena", font_size=18),
        toml_item('type = "line"'),
    ]
    out += [toml_row(name, str(pieces), czk(line), font_size=18) for name, pieces, line in rows]
    out += [
        toml_item('type = "line"'),
        text_image(f"CELKEM  {czk(total)} Kč", 28, "right", padding=4),
        text_image("Celková částka tržby včetně DPH", 14, "right"),
        toml_item('type = "line"'),
        toml_item('type = "grid"', "font_size = 16", "padding = 2", "columns = [",
                  '  { width = 28, align = "left",  text = "DPH" },',
                  '  { width = 36, align = "right", text = "Základ" },',
                  '  { width = 36, align = "right", text = "Daň" },', "]"),
    ]
    for rate, _gross, base, vat in recap:
        out.append(toml_item('type = "grid"', "font_size = 16", "padding = 2", "columns = [",
                             f'  {{ width = 28, align = "left",  text = "{rate} %" }},',
                             f'  {{ width = 36, align = "right", text = "{czk(base)}" }},',
                             f'  {{ width = 36, align = "right", text = "{czk(vat)}" }},', "]"))
    out += [
        toml_item('type = "line"'),
        pair("Režim tržby", "běžný"),
        toml_item('type = "line"'),
    ]
    if mode == "online":
        out += [
            text_image("FIK:", 15),
            text_image(fik(rng), 14, "left", small),
            text_image("BKP:", 15),
            text_image(bkp(signature), 14, "left", small),
            text_image("Tržba odeslána online, FIK přidělen. Koncovka -ff označuje testovací "
                       "prostředí EET: tržba nebyla zaevidována.", 14, "left", small),
        ]
    else:
        out += [
            text_image("PKP (podpisový kód poplatníka):", 15),
            text_image(pkp(signature), 13, "left", small),
            text_image("BKP:", 15),
            text_image(bkp(signature), 14, "left", small),
            text_image("FIK nebyl přidělen: odpověď nedorazila v mezní době. Tržba se odešle "
                       "dodatečně, nejpozději do 48 hodin. Podpis je ukázkový, nejde o RSA.",
                       14, "left", small),
        ]
    out += [
        toml_item('type = "line"'),
        banner,
        text_image("Nejde o skutečnou evidovanou tržbu. Kódy jsou vymyšlené. EET byla zrušena.",
                   14, "center", small),
        toml_item('type = "feed"', "lines = 4"),
    ]
    return "\n".join(out) + "\n", total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", nargs="?", default="both", choices=["online", "offline", "both"])
    parser.add_argument("--items", type=int, default=7, help="items per receipt (default: 7)")
    parser.add_argument("--seed", type=int, default=None, help="random seed (default: a fresh one)")
    parser.add_argument("--now", default=None, metavar="ISO8601",
                        help="time of the offline receipt, e.g. 2026-10-23T17:04:21+02:00 (default: now)")
    parser.add_argument("--out-dir", type=Path, default=Path(__file__).resolve().parent.parent / "examples",
                        help="where eet-online.toml / eet-offline.toml are written (default: examples/)")
    args = parser.parse_args(argv)

    try:
        now = datetime.fromisoformat(args.now) if args.now else datetime.now().astimezone()
    except ValueError:
        parser.error(f"--now is not an ISO 8601 time: {args.now!r}")
    if now.tzinfo is None:
        now = now.astimezone()
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(1, 1_000_000)
    number = random.Random(seed).randrange(1000, 9000)

    # The online sale happened two minutes before the offline one, with the previous number.
    plan = {"online": (seed, now - timedelta(minutes=2), number), "offline": (seed + 1, now, number + 1)}
    wanted = ["online", "offline"] if args.mode == "both" else [args.mode]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for mode in wanted:
        mode_seed, mode_time, mode_number = plan[mode]
        try:
            text, total = build_eet_receipt(mode, args.items, mode_seed, mode_time, mode_number)
        except ValueError as exc:
            parser.error(str(exc))
        target = args.out_dir / f"eet-{mode}.toml"
        target.write_text(text, encoding="utf-8")
        print(f"{mode}: {args.items} items, total {czk(total)} Kč, no. {mode_number} -> {target}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
