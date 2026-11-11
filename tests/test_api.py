"""Tests of the clients of the CRE regulated tariff grids and the Tempo colors."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import csv
from datetime import date
from decimal import Decimal
from http import HTTPStatus
import io
import logging
from pathlib import Path
import re
from unittest.mock import patch

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.trve_edf.api import (
    CRE_GRID_URLS,
    FALLBACK_TEMPO_URL,
    JOUR_TEMPO_HISTORY_URL,
    REQUEST_TIMEOUT,
    CreConnectionError,
    CreDataError,
    TempoConnectionError,
    TempoDataError,
    TrveEdfError,
    async_fetch_grid,
    async_fetch_tempo_colors,
    parse_grid,
    parse_tempo_history,
)
from custom_components.trve_edf.models import (
    OPTION_PRICES,
    PriceKey,
    TariffGrid,
    TariffOption,
    TariffRow,
    TempoColor,
)

FIXTURES = Path(__file__).parent / "fixtures"
BASE_FIXTURE = "cre_base.csv"
HPHC_FIXTURE = "cre_hphc.csv"
TEMPO_FIXTURE = "cre_tempo.csv"

AUG_2025 = date(2025, 8, 1)
JAN_2026 = date(2026, 1, 31)
FEB_2026 = date(2026, 2, 1)
JUL_2026 = date(2026, 7, 31)
AUG_2026 = date(2026, 8, 1)


def base_row(
    start: date, end: date | None, power: int, subscription: str, price: str
) -> TariffRow:
    """Return a row of the Base option."""
    return TariffRow(
        start=start,
        end=end,
        power_kva=power,
        subscription=Decimal(subscription),
        prices={PriceKey.BASE: Decimal(price)},
    )


def hphc_row(
    start: date,
    end: date | None,
    power: int,
    subscription: str,
    *,
    off_peak: str,
    peak: str,
) -> TariffRow:
    """Return a row of the HP/HC option."""
    return TariffRow(
        start=start,
        end=end,
        power_kva=power,
        subscription=Decimal(subscription),
        prices={
            PriceKey.PEAK: Decimal(peak),
            PriceKey.OFF_PEAK: Decimal(off_peak),
        },
    )


def tempo_row(
    start: date,
    end: date | None,
    power: int,
    subscription: str,
    prices: Mapping[PriceKey, str],
) -> TariffRow:
    """Return a row of the Tempo option."""
    return TariffRow(
        start=start,
        end=end,
        power_kva=power,
        subscription=Decimal(subscription),
        prices={key: Decimal(price) for key, price in prices.items()},
    )


TEMPO_PRICES_FEB_2026: Mapping[PriceKey, str] = {
    PriceKey.BLUE_PEAK: "0.1612",
    PriceKey.BLUE_OFF_PEAK: "0.1325",
    PriceKey.WHITE_PEAK: "0.1871",
    PriceKey.WHITE_OFF_PEAK: "0.1499",
    PriceKey.RED_PEAK: "0.706",
    PriceKey.RED_OFF_PEAK: "0.1575",
}
TEMPO_PRICES_AUG_2026: Mapping[PriceKey, str] = {
    PriceKey.BLUE_PEAK: "0.1654",
    PriceKey.BLUE_OFF_PEAK: "0.1356",
    PriceKey.WHITE_PEAK: "0.1921",
    PriceKey.WHITE_OFF_PEAK: "0.1536",
    PriceKey.RED_PEAK: "0.7295",
    PriceKey.RED_OFF_PEAK: "0.1615",
}

BASE_GRID = TariffGrid(
    option=TariffOption.BASE,
    rows=(
        base_row(AUG_2025, JAN_2026, 3, "141", "0.1952"),
        base_row(AUG_2025, JAN_2026, 6, "185.94", "0.1952"),
        base_row(AUG_2025, JAN_2026, 9, "233.7", "0.1952"),
        base_row(FEB_2026, JUL_2026, 3, "144.5", "0.194"),
        base_row(FEB_2026, JUL_2026, 6, "188.2", "0.194"),
        base_row(FEB_2026, JUL_2026, 9, "235.9", "0.1927"),
        base_row(AUG_2026, None, 3, "145.76", "0.2001"),
        base_row(AUG_2026, None, 6, "190.81", "0.2001"),
        base_row(AUG_2026, None, 9, "239.84", "0.1985"),
    ),
)
"""Content of the Base fixture."""

HPHC_GRID = TariffGrid(
    option=TariffOption.HPHC,
    rows=(
        hphc_row(AUG_2025, JAN_2026, 6, "189.99", off_peak="0.1635", peak="0.2081"),
        hphc_row(AUG_2025, JAN_2026, 9, "239.84", off_peak="0.1635", peak="0.2081"),
        hphc_row(FEB_2026, JUL_2026, 6, "188.24", off_peak="0.1578", peak="0.2065"),
        hphc_row(FEB_2026, JUL_2026, 9, "235.92", off_peak="0.1578", peak="0.2065"),
        hphc_row(AUG_2026, None, 3, "145.7629941", off_peak="0.1589", peak="0.2142"),
        hphc_row(AUG_2026, None, 6, "190.8131821", off_peak="0.1589", peak="0.2142"),
        hphc_row(AUG_2026, None, 9, "239.8378787", off_peak="0.1589", peak="0.2142"),
    ),
)
"""Content of the HP/HC fixture."""

TEMPO_GRID = TariffGrid(
    option=TariffOption.TEMPO,
    rows=(
        tempo_row(FEB_2026, JUL_2026, 9, "233.44", TEMPO_PRICES_FEB_2026),
        tempo_row(AUG_2026, None, 6, "189.9802924", TEMPO_PRICES_AUG_2026),
        tempo_row(AUG_2026, None, 9, "237.3436191", TEMPO_PRICES_AUG_2026),
    ),
)
"""Content of the Tempo fixture."""

GRIDS: Mapping[TariffOption, tuple[str, TariffGrid]] = {
    TariffOption.BASE: (BASE_FIXTURE, BASE_GRID),
    TariffOption.HPHC: (HPHC_FIXTURE, HPHC_GRID),
    TariffOption.TEMPO: (TEMPO_FIXTURE, TEMPO_GRID),
}
"""Fixture file and expected grid of each option."""

BASE_HEADER = "DATE_DEBUT;DATE_FIN;P_SOUSCRITE;PART_FIXE_TTC;PART_VARIABLE_TTC"
BASE_LINE = "01/08/2026;;6;190,81;0,2001"
BASE_ROW = base_row(AUG_2026, None, 6, "190.81", "0.2001")
HPHC_HEADER = (
    "DATE_DEBUT;DATE_FIN;P_SOUSCRITE;PART_FIXE_TTC;"
    "PART_VARIABLE_HC_TTC;PART_VARIABLE_HP_TTC"
)
HPHC_LINE = "2026-08-01;;6;190.8131821;0.1589;0.2142"
HPHC_ROW = hphc_row(AUG_2026, None, 6, "190.8131821", off_peak="0.1589", peak="0.2142")
TEMPO_PRICE_COLUMNS = (
    "PART_VARIABLE_HPBleu_TTC",
    "PART_VARIABLE_HCBleu_TTC",
    "PART_VARIABLE_HPBlanc_TTC",
    "PART_VARIABLE_HCBlanc_TTC",
    "PART_VARIABLE_HPRouge_TTC",
    "PART_VARIABLE_HCRouge_TTC",
)
"""Price columns of the Tempo option, in the order of the price keys."""
TEMPO_HEADER = ";".join(
    ("DATE_DEBUT", "DATE_FIN", "P_SOUSCRITE", "PART_FIXE_TTC", *TEMPO_PRICE_COLUMNS)
)
TEMPO_LINE = "01/08/2026;;6;189,9802924;0,1654;0,1356;0,1921;0,1536;0,7295;0,1615"
TEMPO_ROW = tempo_row(AUG_2026, None, 6, "189.9802924", TEMPO_PRICES_AUG_2026)

REQUIRED_COLUMNS: Mapping[TariffOption, tuple[str, ...]] = {
    TariffOption.BASE: tuple(BASE_HEADER.split(";")),
    TariffOption.HPHC: tuple(HPHC_HEADER.split(";")),
    TariffOption.TEMPO: tuple(TEMPO_HEADER.split(";")),
}
"""Columns that a grid of each option must have."""

API_LOGGER = "custom_components.trve_edf.api"
TODAY = date(2026, 11, 11)
"""Day of the download, for the tests of the invalid past rows."""

INVALID_PAST_LINES = [
    pytest.param(";31/07/2026;6;188,2;0,194", "DATE_DEBUT is empty", id="no start"),
    pytest.param(
        "x/02/2026;31/07/2026;6;188,2;0,194",
        "DATE_DEBUT is not a date: 'x/02/2026'",
        id="invalid start",
    ),
    pytest.param(
        "01/02/2026;31/07/2026;;188,2;0,194", "P_SOUSCRITE is empty", id="no power"
    ),
    pytest.param(
        "01/02/2026;31/07/2026;6 kVA;188,2;0,194",
        "P_SOUSCRITE is not a positive integer: '6 kVA'",
        id="invalid power",
    ),
    pytest.param(
        "01/02/2026;31/07/2026;6;188,2;",
        "PART_VARIABLE_TTC is empty",
        id="some amounts empty",
    ),
    pytest.param(
        "01/02/2026;31/07/2026;6;abc;0,194",
        "PART_FIXE_TTC is not an amount: 'abc'",
        id="invalid amount",
    ),
    pytest.param(
        "01/02/2026;31/07/2026;6;-188,2;0,194",
        "PART_FIXE_TTC is negative: '-188,2'",
        id="negative amount",
    ),
    pytest.param(
        "01/08/2026;31/07/2026;6;188,2;0,194",
        "DATE_FIN 2026-07-31 is before DATE_DEBUT 2026-08-01",
        id="end before start",
    ),
    pytest.param(
        "01/02/2026;31/07/2026;6;188,2;0,194;x",
        "the row has more fields than the header",
        id="more fields",
    ),
    pytest.param(
        "01/02/2026;31/07/2026;6;188,2",
        "the row has fewer fields than the header",
        id="fewer fields",
    ),
    pytest.param(
        "01/02/2026;2026-11-10;6;abc;0,194",
        "PART_FIXE_TTC is not an amount: 'abc'",
        id="ended the day before",
    ),
]
"""Invalid rows of a Base grid that ended before TODAY, with the reason."""


def read_fixture(name: str) -> str:
    """Return the content of a fixture file."""
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_columns(name: str) -> list[str]:
    """Return the columns of a fixture file, in file order."""
    return read_fixture(name).splitlines()[0].split(";")


def warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return the warnings logged by the client."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == API_LOGGER and record.levelno == logging.WARNING
    ]


def csv_text(*lines: str) -> str:
    """Join CSV lines into the content of a file."""
    return "".join(f"{line}\n" for line in lines)


def rewrite(
    text: str, columns: Sequence[str], values: Mapping[str, str] | None = None
) -> str:
    """Rewrite a CSV grid with the given columns, in the given order.

    Args:
        text: Content of the grid.
        columns: Columns to write; the others are left out.
        values: Values of added columns, the same on every row.

    Returns:
        The content of the rewritten grid.
    """
    output = io.StringIO()
    writer = csv.DictWriter(
        output, columns, delimiter=";", lineterminator="\n", extrasaction="ignore"
    )
    writer.writeheader()
    for record in csv.DictReader(io.StringIO(text), delimiter=";"):
        writer.writerow(record | dict(values or {}))
    return output.getvalue()


def to_iso_formats(text: str) -> str:
    """Write the dates as YYYY-MM-DD and the decimals with a dot."""
    text = re.sub(r"\b(\d{2})/(\d{2})/(\d{4})\b", r"\3-\2-\1", text)
    return text.replace(",", ".")


def to_french_formats(text: str) -> str:
    """Write the dates as DD/MM/YYYY and the decimals with a comma."""
    text = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", r"\3/\2/\1", text)
    return text.replace(".", ",")


# Constants and errors.


def test_every_option_has_a_grid_url() -> None:
    """Each option downloads the data.gouv.fr resource of its CRE file."""
    assert set(CRE_GRID_URLS) == set(TariffOption)
    assert CRE_GRID_URLS[TariffOption.BASE] == (
        "https://www.data.gouv.fr/fr/datasets/r/c13d05e5-9e55-4d03-bf7e-042a2ade7e49"
    )
    assert CRE_GRID_URLS[TariffOption.HPHC] == (
        "https://www.data.gouv.fr/fr/datasets/r/f7303b3a-93c7-4242-813d-84919034c416"
    )
    assert CRE_GRID_URLS[TariffOption.TEMPO] == (
        "https://www.data.gouv.fr/fr/datasets/r/0c3d1d36-c412-4620-8566-e5cbb4fa2b5a"
    )


def test_request_timeout() -> None:
    """A whole request is limited to 30 seconds."""
    assert REQUEST_TIMEOUT.total == 30


def test_errors_share_a_base_class() -> None:
    """The errors of the client are errors of the integration."""
    assert issubclass(CreConnectionError, TrveEdfError)
    assert issubclass(CreDataError, TrveEdfError)
    assert not issubclass(CreConnectionError, CreDataError)
    assert not issubclass(CreDataError, CreConnectionError)
    assert issubclass(TempoConnectionError, TrveEdfError)
    assert issubclass(TempoDataError, TrveEdfError)
    assert not issubclass(TempoConnectionError, TempoDataError)
    assert not issubclass(TempoDataError, TempoConnectionError)
    cre_errors = (CreConnectionError, CreDataError)
    assert not issubclass(TempoConnectionError, cre_errors)
    assert not issubclass(TempoDataError, cre_errors)


# Parsing of valid grids.


@pytest.mark.parametrize("option", list(TariffOption))
def test_parse_fixture(option: TariffOption) -> None:
    """Every row of a CRE file is read, in file order, with its TTC amounts."""
    name, expected = GRIDS[option]

    assert parse_grid(option, read_fixture(name)) == expected


@pytest.mark.parametrize("option", list(TariffOption))
def test_prices_cover_the_periods_of_the_option(option: TariffOption) -> None:
    """Each row prices exactly the periods of its option."""
    name, _ = GRIDS[option]

    grid = parse_grid(option, read_fixture(name))

    assert grid.option is option
    assert all(tuple(row.prices) == OPTION_PRICES[option] for row in grid.rows)


def test_peak_and_off_peak_prices_are_not_swapped() -> None:
    """HP is the peak price and HC the off-peak price."""
    grid = parse_grid(TariffOption.HPHC, csv_text(HPHC_HEADER, HPHC_LINE))

    prices = grid.rows[0].prices
    assert prices[PriceKey.PEAK] == Decimal("0.2142")
    assert prices[PriceKey.OFF_PEAK] == Decimal("0.1589")


def test_tempo_prices_are_not_swapped() -> None:
    """Each Tempo price is read from the column of its color and period."""
    grid = parse_grid(TariffOption.TEMPO, csv_text(TEMPO_HEADER, TEMPO_LINE))

    assert grid.rows[0].prices == {
        PriceKey.BLUE_PEAK: Decimal("0.1654"),
        PriceKey.BLUE_OFF_PEAK: Decimal("0.1356"),
        PriceKey.WHITE_PEAK: Decimal("0.1921"),
        PriceKey.WHITE_OFF_PEAK: Decimal("0.1536"),
        PriceKey.RED_PEAK: Decimal("0.7295"),
        PriceKey.RED_OFF_PEAK: Decimal("0.1615"),
    }


def test_amounts_are_exact_decimals() -> None:
    """Amounts are parsed as exact decimals, never through a float."""
    grid = parse_grid(
        TariffOption.BASE,
        csv_text(BASE_HEADER, "01/08/2026;;6;190,8131821000000000000001;0,20010"),
    )

    row = grid.rows[0]
    assert isinstance(row.subscription, Decimal)
    assert str(row.subscription) == "190.8131821000000000000001"
    assert str(row.prices[PriceKey.BASE]) == "0.20010"


@pytest.mark.parametrize(
    ("option", "convert"),
    [
        (TariffOption.BASE, to_iso_formats),
        (TariffOption.HPHC, to_french_formats),
        (TariffOption.TEMPO, to_iso_formats),
    ],
)
def test_date_and_decimal_formats_are_interchangeable(
    option: TariffOption, convert: Callable[[str], str]
) -> None:
    """DD/MM/YYYY and YYYY-MM-DD dates, comma and dot decimals give one grid."""
    name, expected = GRIDS[option]
    text = convert(read_fixture(name))
    assert text != read_fixture(name)

    assert parse_grid(option, text) == expected


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("01/08/2026", "31/07/2027"),
        ("1/8/2026", "31/7/2027"),
        ("2026-08-01", "2027-07-31"),
        ("01/08/2026", "2027-07-31"),
    ],
)
def test_date_formats(start: str, end: str) -> None:
    """Dates are read as DD/MM/YYYY, with or without leading zeros, or ISO."""
    grid = parse_grid(
        TariffOption.BASE, csv_text(BASE_HEADER, f"{start};{end};6;190,81;0,2001")
    )

    assert grid.rows[0].start == date(2026, 8, 1)
    assert grid.rows[0].end == date(2027, 7, 31)


@pytest.mark.parametrize(
    ("subscription", "price", "expected"),
    [
        ("190,81", "0,2001", ("190.81", "0.2001")),
        ("190.81", "0.2001", ("190.81", "0.2001")),
        ("190", "0", ("190", "0")),
        ("+190,81", "0,2001", ("190.81", "0.2001")),
    ],
)
def test_decimal_formats(
    subscription: str, price: str, expected: tuple[str, str]
) -> None:
    """Decimals use a comma or a dot; integers and zero are amounts too."""
    grid = parse_grid(
        TariffOption.BASE,
        csv_text(BASE_HEADER, f"01/08/2026;;6;{subscription};{price}"),
    )

    row = grid.rows[0]
    assert (row.subscription, row.prices[PriceKey.BASE]) == (
        Decimal(expected[0]),
        Decimal(expected[1]),
    )


@pytest.mark.parametrize("option", list(TariffOption))
def test_utf8_byte_order_mark_is_ignored(option: TariffOption) -> None:
    """A byte order mark before the header does not hide the first column."""
    name, expected = GRIDS[option]

    assert parse_grid(option, "﻿" + read_fixture(name)) == expected


@pytest.mark.parametrize("newline", ["\r\n", "\r"])
@pytest.mark.parametrize("option", list(TariffOption))
def test_line_endings(option: TariffOption, newline: str) -> None:
    """Windows and old Mac line endings are read like Unix ones."""
    name, expected = GRIDS[option]

    assert parse_grid(option, read_fixture(name).replace("\n", newline)) == expected


def test_spaces_around_names_and_values_are_ignored() -> None:
    """Spaces and tabs around header names and values, even quoted, are ignored."""
    text = csv_text(
        " DATE_DEBUT ;\tDATE_FIN\t;P_SOUSCRITE  ; PART_FIXE_TTC;PART_VARIABLE_TTC ",
        ' 01/08/2026 ;   ;  6\t; "190,81" ;"0,2001"  ',
    )

    assert parse_grid(TariffOption.BASE, text).rows == (BASE_ROW,)


def test_quoted_values() -> None:
    """Quoted values are read like plain ones."""
    text = csv_text(BASE_HEADER, '"01/08/2026";"";"6";"190,81";"0,2001"')

    assert parse_grid(TariffOption.BASE, text).rows == (BASE_ROW,)


@pytest.mark.parametrize("option", list(TariffOption))
def test_columns_are_read_by_name(option: TariffOption) -> None:
    """The order of the columns does not matter."""
    name, expected = GRIDS[option]
    columns = fixture_columns(name)
    text = rewrite(read_fixture(name), list(reversed(columns)))
    assert text.splitlines()[0] != read_fixture(name).splitlines()[0]

    assert parse_grid(option, text) == expected


@pytest.mark.parametrize("option", list(TariffOption))
def test_extra_columns_are_ignored(option: TariffOption) -> None:
    """Unknown columns, before or after the known ones, are ignored."""
    name, expected = GRIDS[option]
    columns = ["ID", *fixture_columns(name), "COMMENTAIRE"]
    text = rewrite(read_fixture(name), columns, {"ID": "x", "COMMENTAIRE": "y;z"})

    assert parse_grid(option, text) == expected


@pytest.mark.parametrize("option", list(TariffOption))
def test_amounts_without_taxes_are_not_required(option: TariffOption) -> None:
    """Only the TTC amounts are used: the HT columns may be missing."""
    name, expected = GRIDS[option]
    text = rewrite(read_fixture(name), REQUIRED_COLUMNS[option])
    assert "_HT" not in text

    assert parse_grid(option, text) == expected


def test_rows_keep_the_file_order() -> None:
    """Rows are returned in file order, not sorted."""
    header, *lines = read_fixture(BASE_FIXTURE).splitlines()

    grid = parse_grid(TariffOption.BASE, csv_text(header, *reversed(lines)))

    assert grid.rows == tuple(reversed(BASE_GRID.rows))


def test_blank_lines_are_skipped() -> None:
    """Empty lines, lines of spaces and lines of empty cells are skipped."""
    other = "01/08/2026;;9;239,84;0,1985"
    text = csv_text(BASE_HEADER, "", BASE_LINE, "   ", ";;;;", "\t", other, ";;;;;")

    grid = parse_grid(TariffOption.BASE, text)

    assert grid.rows == (BASE_ROW, base_row(AUG_2026, None, 9, "239.84", "0.1985"))


@pytest.mark.parametrize(
    ("option", "header", "gap", "line", "row"),
    [
        pytest.param(
            TariffOption.BASE,
            BASE_HEADER,
            "01/08/2010;31/07/2011;36;;",
            BASE_LINE,
            BASE_ROW,
            id="base",
        ),
        pytest.param(
            TariffOption.HPHC,
            HPHC_HEADER,
            "2010-08-01;2011-07-31;36;;;",
            HPHC_LINE,
            HPHC_ROW,
            id="hphc",
        ),
        pytest.param(
            TariffOption.BASE,
            "DATE_DEBUT;DATE_FIN;P_SOUSCRITE;PART_FIXE_HT;PART_FIXE_TTC;"
            "PART_VARIABLE_HT;PART_VARIABLE_TTC",
            "01/08/2010;31/07/2011;36;123,45;;0,1;",
            "01/08/2026;;6;143,28;190,81;0,1361;0,2001",
            BASE_ROW,
            id="base without TTC amounts",
        ),
        pytest.param(
            TariffOption.BASE,
            BASE_HEADER,
            "01/08/2010;31/07/2011;36",
            BASE_LINE,
            BASE_ROW,
            id="base short row without amounts",
        ),
        pytest.param(
            TariffOption.TEMPO,
            TEMPO_HEADER,
            "01/08/2010;31/07/2011;36;;;;;;;",
            TEMPO_LINE,
            TEMPO_ROW,
            id="tempo",
        ),
    ],
)
def test_rows_without_any_amount_are_skipped(
    option: TariffOption, header: str, gap: str, line: str, row: TariffRow
) -> None:
    """A gap in the history, a row without any TTC amount, is skipped."""
    grid = parse_grid(option, csv_text(header, gap, line, gap))

    assert grid.rows == (row,)


@pytest.mark.parametrize(
    ("header", "line"),
    [
        (BASE_HEADER, f"{BASE_LINE};"),
        (f"{BASE_HEADER};", f"{BASE_LINE};"),
        (f"{BASE_HEADER};", BASE_LINE),
    ],
)
def test_trailing_separators_are_tolerated(header: str, line: str) -> None:
    """A separator at the end of the lines adds no meaningful field."""
    assert parse_grid(TariffOption.BASE, csv_text(header, line)).rows == (BASE_ROW,)


# Invalid grids.


@pytest.mark.parametrize("text", ["", "﻿"])
def test_empty_file(text: str) -> None:
    """A file without a header is rejected."""
    with pytest.raises(CreDataError, match=r"^The CRE tariff grid \(base\) is empty$"):
        parse_grid(TariffOption.BASE, text)


@pytest.mark.parametrize(
    ("option", "column"),
    [
        pytest.param(option, column, id=f"{option}-{column}")
        for option, columns in REQUIRED_COLUMNS.items()
        for column in columns
    ],
)
def test_missing_column(option: TariffOption, column: str) -> None:
    """A grid without one of the required columns is rejected."""
    name, _ = GRIDS[option]
    columns = [other for other in fixture_columns(name) if other != column]
    text = rewrite(read_fixture(name), columns)

    with pytest.raises(
        CreDataError,
        match=rf"^The CRE tariff grid \({option}\) lacks the required columns: "
        rf"{column}$",
    ):
        parse_grid(option, text)


@pytest.mark.parametrize(
    ("option", "name", "missing"),
    [
        (TariffOption.BASE, HPHC_FIXTURE, "PART_VARIABLE_TTC"),
        (TariffOption.BASE, TEMPO_FIXTURE, "PART_VARIABLE_TTC"),
        (TariffOption.HPHC, BASE_FIXTURE, "PART_VARIABLE_HP_TTC, PART_VARIABLE_HC_TTC"),
        (TariffOption.HPHC, TEMPO_FIXTURE, "PART_VARIABLE_HP_TTC, PART_VARIABLE_HC_TTC"),
        (TariffOption.TEMPO, BASE_FIXTURE, ", ".join(TEMPO_PRICE_COLUMNS)),
        (TariffOption.TEMPO, HPHC_FIXTURE, ", ".join(TEMPO_PRICE_COLUMNS)),
    ],
)
def test_grid_of_another_option(option: TariffOption, name: str, missing: str) -> None:
    """The grid of another option lacks the price columns of the option."""
    with pytest.raises(
        CreDataError,
        match=rf"^The CRE tariff grid \({option}\) lacks the required columns: "
        rf"{missing}$",
    ):
        parse_grid(option, read_fixture(name))


def test_not_a_grid() -> None:
    """A file that is not a grid lacks every required column."""
    with pytest.raises(
        CreDataError,
        match=r"lacks the required columns: DATE_DEBUT, DATE_FIN, P_SOUSCRITE, "
        r"PART_FIXE_TTC, PART_VARIABLE_TTC$",
    ):
        parse_grid(TariffOption.BASE, "<!DOCTYPE html>\n<html></html>\n")


def test_duplicate_column() -> None:
    """A required column that appears twice is ambiguous: the grid is rejected."""
    text = csv_text(f"{BASE_HEADER}; PART_VARIABLE_TTC ", f"{BASE_LINE};0,2001")

    with pytest.raises(
        CreDataError,
        match=r"^The CRE tariff grid \(base\) has duplicate columns: "
        r"PART_VARIABLE_TTC$",
    ):
        parse_grid(TariffOption.BASE, text)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(csv_text(BASE_HEADER), id="header only"),
        pytest.param(csv_text(BASE_HEADER, "", ";;;;", "  "), id="blank lines"),
        pytest.param(
            csv_text(BASE_HEADER, "01/08/2010;31/07/2011;36;;"),
            id="rows without amount",
        ),
    ],
)
def test_no_usable_row(text: str) -> None:
    """A grid without any row with amounts is rejected."""
    with pytest.raises(
        CreDataError, match=r"^The CRE tariff grid \(base\) has no usable row$"
    ):
        parse_grid(TariffOption.BASE, text)


@pytest.mark.parametrize(
    ("line", "message"),
    [
        pytest.param(";;6;190,81;0,2001", "DATE_DEBUT is empty", id="no start"),
        pytest.param(
            "2026/08/01;;6;190,81;0,2001",
            "DATE_DEBUT is not a date: '2026/08/01'",
            id="start format",
        ),
        pytest.param(
            "01-08-2026;;6;190,81;0,2001",
            "DATE_DEBUT is not a date: '01-08-2026'",
            id="start with dashes",
        ),
        pytest.param(
            "01/08/26;;6;190,81;0,2001",
            "DATE_DEBUT is not a date: '01/08/26'",
            id="start with a short year",
        ),
        pytest.param(
            "31/02/2026;;6;190,81;0,2001",
            "DATE_DEBUT is not a valid date: '31/02/2026'",
            id="impossible start",
        ),
        pytest.param(
            "2026-13-01;;6;190,81;0,2001",
            "DATE_DEBUT is not a valid date: '2026-13-01'",
            id="impossible ISO start",
        ),
        pytest.param(
            "01/08/2026;soon;6;190,81;0,2001",
            "DATE_FIN is not a date: 'soon'",
            id="end format",
        ),
        pytest.param(
            "01/08/2026;31/07/2026;6;190,81;0,2001",
            "DATE_FIN 2026-07-31 is before DATE_DEBUT 2026-08-01",
            id="end before start",
        ),
        pytest.param(
            "01/08/2026;;;190,81;0,2001", "P_SOUSCRITE is empty", id="no power"
        ),
        pytest.param(
            "01/08/2026;;6 kVA;190,81;0,2001",
            "P_SOUSCRITE is not a positive integer: '6 kVA'",
            id="power with unit",
        ),
        pytest.param(
            "01/08/2026;;6,5;190,81;0,2001",
            "P_SOUSCRITE is not a positive integer: '6,5'",
            id="decimal power",
        ),
        pytest.param(
            "01/08/2026;;-6;190,81;0,2001",
            "P_SOUSCRITE is not a positive integer: '-6'",
            id="negative power",
        ),
        pytest.param(
            "01/08/2026;;0;190,81;0,2001",
            "P_SOUSCRITE is not a positive integer: '0'",
            id="zero power",
        ),
        pytest.param(
            "01/08/2026;;6;;0,2001", "PART_FIXE_TTC is empty", id="no subscription"
        ),
        pytest.param(
            "01/08/2026;;6;190,81;", "PART_VARIABLE_TTC is empty", id="no price"
        ),
        pytest.param(
            "01/08/2026;;6;abc;0,2001",
            "PART_FIXE_TTC is not an amount: 'abc'",
            id="subscription text",
        ),
        pytest.param(
            "01/08/2026;;6;1 190,81;0,2001",
            "PART_FIXE_TTC is not an amount: '1 190,81'",
            id="thousands separator",
        ),
        pytest.param(
            "01/08/2026;;6;190,81;0,20.01",
            "PART_VARIABLE_TTC is not an amount: '0,20.01'",
            id="two decimal separators",
        ),
        pytest.param(
            "01/08/2026;;6;190,81;0,2001 €",
            "PART_VARIABLE_TTC is not an amount: '0,2001 €'",
            id="price with unit",
        ),
        pytest.param(
            "01/08/2026;;6;190,81;NaN",
            "PART_VARIABLE_TTC is not an amount: 'NaN'",
            id="not a number",
        ),
        pytest.param(
            "01/08/2026;;6;190,81;Infinity",
            "PART_VARIABLE_TTC is not an amount: 'Infinity'",
            id="infinity",
        ),
        pytest.param(
            "01/08/2026;;6;190,81;2e-1",
            "PART_VARIABLE_TTC is not an amount: '2e-1'",
            id="exponent",
        ),
        pytest.param(
            "01/08/2026;;6;190,81;,2001",
            "PART_VARIABLE_TTC is not an amount: ',2001'",
            id="no integer part",
        ),
        pytest.param(
            "01/08/2026;;6;-190,81;0,2001",
            "PART_FIXE_TTC is negative: '-190,81'",
            id="negative subscription",
        ),
        pytest.param(
            "01/08/2026;;6;190,81;-0,2001",
            "PART_VARIABLE_TTC is negative: '-0,2001'",
            id="negative price",
        ),
        pytest.param(
            "01/08/2026;;6;190,81;-0",
            "PART_VARIABLE_TTC is negative: '-0'",
            id="negative zero",
        ),
        pytest.param(
            "01/08/2026;;6;190,81;0,2001;0,1",
            "the row has more fields than the header",
            id="more fields",
        ),
        pytest.param(
            "01/08/2026;;6;190,81",
            "the row has fewer fields than the header",
            id="fewer fields",
        ),
    ],
)
def test_invalid_row(line: str, message: str) -> None:
    """One invalid row rejects the whole grid, with the line of the error."""
    text = csv_text(BASE_HEADER, BASE_LINE, line, BASE_LINE)

    with pytest.raises(
        CreDataError,
        match=rf"^Line 3 of the CRE tariff grid \(base\): {re.escape(message)}",
    ):
        parse_grid(TariffOption.BASE, text)


@pytest.mark.parametrize(
    ("line", "message"),
    [
        pytest.param(
            "2026-08-01;;6;190.8131821;0.1589;",
            "PART_VARIABLE_HP_TTC is empty",
            id="no peak price",
        ),
        pytest.param(
            "2026-08-01;;6;190.8131821;;0.2142",
            "PART_VARIABLE_HC_TTC is empty",
            id="no off-peak price",
        ),
        pytest.param(
            "2026-08-01;;6;;0.1589;0.2142",
            "PART_FIXE_TTC is empty",
            id="no subscription",
        ),
        pytest.param(
            "2026-08-01;;6;190.8131821;-0.1589;0.2142",
            "PART_VARIABLE_HC_TTC is negative: '-0.1589'",
            id="negative off-peak price",
        ),
        pytest.param(
            "2026-08-01;;6;190.8131821;0.1589;x",
            "PART_VARIABLE_HP_TTC is not an amount: 'x'",
            id="invalid peak price",
        ),
    ],
)
def test_invalid_hphc_row(line: str, message: str) -> None:
    """A row with only some of its amounts is rejected."""
    with pytest.raises(
        CreDataError,
        match=rf"^Line 2 of the CRE tariff grid \(hphc\): {re.escape(message)}$",
    ):
        parse_grid(TariffOption.HPHC, csv_text(HPHC_HEADER, line))


@pytest.mark.parametrize(
    ("line", "message"),
    [
        pytest.param(
            "01/08/2026;;6;189,9802924;0,1654;0,1356;0,1921;0,1536;;0,1615",
            "PART_VARIABLE_HPRouge_TTC is empty",
            id="no red peak price",
        ),
        pytest.param(
            "01/08/2026;;6;189,9802924;0,1654;;0,1921;0,1536;0,7295;0,1615",
            "PART_VARIABLE_HCBleu_TTC is empty",
            id="no blue off-peak price",
        ),
        pytest.param(
            "01/08/2026;;6;189,9802924;0,1654;0,1356;0,1921;-0,1536;0,7295;0,1615",
            "PART_VARIABLE_HCBlanc_TTC is negative: '-0,1536'",
            id="negative white off-peak price",
        ),
        pytest.param(
            "01/08/2026;;6;189,9802924;0,1654;0,1356;x;0,1536;0,7295;0,1615",
            "PART_VARIABLE_HPBlanc_TTC is not an amount: 'x'",
            id="invalid white peak price",
        ),
    ],
)
def test_invalid_tempo_row(line: str, message: str) -> None:
    """A Tempo row with only some of its six prices is rejected."""
    with pytest.raises(
        CreDataError,
        match=rf"^Line 2 of the CRE tariff grid \(tempo\): {re.escape(message)}$",
    ):
        parse_grid(TariffOption.TEMPO, csv_text(TEMPO_HEADER, line))


def test_missing_end_is_not_taken_as_in_force() -> None:
    """A row cut before its end date is rejected, not taken as in force."""
    header = "DATE_DEBUT;P_SOUSCRITE;PART_FIXE_TTC;PART_VARIABLE_TTC;DATE_FIN"
    text = csv_text(
        header, "01/08/2025;6;185,94;0,1952;31/01/2026", "01/08/2025;6;185,94;0,1952"
    )

    with pytest.raises(
        CreDataError,
        match=r"^Line 3 of the CRE tariff grid \(base\): the row has fewer fields "
        r"than the header$",
    ):
        parse_grid(TariffOption.BASE, text)


def test_invalid_csv() -> None:
    """An error of the CSV reader is reported as invalid data."""
    huge = '"' + "0" * 200_000 + '"'
    text = csv_text(BASE_HEADER, BASE_LINE, f"01/08/2026;;6;190,81;{huge}")

    with pytest.raises(
        CreDataError, match=r"^The CRE tariff grid \(base\) is not valid CSV, line 3: "
    ) as error:
        parse_grid(TariffOption.BASE, text)

    assert isinstance(error.value.__cause__, csv.Error)


# Invalid rows that ended before the day of the download.


@pytest.mark.parametrize(("line", "reason"), INVALID_PAST_LINES)
def test_invalid_past_row_is_skipped(
    caplog: pytest.LogCaptureFixture, line: str, reason: str
) -> None:
    """An invalid row that ended before today cannot affect a price: it is skipped."""
    text = csv_text(BASE_HEADER, BASE_LINE, line)

    grid = parse_grid(TariffOption.BASE, text, today=TODAY)

    assert grid.rows == (BASE_ROW,)
    assert warnings(caplog) == [
        "Skipped 1 invalid row(s) of the CRE tariff grid (base) that ended before "
        f"2026-11-11; first at line 3: {reason}"
    ]


@pytest.mark.parametrize(("line", "reason"), INVALID_PAST_LINES)
def test_invalid_past_row_without_today(line: str, reason: str) -> None:
    """Without the current day, an invalid past row still rejects the grid."""
    text = csv_text(BASE_HEADER, BASE_LINE, line)

    with pytest.raises(
        CreDataError,
        match=rf"^Line 3 of the CRE tariff grid \(base\): {re.escape(reason)}$",
    ):
        parse_grid(TariffOption.BASE, text)


def test_skipped_rows_are_logged_once(caplog: pytest.LogCaptureFixture) -> None:
    """One warning gives the number of skipped rows and the first of them."""
    text = csv_text(
        BASE_HEADER,
        "01/02/2025;31/07/2025;6;188,2;",
        BASE_LINE,
        ";31/07/2026;6;188,2;0,194",
        "01/02/2026;31/07/2026;6;abc;0,194",
    )

    grid = parse_grid(TariffOption.BASE, text, today=TODAY)

    assert grid.rows == (BASE_ROW,)
    assert warnings(caplog) == [
        "Skipped 3 invalid row(s) of the CRE tariff grid (base) that ended before "
        "2026-11-11; first at line 2: PART_VARIABLE_TTC is empty"
    ]


@pytest.mark.parametrize("option", list(TariffOption))
def test_valid_past_rows_are_kept(
    caplog: pytest.LogCaptureFixture, option: TariffOption
) -> None:
    """Only the invalid past rows are skipped; nothing is logged otherwise."""
    name, expected = GRIDS[option]

    assert parse_grid(option, read_fixture(name), today=TODAY) == expected
    assert warnings(caplog) == []


@pytest.mark.parametrize(
    ("header", "line", "message"),
    [
        pytest.param(
            BASE_HEADER,
            "01/02/2026;11/11/2026;6;abc;0,194",
            "PART_FIXE_TTC is not an amount: 'abc'",
            id="ends today",
        ),
        pytest.param(
            BASE_HEADER,
            "01/02/2026;31/12/2026;6;188,2;",
            "PART_VARIABLE_TTC is empty",
            id="ends later",
        ),
        pytest.param(
            BASE_HEADER,
            "01/02/2026;;6;-188,2;0,194",
            "PART_FIXE_TTC is negative: '-188,2'",
            id="in force",
        ),
        pytest.param(
            BASE_HEADER,
            "01/02/2026;soon;6;188,2;0,194",
            "DATE_FIN is not a date: 'soon'",
            id="unreadable end",
        ),
        pytest.param(
            BASE_HEADER,
            "01/02/2026;31/02/2026;6;188,2;0,194",
            "DATE_FIN is not a valid date: '31/02/2026'",
            id="impossible end",
        ),
        pytest.param(
            "DATE_DEBUT;P_SOUSCRITE;PART_FIXE_TTC;PART_VARIABLE_TTC;DATE_FIN",
            "01/02/2026;6;188,2;0,194",
            "the row has fewer fields than the header",
            id="no end cell",
        ),
    ],
)
def test_invalid_row_that_may_apply_rejects_the_grid(
    caplog: pytest.LogCaptureFixture, header: str, line: str, message: str
) -> None:
    """An invalid row that does not provably end before today is still an error."""
    text = csv_text(header, line)

    with pytest.raises(
        CreDataError,
        match=rf"^Line 2 of the CRE tariff grid \(base\): {re.escape(message)}",
    ):
        parse_grid(TariffOption.BASE, text, today=TODAY)

    assert warnings(caplog) == []


def test_all_rows_skipped_is_no_usable_row(caplog: pytest.LogCaptureFixture) -> None:
    """A grid whose rows are all skipped has no usable row."""
    text = csv_text(
        BASE_HEADER, ";31/07/2026;6;188,2;0,194", "01/08/2010;31/07/2011;36;;"
    )

    with pytest.raises(
        CreDataError, match=r"^The CRE tariff grid \(base\) has no usable row$"
    ):
        parse_grid(TariffOption.BASE, text, today=TODAY)

    assert len(warnings(caplog)) == 1


@pytest.mark.parametrize(
    ("option", "text", "message"),
    [
        pytest.param(TariffOption.BASE, "", "is empty", id="empty"),
        pytest.param(
            TariffOption.BASE,
            read_fixture(HPHC_FIXTURE),
            "lacks the required columns: PART_VARIABLE_TTC",
            id="another option",
        ),
        pytest.param(
            TariffOption.HPHC,
            "<!DOCTYPE html>\n<html></html>\n",
            "lacks the required columns",
            id="HTML page",
        ),
        pytest.param(
            TariffOption.BASE,
            csv_text(f"{BASE_HEADER};PART_FIXE_TTC", f"{BASE_LINE};190,81"),
            "has duplicate columns: PART_FIXE_TTC",
            id="duplicate column",
        ),
        pytest.param(
            TariffOption.BASE,
            csv_text(BASE_HEADER, f'01/02/2026;31/07/2026;6;188,2;"{"0" * 200_000}"'),
            "is not valid CSV",
            id="invalid CSV",
        ),
    ],
)
def test_grid_errors_do_not_depend_on_today(
    option: TariffOption, text: str, message: str
) -> None:
    """Errors about the whole file are raised whatever the current day."""
    with pytest.raises(CreDataError, match=re.escape(message)):
        parse_grid(option, text, today=TODAY)


# Download of the grids.


@pytest.mark.parametrize("option", list(TariffOption))
async def test_fetch_grid(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, option: TariffOption
) -> None:
    """The grid of the option is downloaded from its URL and parsed."""
    name, expected = GRIDS[option]
    aioclient_mock.get(CRE_GRID_URLS[option], content=(FIXTURES / name).read_bytes())

    grid = await async_fetch_grid(async_get_clientsession(hass), option)

    assert grid == expected
    assert aioclient_mock.call_count == 1
    assert str(aioclient_mock.mock_calls[0][1]) == CRE_GRID_URLS[option]


async def test_fetch_grid_request_options(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The request has a timeout and follows the redirect to the CRE website."""
    url = CRE_GRID_URLS[TariffOption.BASE]
    aioclient_mock.get(url, content=(FIXTURES / BASE_FIXTURE).read_bytes())
    session = async_get_clientsession(hass)

    with patch.object(
        aiohttp.ClientSession,
        "get",
        autospec=True,
        side_effect=aiohttp.ClientSession.get,
    ) as get:
        await async_fetch_grid(session, TariffOption.BASE)

    get.assert_called_once_with(
        session, url, timeout=REQUEST_TIMEOUT, allow_redirects=True
    )


async def test_fetch_grid_skips_invalid_past_rows(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The current day is passed on to the parsing of the grid."""
    content = csv_text(BASE_HEADER, "01/02/2026;31/07/2026;6;abc;0,194", BASE_LINE)
    aioclient_mock.get(CRE_GRID_URLS[TariffOption.BASE], content=content.encode())
    session = async_get_clientsession(hass)

    with pytest.raises(CreDataError, match="PART_FIXE_TTC is not an amount"):
        await async_fetch_grid(session, TariffOption.BASE)
    grid = await async_fetch_grid(session, TariffOption.BASE, today=TODAY)

    assert grid.rows == (BASE_ROW,)


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"\xef\xbb\xbf" + read_fixture(BASE_FIXTURE).encode(), id="BOM"),
        pytest.param(
            rewrite(
                read_fixture(BASE_FIXTURE),
                [*fixture_columns(BASE_FIXTURE), "LIBELLE"],
                {"LIBELLE": "Électricité réglementée, prix en €"},
            ).encode("utf-8"),
            id="UTF-8",
        ),
        pytest.param(
            rewrite(
                read_fixture(BASE_FIXTURE),
                [*fixture_columns(BASE_FIXTURE), "LIBELLE"],
                {"LIBELLE": "Électricité réglementée, prix en €"},
            ).encode("cp1252"),
            id="Windows-1252",
        ),
    ],
)
async def test_fetch_grid_encodings(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, content: bytes
) -> None:
    """The body is read as UTF-8, with or without BOM, else as Windows-1252."""
    aioclient_mock.get(CRE_GRID_URLS[TariffOption.BASE], content=content)

    grid = await async_fetch_grid(async_get_clientsession(hass), TariffOption.BASE)

    assert grid == BASE_GRID


async def test_fetch_grid_windows_1252_is_not_utf8(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A Windows-1252 body is decoded with the fallback, which is logged."""
    text = csv_text(f"{BASE_HEADER};LIBELLE", f"{BASE_LINE};Été")
    content = text.encode("cp1252")
    with pytest.raises(UnicodeDecodeError):
        content.decode("utf-8")
    aioclient_mock.get(CRE_GRID_URLS[TariffOption.BASE], content=content)
    caplog.set_level("DEBUG", logger="custom_components.trve_edf.api")

    grid = await async_fetch_grid(async_get_clientsession(hass), TariffOption.BASE)

    assert grid.rows == (BASE_ROW,)
    assert "decoded as Windows-1252" in caplog.text


async def test_fetch_grid_undecodable(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A body that is neither UTF-8 nor Windows-1252 is invalid data."""
    content = csv_text(f"{BASE_HEADER};LIBELLE", f"{BASE_LINE};").encode() + b"\x81\n"
    aioclient_mock.get(CRE_GRID_URLS[TariffOption.BASE], content=content)

    with pytest.raises(
        CreDataError,
        match=r"^The CRE tariff grid \(base\) is neither UTF-8 nor Windows-1252 text$",
    ) as error:
        await async_fetch_grid(async_get_clientsession(hass), TariffOption.BASE)

    assert isinstance(error.value.__cause__, UnicodeDecodeError)


@pytest.mark.parametrize(
    "status",
    [HTTPStatus.BAD_REQUEST, HTTPStatus.NOT_FOUND, HTTPStatus.INTERNAL_SERVER_ERROR],
)
async def test_fetch_grid_http_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status: HTTPStatus
) -> None:
    """An HTTP error status is a connection error, whatever the body."""
    aioclient_mock.get(
        CRE_GRID_URLS[TariffOption.HPHC],
        status=status,
        content=(FIXTURES / HPHC_FIXTURE).read_bytes(),
    )

    with pytest.raises(
        CreConnectionError,
        match=rf"^The CRE tariff grid \(hphc\) could not be downloaded: "
        rf"HTTP status {status.value}$",
    ):
        await async_fetch_grid(async_get_clientsession(hass), TariffOption.HPHC)


@pytest.mark.parametrize(
    ("exception", "reason"),
    [
        pytest.param(
            aiohttp.ClientConnectionError("Connection refused"),
            "Connection refused",
            id="connection",
        ),
        pytest.param(
            aiohttp.ClientPayloadError("Response payload is not completed"),
            "Response payload is not completed",
            id="payload",
        ),
        pytest.param(TimeoutError(), "TimeoutError", id="timeout"),
    ],
)
async def test_fetch_grid_connection_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    exception: Exception,
    reason: str,
) -> None:
    """Network errors and timeouts are connection errors, chained to the cause."""
    aioclient_mock.get(CRE_GRID_URLS[TariffOption.BASE], exc=exception)

    with pytest.raises(
        CreConnectionError,
        match=rf"^The CRE tariff grid \(base\) could not be downloaded: "
        rf"{re.escape(reason)}",
    ) as error:
        await async_fetch_grid(async_get_clientsession(hass), TariffOption.BASE)

    assert error.value.__cause__ is exception


async def test_fetch_grid_connection_lost_while_reading(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A connection lost while reading the body is a connection error."""
    aioclient_mock.get(
        CRE_GRID_URLS[TariffOption.BASE],
        content=(FIXTURES / BASE_FIXTURE).read_bytes(),
        closing=True,
    )

    with pytest.raises(
        CreConnectionError,
        match=r"^The CRE tariff grid \(base\) could not be downloaded: "
        r"Connection closed$",
    ) as error:
        await async_fetch_grid(async_get_clientsession(hass), TariffOption.BASE)

    assert isinstance(error.value.__cause__, aiohttp.ClientConnectionError)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        pytest.param(b"", "is empty", id="empty"),
        pytest.param(
            b"<!DOCTYPE html><html><body>Maintenance</body></html>",
            "lacks the required columns",
            id="HTML page",
        ),
        pytest.param(
            csv_text(BASE_HEADER, "01/08/2026;;6;190,81;-0,2001").encode(),
            "PART_VARIABLE_TTC is negative",
            id="invalid row",
        ),
    ],
)
async def test_fetch_grid_invalid_content(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    content: bytes,
    message: str,
) -> None:
    """An invalid body is invalid data, not a connection error."""
    aioclient_mock.get(CRE_GRID_URLS[TariffOption.BASE], content=content)

    with pytest.raises(CreDataError, match=re.escape(message)) as error:
        await async_fetch_grid(async_get_clientsession(hass), TariffOption.BASE)

    assert not isinstance(error.value, CreConnectionError)


# Tempo colors: constants.

HISTORY_FIXTURE = "jourtempo_history.csv"
HISTORY_HEADER = "date,couleur,saison"
YESTERDAY = date(2026, 11, 10)
TOMORROW = date(2026, 11, 12)
DAYS = (YESTERDAY, TODAY, TOMORROW)
"""Days asked by the integration: yesterday, today and tomorrow."""
KNOWN_COLORS = {YESTERDAY: TempoColor.BLUE, TODAY: TempoColor.BLUE}
"""Colors of DAYS in the history fixture: tomorrow is not published yet."""
WHITE_DAY = date(2026, 1, 9)
RED_DAY = date(2026, 1, 10)
FIXTURE_COLORS = {
    WHITE_DAY: TempoColor.WHITE,
    RED_DAY: TempoColor.RED,
    **{date(2026, 11, day): TempoColor.BLUE for day in range(7, 12)},
}
"""Content of the history fixture."""

FALLBACK_LABELS = {1: "Bleu", 2: "Blanc", 3: "Rouge"}


def history_text(*lines: str, header: str = HISTORY_HEADER) -> str:
    """Return a history with the given lines after its header."""
    return csv_text(header, *lines)


def fallback_url(day: date) -> str:
    """Return the URL of the color of a day on the fallback source."""
    return FALLBACK_TEMPO_URL.format(day=day.isoformat())


def fallback_answer(day: date, code: int) -> dict[str, object]:
    """Return the answer of the fallback source for a day."""
    answer: dict[str, object] = {
        "dateJour": day.isoformat(),
        "codeJour": code,
        "periode": "2026-2027" if day >= date(2026, 9, 1) else "2025-2026",
    }
    if code in FALLBACK_LABELS:
        answer["libCouleur"] = FALLBACK_LABELS[code]
    return answer


def mock_fallback(
    aioclient_mock: AiohttpClientMocker, codes: Mapping[date, int] | None = None
) -> None:
    """Mock the fallback source; by default, the colors of DAYS are KNOWN_COLORS."""
    if codes is None:
        codes = {YESTERDAY: 1, TODAY: 1, TOMORROW: 0}
    for day, code in codes.items():
        aioclient_mock.get(fallback_url(day), json=fallback_answer(day, code))


def requested_urls(aioclient_mock: AiohttpClientMocker) -> list[str]:
    """Return the URLs requested, in order."""
    return [str(call[1]) for call in aioclient_mock.mock_calls]


def exception_chain(error: BaseException) -> list[BaseException]:
    """Return an error and its causes and contexts, as shown by a traceback."""
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


# Tempo colors: constants and errors.


def test_tempo_urls() -> None:
    """The colors come from Jour Tempo, else from api-couleur-tempo.fr."""
    assert JOUR_TEMPO_HISTORY_URL == "https://jourtempo.fr/api/v1/tempo-historique.csv"
    assert fallback_url(TODAY) == (
        "https://www.api-couleur-tempo.fr/api/jourTempo/2026-11-11"
    )


# Tempo colors: parsing of the history.


def test_parse_history_fixture() -> None:
    """Every color word of the history is read."""
    colors = parse_tempo_history(read_fixture(HISTORY_FIXTURE), list(FIXTURE_COLORS))

    assert colors == FIXTURE_COLORS


def test_parse_history_requested_days_only() -> None:
    """Only the requested days are returned; a day not published yet is absent."""
    colors = parse_tempo_history(read_fixture(HISTORY_FIXTURE), DAYS)

    assert colors == KNOWN_COLORS


def test_parse_history_without_days() -> None:
    """Without any requested day, no color is returned."""
    assert parse_tempo_history(read_fixture(HISTORY_FIXTURE), []) == {}


@pytest.mark.parametrize("separator", [",", ";"])
def test_parse_history_separators(separator: str) -> None:
    """The separator of the header, a comma or a semicolon, is used."""
    text = read_fixture(HISTORY_FIXTURE).replace(",", separator)

    assert parse_tempo_history(text, list(FIXTURE_COLORS)) == FIXTURE_COLORS


def test_parse_history_separator_of_the_header() -> None:
    """The separator is the one of the header, whatever the values hold."""
    text = history_text("2026-11-11;bleu;2026,2027", header="date;couleur;saison")

    assert parse_tempo_history(text, [TODAY]) == {TODAY: TempoColor.BLUE}


@pytest.mark.parametrize(
    "convert",
    [
        pytest.param(lambda text: "﻿" + text, id="BOM"),
        pytest.param(lambda text: text.replace("\n", "\r\n"), id="CRLF"),
        pytest.param(lambda text: text.replace("\n", "\r"), id="CR"),
        pytest.param(
            lambda text: "﻿" + text.replace(",", ";").replace("\n", "\r\n"),
            id="BOM, semicolon and CRLF",
        ),
    ],
)
def test_parse_history_bom_and_line_endings(convert: Callable[[str], str]) -> None:
    """A byte order mark and Windows or old Mac line endings are tolerated."""
    text = convert(read_fixture(HISTORY_FIXTURE))

    assert parse_tempo_history(text, list(FIXTURE_COLORS)) == FIXTURE_COLORS


def test_parse_history_spaces_and_case() -> None:
    """Spaces around names and values, and the case of the colors, are ignored."""
    text = history_text(
        " 2026-01-09 , Blanc ,2025-2026",
        '2026-01-10,\t"ROUGE"  ,2025-2026',
        "2026-11-11 ,bLeU, 2026-2027",
        header=" date ,\tcouleur ,saison ",
    )

    assert parse_tempo_history(text, [WHITE_DAY, RED_DAY, TODAY]) == {
        WHITE_DAY: TempoColor.WHITE,
        RED_DAY: TempoColor.RED,
        TODAY: TempoColor.BLUE,
    }


def test_parse_history_columns_by_name() -> None:
    """The order of the columns does not matter, extra columns are ignored."""
    text = history_text(
        "x,2026-2027,bleu,2026-11-10,y",
        "x,2026-2027,blanc,2026-11-11,y",
        header="id,saison,couleur,date,commentaire",
    )

    assert parse_tempo_history(text, DAYS) == {
        YESTERDAY: TempoColor.BLUE,
        TODAY: TempoColor.WHITE,
    }


def test_parse_history_season_not_required() -> None:
    """Only the date and the color are needed."""
    text = history_text("2026-11-11,rouge", header="date,couleur")

    assert parse_tempo_history(text, DAYS) == {TODAY: TempoColor.RED}


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("2026-11-12,,2026-2027", id="empty"),
        pytest.param("2026-11-12,  ,2026-2027", id="spaces"),
        pytest.param('2026-11-12,"",2026-2027', id="quoted empty"),
        pytest.param("2026-11-12", id="no color cell"),
    ],
)
def test_parse_history_color_not_published(line: str) -> None:
    """A day whose color is empty is not published yet: it is absent."""
    text = read_fixture(HISTORY_FIXTURE) + f"{line}\n"

    assert parse_tempo_history(text, DAYS) == KNOWN_COLORS


def test_parse_history_empty_line_then_color() -> None:
    """An empty color does not hide the color of the same day on another line."""
    text = history_text("2026-11-12,,2026-2027", "2026-11-12,blanc,2026-2027")

    assert parse_tempo_history(text, [TOMORROW]) == {TOMORROW: TempoColor.WHITE}


def test_parse_history_blank_lines() -> None:
    """Empty lines, lines of spaces and lines of empty cells are skipped."""
    text = history_text("", "2026-11-10,bleu,2026-2027", "   ", ",,", "\t", ",,,")

    assert parse_tempo_history(text, DAYS) == {YESTERDAY: TempoColor.BLUE}


def test_parse_history_same_color_twice() -> None:
    """A day given twice with the same color is consistent."""
    text = history_text("2026-11-11,bleu,2026-2027", "2026-11-11,BLEU,2026-2027")

    assert parse_tempo_history(text, DAYS) == {TODAY: TempoColor.BLUE}


def test_parse_history_other_days_are_not_checked() -> None:
    """Beyond their date, the lines of other days are not checked."""
    text = history_text(
        "2014-09-01,inconnu,2014-2015",
        "2026-11-09,bleu,2026-2027",
        "2026-11-09,rouge,2026-2027",
        "2026-11-08,bleu,2026-2027,x,y",
        "2026-11-07",
        "2026-11-11,bleu,2026-2027",
    )

    assert parse_tempo_history(text, DAYS) == {TODAY: TempoColor.BLUE}


@pytest.mark.parametrize("text", ["", "﻿"])
def test_parse_history_empty(text: str) -> None:
    """A file without a header is rejected."""
    with pytest.raises(TempoDataError, match=r"^The Jour Tempo history is empty$"):
        parse_tempo_history(text, DAYS)


@pytest.mark.parametrize(
    ("header", "missing"),
    [
        pytest.param("couleur,saison", "date", id="no date"),
        pytest.param("date,saison", "couleur", id="no color"),
        pytest.param("jour,color,season", "date, couleur", id="other names"),
        pytest.param("Date,Couleur,Saison", "date, couleur", id="other case"),
        pytest.param("<!DOCTYPE html>", "date, couleur", id="HTML page"),
        pytest.param("date couleur saison", "date, couleur", id="other separator"),
    ],
)
def test_parse_history_missing_column(header: str, missing: str) -> None:
    """A history without the date or the color column is rejected."""
    text = history_text("2026-11-11,bleu,2026-2027", header=header)

    with pytest.raises(
        TempoDataError,
        match=rf"^The Jour Tempo history lacks the required columns: {missing}$",
    ):
        parse_tempo_history(text, DAYS)


def test_parse_history_duplicate_column() -> None:
    """A required column that appears twice is ambiguous: the file is rejected."""
    text = history_text(
        "2026-11-11,bleu,2026-2027,rouge", header=f"{HISTORY_HEADER}, couleur "
    )

    with pytest.raises(
        TempoDataError,
        match=r"^The Jour Tempo history has duplicate columns: couleur$",
    ):
        parse_tempo_history(text, DAYS)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("", id="empty"),
        pytest.param("demain", id="text"),
        pytest.param("11/11/2026", id="French format"),
        pytest.param("2026-11-1", id="truncated"),
        pytest.param("20261111", id="basic ISO format"),
        pytest.param("2026-11-11T06:00:00", id="date and time"),
        pytest.param("2026-02-30", id="impossible date"),
        pytest.param("2026-13-01", id="impossible month"),
    ],
)
def test_parse_history_invalid_date(value: str) -> None:
    """A line whose date cannot be read may be a requested day: it is an error."""
    text = history_text("2026-11-10,bleu,2026-2027", f"{value},bleu,2026-2027")

    with pytest.raises(
        TempoDataError,
        match=rf"^Line 3 of the Jour Tempo history: date is not a valid date: "
        rf"{re.escape(repr(value))}$",
    ):
        parse_tempo_history(text, DAYS)


def test_parse_history_missing_date_cell() -> None:
    """A line too short to have a date has no valid date."""
    text = history_text("bleu", header="couleur,saison,date")

    with pytest.raises(
        TempoDataError,
        match=r"^Line 2 of the Jour Tempo history: date is not a valid date: ''$",
    ):
        parse_tempo_history(text, DAYS)


@pytest.mark.parametrize(
    "value", ["vert", "inconnu", "blue", "bleu clair", "1", "b", "ble"]
)
def test_parse_history_unknown_color(value: str) -> None:
    """An unknown color word of a requested day is an error."""
    text = history_text("2026-11-10,bleu,2026-2027", f"2026-11-11,{value},2026-2027")

    with pytest.raises(
        TempoDataError,
        match=rf"^Line 3 of the Jour Tempo history: unknown couleur of 2026-11-11: "
        rf"{re.escape(repr(value))}$",
    ):
        parse_tempo_history(text, DAYS)


def test_parse_history_conflicting_colors() -> None:
    """Two different colors for a requested day are an error."""
    text = history_text(
        "2026-11-11,bleu,2026-2027",
        "2026-11-10,bleu,2026-2027",
        "2026-11-11,blanc,2026-2027",
    )

    with pytest.raises(
        TempoDataError,
        match=r"^Line 4 of the Jour Tempo history: 2026-11-11 has two colors: "
        r"blue and white$",
    ):
        parse_tempo_history(text, DAYS)


def test_parse_history_invalid_csv() -> None:
    """An error of the CSV reader, even on another day, is reported as invalid."""
    huge = '"' + "x" * 200_000 + '"'
    text = history_text("2026-11-11,bleu,2026-2027", f"2014-09-01,{huge},2014-2015")

    with pytest.raises(
        TempoDataError, match=r"^The Jour Tempo history is not valid CSV, line 3: "
    ) as error:
        parse_tempo_history(text, DAYS)

    assert isinstance(error.value.__cause__, csv.Error)


# Tempo colors: download from the history.


async def test_fetch_tempo_colors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The colors of the requested days are read from the Jour Tempo history."""
    aioclient_mock.get(
        JOUR_TEMPO_HISTORY_URL, content=(FIXTURES / HISTORY_FIXTURE).read_bytes()
    )

    colors = await async_fetch_tempo_colors(async_get_clientsession(hass), DAYS)

    assert colors == KNOWN_COLORS
    assert requested_urls(aioclient_mock) == [JOUR_TEMPO_HISTORY_URL]
    assert warnings(caplog) == []


async def test_fetch_tempo_colors_without_days(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Without any requested day, nothing is downloaded."""
    colors = await async_fetch_tempo_colors(async_get_clientsession(hass), [])

    assert colors == {}
    assert aioclient_mock.call_count == 0


async def test_fetch_tempo_colors_request_options(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The requests have a timeout, follow redirects and add no header."""
    aioclient_mock.get(JOUR_TEMPO_HISTORY_URL, status=HTTPStatus.SERVICE_UNAVAILABLE)
    mock_fallback(aioclient_mock, {TODAY: 1})
    session = async_get_clientsession(hass)

    with patch.object(
        aiohttp.ClientSession,
        "get",
        autospec=True,
        side_effect=aiohttp.ClientSession.get,
    ) as get:
        await async_fetch_tempo_colors(session, [TODAY])

    assert get.call_args_list == [
        call(session, JOUR_TEMPO_HISTORY_URL, timeout=REQUEST_TIMEOUT, allow_redirects=True),
        call(session, fallback_url(TODAY), timeout=REQUEST_TIMEOUT, allow_redirects=True),
    ]


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(
            b"\xef\xbb\xbf" + (FIXTURES / HISTORY_FIXTURE).read_bytes(), id="BOM"
        ),
        pytest.param(
            history_text(
                "2026-11-10,bleu,2026-2027,Été", header=f"{HISTORY_HEADER},remarque"
            ).encode("utf-8"),
            id="UTF-8",
        ),
        pytest.param(
            history_text(
                "2026-11-10,bleu,2026-2027,Été", header=f"{HISTORY_HEADER},remarque"
            ).encode("cp1252"),
            id="Windows-1252",
        ),
    ],
)
async def test_fetch_tempo_colors_encodings(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, content: bytes
) -> None:
    """The history is read as UTF-8, with or without BOM, else as Windows-1252."""
    aioclient_mock.get(JOUR_TEMPO_HISTORY_URL, content=content)

    colors = await async_fetch_tempo_colors(async_get_clientsession(hass), DAYS)

    assert colors[YESTERDAY] is TempoColor.BLUE
    assert aioclient_mock.call_count == 1


async def test_fetch_tempo_colors_windows_1252_is_logged(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A Windows-1252 history is decoded with the fallback encoding, logged."""
    content = history_text(
        "2026-11-11,rouge,2026-2027,Été", header=f"{HISTORY_HEADER},remarque"
    ).encode("cp1252")
    with pytest.raises(UnicodeDecodeError):
        content.decode("utf-8")
    aioclient_mock.get(JOUR_TEMPO_HISTORY_URL, content=content)
    caplog.set_level("DEBUG", logger=API_LOGGER)

    colors = await async_fetch_tempo_colors(async_get_clientsession(hass), DAYS)

    assert colors == {TODAY: TempoColor.RED}
    assert "Jour Tempo history decoded as Windows-1252" in caplog.text


async def test_fetch_tempo_colors_duplicate_days(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A day requested twice is returned once."""
    aioclient_mock.get(
        JOUR_TEMPO_HISTORY_URL, content=(FIXTURES / HISTORY_FIXTURE).read_bytes()
    )

    colors = await async_fetch_tempo_colors(
        async_get_clientsession(hass), [TODAY, TODAY, YESTERDAY]
    )

    assert colors == KNOWN_COLORS
    assert aioclient_mock.call_count == 1
