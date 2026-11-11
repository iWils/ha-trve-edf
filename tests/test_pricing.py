"""Tests of the tariff rules.

Instants are compared in UTC: two aware datetimes of the same zone compare by
wall-clock time, ignoring the hour repeated in autumn, and an instant of that hour
never equals an instant of another zone.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from custom_components.trve_edf.models import (
    OffPeakRange,
    TariffGrid,
    TariffOption,
    TariffPeriod,
    TariffRow,
)
from custom_components.trve_edf.pricing import (
    PARIS,
    InvalidOffPeakRangesError,
    available_powers,
    current_period,
    current_price,
    format_off_peak_ranges,
    is_off_peak,
    next_midnight,
    next_period_change,
    parse_off_peak_ranges,
    row_in_force,
)

BASE = TariffOption.BASE
HPHC = TariffOption.HPHC
NEW_YORK = ZoneInfo("America/New_York")

SPRING_DAY = date(2026, 3, 29)
"""Clock moved from 02:00 CET to 03:00 CEST, at 01:00 UTC."""
AUTUMN_DAY = date(2026, 10, 25)
"""Clock moved back from 03:00 CEST to 02:00 CET, at 01:00 UTC."""


def paris(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
    *,
    fold: int = 0,
) -> datetime:
    """Return an instant given by its wall-clock time in Paris."""
    return datetime(year, month, day, hour, minute, second, tzinfo=PARIS, fold=fold)


def utc(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    """Return an instant given in UTC."""
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def off_peak_range(start: str, end: str) -> OffPeakRange:
    """Return an off-peak range from its ``HH:MM`` times."""
    return OffPeakRange(time.fromisoformat(start), time.fromisoformat(end))


def assert_paris_instant(actual: datetime | None, expected: datetime) -> None:
    """Check that an instant is the expected one, expressed in Paris time."""
    assert actual is not None
    assert actual.tzinfo is PARIS
    assert actual.astimezone(UTC) == expected.astimezone(UTC)


# Off-peak ranges: parsing and formatting.


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("22:00-06:00", [("22:00", "06:00")], id="crossing-midnight"),
        pytest.param("12:00-14:00", [("12:00", "14:00")], id="same-day"),
        pytest.param("2:00-7:00", [("02:00", "07:00")], id="one-digit-hours"),
        pytest.param("02:00-7:30", [("02:00", "07:30")], id="mixed-digits"),
        pytest.param("0:00-9:59", [("00:00", "09:59")], id="one-digit-zero"),
        pytest.param(
            " 01:30 - 07:30 , 12:30-14:30 ",
            [("01:30", "07:30"), ("12:30", "14:30")],
            id="spaces",
        ),
        pytest.param("\t22:00 -06:00\t", [("22:00", "06:00")], id="tabs"),
        pytest.param(
            "14:00-17:00,2:00-7:00",
            [("02:00", "07:00"), ("14:00", "17:00")],
            id="sorted-by-start",
        ),
        pytest.param(
            "22:00-00:00,00:00-06:00",
            [("00:00", "06:00"), ("22:00", "00:00")],
            id="touching-at-midnight",
        ),
        pytest.param(
            "00:00-06:00,22:00-00:00",
            [("00:00", "06:00"), ("22:00", "00:00")],
            id="touching-at-midnight-reversed",
        ),
        pytest.param(
            "06:00-12:00,12:00-14:00",
            [("06:00", "12:00"), ("12:00", "14:00")],
            id="touching-in-the-day",
        ),
        pytest.param(
            "23:59-00:00,00:00-23:59",
            [("00:00", "23:59"), ("23:59", "00:00")],
            id="whole-day",
        ),
        pytest.param(
            "22:00-06:00,12:00-14:00,6:00-6:01",
            [("06:00", "06:01"), ("12:00", "14:00"), ("22:00", "06:00")],
            id="three-ranges",
        ),
    ],
)
def test_parse_valid_ranges(text: str, expected: list[tuple[str, str]]) -> None:
    """Valid ranges are parsed and sorted by start time."""
    assert parse_off_peak_ranges(text) == tuple(
        off_peak_range(start, end) for start, end in expected
    )


@pytest.mark.parametrize("text", ["", "   ", "\t"])
def test_parse_without_range(text: str) -> None:
    """A text without any range is rejected."""
    with pytest.raises(InvalidOffPeakRangesError, match=r"^No off-peak range$"):
        parse_off_peak_ranges(text)


@pytest.mark.parametrize(
    "text",
    [
        "22:00",
        "22:00-",
        "-06:00",
        "22-06",
        "22h00-06h00",
        "22:00/06:00",
        "22.00-06.00",
        "22:00\u201306:00",
        "22:00-06:00;14:00-16:00",
        "22:00-06:00 14:00-16:00",
        "22:00-06:00,",
        ",22:00-06:00",
        "22:00-06:00,,14:00-16:00",
        "24:00-06:00",
        "22:00-24:00",
        "22:60-06:00",
        "22:00-06:99",
        "22:0-06:00",
        "22:00-6:0",
        "222:00-06:00",
        "022:00-06:00",
        "+1:00-06:00",
        "22 :00-06:00",
        "22: 00-06:00",
        "22:00:00-06:00:00",
        "\u0662\u0662:00-06:00",
        "ab:cd-ef:gh",
    ],
)
def test_parse_bad_format(text: str) -> None:
    """A range that is not HH:MM-HH:MM with valid times is rejected."""
    with pytest.raises(InvalidOffPeakRangesError, match=r"^Invalid off-peak range"):
        parse_off_peak_ranges(text)


def test_parse_bad_format_message() -> None:
    """The error message names the bad range."""
    with pytest.raises(
        InvalidOffPeakRangesError,
        match=r"^Invalid off-peak range '22h00-06h00', expected HH:MM-HH:MM$",
    ):
        parse_off_peak_ranges("12:00-14:00, 22h00-06h00 ")


@pytest.mark.parametrize(
    "text", ["06:00-06:00", "0:00-00:00", "22:00-06:00, 12:30 - 12:30"]
)
def test_parse_same_start_and_end(text: str) -> None:
    """A range must not start and end at the same time."""
    with pytest.raises(
        InvalidOffPeakRangesError, match=r"starts and ends at the same time$"
    ):
        parse_off_peak_ranges(text)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("01:00-03:00,02:00-04:00", id="partly"),
        pytest.param("02:00-04:00,01:00-03:00", id="partly-reversed"),
        pytest.param("12:00-14:00,12:30-13:00", id="inside"),
        pytest.param("12:00-14:00,12:00-13:00", id="same-start"),
        pytest.param("12:00-14:00,13:00-14:00", id="same-end"),
        pytest.param("22:00-06:00,22:00-06:00", id="duplicate"),
        pytest.param("22:00-06:00,21:00-22:30", id="before-midnight-part"),
        pytest.param("22:00-06:00,23:00-23:30", id="inside-before-midnight"),
        pytest.param("22:00-06:00,00:00-01:00", id="inside-after-midnight"),
        pytest.param("22:00-06:00,05:00-07:00", id="after-midnight-part"),
        pytest.param("22:00-02:00,23:00-01:00", id="both-crossing-midnight"),
        pytest.param("22:00-00:00,23:30-00:30", id="ending-at-midnight"),
        pytest.param("00:00-06:00,23:00-00:30", id="starting-at-midnight"),
        pytest.param("06:00-05:59,05:59-06:01", id="almost-whole-day"),
    ],
)
def test_parse_overlapping_ranges(text: str) -> None:
    """Overlapping ranges are rejected, including across midnight."""
    with pytest.raises(InvalidOffPeakRangesError, match=r"overlaps another range$"):
        parse_off_peak_ranges(text)


def test_parse_overlap_message() -> None:
    """The error message names a range that overlaps another one."""
    with pytest.raises(
        InvalidOffPeakRangesError,
        match=r"^Off-peak range 02:00-04:00 overlaps another range$",
    ):
        parse_off_peak_ranges("2:00-4:00,1:00-3:00")


def test_invalid_ranges_error_is_a_value_error() -> None:
    """Callers may catch the parsing error as a ValueError."""
    assert issubclass(InvalidOffPeakRangesError, ValueError)


@pytest.mark.parametrize(
    ("ranges", "expected"),
    [
        pytest.param([], "", id="empty"),
        pytest.param([off_peak_range("22:00", "06:00")], "22:00-06:00", id="one"),
        pytest.param(
            [off_peak_range("14:00", "17:00"), off_peak_range("02:00", "07:00")],
            "02:00-07:00,14:00-17:00",
            id="sorted",
        ),
        pytest.param(
            [off_peak_range("22:00", "00:00"), off_peak_range("00:00", "06:00")],
            "00:00-06:00,22:00-00:00",
            id="touching-at-midnight",
        ),
    ],
)
def test_format_ranges(ranges: list[OffPeakRange], expected: str) -> None:
    """Ranges are formatted as their canonical text, sorted by start time."""
    assert format_off_peak_ranges(ranges) == expected


@pytest.mark.parametrize(
    ("text", "canonical"),
    [
        ("22:00-06:00", "22:00-06:00"),
        (" 2:00 - 7:00 ,14:00-17:00", "02:00-07:00,14:00-17:00"),
        ("22:00-00:00,00:00-06:00", "00:00-06:00,22:00-00:00"),
        ("0:05-9:59, 23:59-0:00", "00:05-09:59,23:59-00:00"),
    ],
)
def test_format_round_trip(text: str, canonical: str) -> None:
    """The canonical text is parsed back as the same ranges."""
    ranges = parse_off_peak_ranges(text)
    assert format_off_peak_ranges(ranges) == canonical
    assert parse_off_peak_ranges(canonical) == ranges


# Off-peak hours.


@pytest.mark.parametrize(
    ("text", "moment", "expected"),
    [
        ("12:00-14:00", "11:59:59.999999", False),
        ("12:00-14:00", "12:00", True),
        ("12:00-14:00", "13:59:59.999999", True),
        ("12:00-14:00", "14:00", False),
        ("12:00-14:00", "00:00", False),
        ("22:00-06:00", "21:59:59", False),
        ("22:00-06:00", "22:00", True),
        ("22:00-06:00", "23:59:59.999999", True),
        ("22:00-06:00", "00:00", True),
        ("22:00-06:00", "05:59:59.999999", True),
        ("22:00-06:00", "06:00", False),
        ("22:00-06:00", "12:00", False),
        ("22:00-00:00", "21:59", False),
        ("22:00-00:00", "22:00", True),
        ("22:00-00:00", "23:59:59", True),
        ("22:00-00:00", "00:00", False),
        ("00:00-06:00", "00:00", True),
        ("00:00-06:00", "23:59:59", False),
        ("01:30-07:30,12:30-14:30", "01:00", False),
        ("01:30-07:30,12:30-14:30", "02:00", True),
        ("01:30-07:30,12:30-14:30", "12:00", False),
        ("01:30-07:30,12:30-14:30", "13:00", True),
        ("01:30-07:30,12:30-14:30", "15:00", False),
    ],
)
def test_is_off_peak(text: str, moment: str, expected: bool) -> None:
    """A time is off-peak in a range, start included and end excluded."""
    ranges = parse_off_peak_ranges(text)
    assert is_off_peak(time.fromisoformat(moment), ranges) is expected


def test_is_off_peak_without_range() -> None:
    """Without any range, no time is off-peak."""
    assert is_off_peak(time(23, 0), ()) is False


# Tariff rows.


def hphc_row(
    start: date, end: date | None, power_kva: int, peak: str = "0.2000"
) -> TariffRow:
    """Return a HP/HC tariff row."""
    return TariffRow(
        start=start,
        end=end,
        power_kva=power_kva,
        subscription=Decimal("150.00"),
        prices={
            TariffPeriod.PEAK: Decimal(peak),
            TariffPeriod.OFF_PEAK: Decimal("0.1500"),
        },
    )


ROW_2024 = hphc_row(date(2024, 2, 1), date(2025, 1, 31), 6, "0.2700")
ROW_2025 = hphc_row(date(2025, 2, 1), date(2025, 7, 31), 6, "0.2500")
ROW_6_KVA = hphc_row(date(2025, 8, 1), None, 6, "0.2100")
ROW_9_KVA = hphc_row(date(2025, 2, 1), None, 9, "0.2200")
ROW_12_KVA = hphc_row(date(2026, 2, 1), None, 12, "0.2300")
GRID = TariffGrid(HPHC, (ROW_6_KVA, ROW_9_KVA, ROW_2024, ROW_12_KVA, ROW_2025))
"""Grid with closed and open rows, a row published in advance, in no order."""

OLD_ROW = hphc_row(date(2025, 2, 1), None, 6, "0.2500")
NEW_ROW = hphc_row(date(2025, 8, 1), None, 6, "0.2100")
"""Overlapping rows: the end of the old one is not filled."""


@pytest.mark.parametrize(
    ("day", "power_kva", "expected"),
    [
        pytest.param(date(2024, 1, 31), 6, None, id="before-first-row"),
        pytest.param(date(2024, 2, 1), 6, ROW_2024, id="first-day"),
        pytest.param(date(2025, 1, 31), 6, ROW_2024, id="last-day-included"),
        pytest.param(date(2025, 2, 1), 6, ROW_2025, id="day-after-end"),
        pytest.param(date(2025, 7, 31), 6, ROW_2025, id="last-day-of-next-row"),
        pytest.param(date(2025, 8, 1), 6, ROW_6_KVA, id="open-row-first-day"),
        pytest.param(date(2040, 1, 1), 6, ROW_6_KVA, id="open-row-far-ahead"),
        pytest.param(date(2025, 8, 1), 9, ROW_9_KVA, id="other-power"),
        pytest.param(date(2025, 8, 1), 3, None, id="unknown-power"),
        pytest.param(date(2026, 1, 31), 12, None, id="published-in-advance"),
        pytest.param(date(2026, 2, 1), 12, ROW_12_KVA, id="in-force-on-its-day"),
    ],
)
def test_row_in_force(day: date, power_kva: int, expected: TariffRow | None) -> None:
    """The row in force is the one of that power whose validity has the day."""
    assert row_in_force(GRID, day, power_kva) is expected


@pytest.mark.parametrize(
    "rows", [(OLD_ROW, NEW_ROW), (NEW_ROW, OLD_ROW)], ids=["old-first", "new-first"]
)
def test_row_in_force_overlapping_rows(rows: tuple[TariffRow, ...]) -> None:
    """When rows overlap, the one that starts last applies."""
    grid = TariffGrid(HPHC, rows)
    assert row_in_force(grid, date(2025, 7, 31), 6) is OLD_ROW
    assert row_in_force(grid, date(2025, 8, 1), 6) is NEW_ROW
    assert row_in_force(grid, date(2030, 1, 1), 6) is NEW_ROW


def test_row_in_force_empty_grid() -> None:
    """An empty grid has no row in force."""
    assert row_in_force(TariffGrid(HPHC, ()), date(2025, 8, 1), 6) is None


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2024, 1, 31), ()),
        (date(2024, 6, 1), (6,)),
        (date(2025, 8, 1), (6, 9)),
        (date(2026, 2, 1), (6, 9, 12)),
    ],
)
def test_available_powers(day: date, expected: tuple[int, ...]) -> None:
    """The available powers are those with a row in force, sorted."""
    assert available_powers(GRID, day) == expected


def test_available_powers_without_duplicates() -> None:
    """A power with overlapping rows is listed once."""
    grid = TariffGrid(HPHC, (ROW_9_KVA, NEW_ROW, OLD_ROW))
    assert available_powers(grid, date(2025, 9, 1)) == (6, 9)


# Current period and price.

NIGHT = parse_off_peak_ranges("22:00-06:00")


@pytest.mark.parametrize(
    "now", [paris(2026, 1, 15, 3), paris(2026, 1, 15, 12), utc(2026, 7, 1, 21)]
)
def test_current_period_base(now: datetime) -> None:
    """The Base option has a single period, and needs no off-peak range."""
    assert current_period(BASE, now, ()) is TariffPeriod.BASE
    assert current_period(BASE, now, NIGHT) is TariffPeriod.BASE


@pytest.mark.parametrize(
    ("text", "now", "expected"),
    [
        pytest.param(
            "22:00-06:00", paris(2026, 1, 15, 21, 59, 59), "peak", id="before-start"
        ),
        pytest.param("22:00-06:00", paris(2026, 1, 15, 22), "off_peak", id="start"),
        pytest.param(
            "22:00-06:00", paris(2026, 1, 16, 5, 59, 59), "off_peak", id="before-end"
        ),
        pytest.param("22:00-06:00", paris(2026, 1, 16, 6), "peak", id="end"),
        pytest.param(
            "22:00-06:00", utc(2026, 1, 15, 21, 30), "off_peak", id="utc-winter"
        ),
        pytest.param(
            "22:00-06:00", utc(2026, 7, 1, 20, 30), "off_peak", id="utc-summer"
        ),
        pytest.param(
            "22:00-06:00", utc(2026, 7, 1, 5, 30), "peak", id="utc-summer-morning"
        ),
        pytest.param(
            "22:00-06:00",
            datetime(2026, 1, 15, 16, 30, tzinfo=NEW_YORK),
            "off_peak",
            id="new-york",
        ),
        pytest.param(
            "22:00-06:00",
            datetime(2026, 1, 15, 22, 30, tzinfo=timezone(timedelta(hours=5))),
            "peak",
            id="fixed-offset",
        ),
        pytest.param(
            "02:00-02:30", utc(2026, 10, 25, 0, 15), "off_peak", id="02:15-cest"
        ),
        pytest.param("02:00-02:30", utc(2026, 10, 25, 0, 45), "peak", id="02:45-cest"),
        pytest.param(
            "02:00-02:30", utc(2026, 10, 25, 1, 15), "off_peak", id="02:15-cet"
        ),
        pytest.param("02:00-02:30", utc(2026, 3, 29, 0, 59), "peak", id="01:59-cet"),
    ],
)
def test_current_period_hphc(text: str, now: datetime, expected: str) -> None:
    """The HP/HC period follows the wall-clock time in Paris."""
    ranges = parse_off_peak_ranges(text)
    assert current_period(HPHC, now, ranges) is TariffPeriod(expected)


@pytest.mark.parametrize("option", [BASE, HPHC])
def test_current_period_naive_datetime(option: TariffOption) -> None:
    """A naive datetime is rejected: its time zone is unknown."""
    with pytest.raises(ValueError, match="timezone-aware"):
        current_period(option, datetime(2026, 1, 15, 12), NIGHT)


def test_current_period_hphc_without_range() -> None:
    """The HP/HC option cannot work without off-peak ranges."""
    with pytest.raises(ValueError, match="needs off-peak ranges"):
        current_period(HPHC, paris(2026, 1, 15, 12), ())


BASE_ROW = TariffRow(
    start=date(2025, 8, 1),
    end=None,
    power_kva=6,
    subscription=Decimal("158.40"),
    prices={TariffPeriod.BASE: Decimal("0.1952")},
)


@pytest.mark.parametrize(
    ("row", "period", "expected"),
    [
        pytest.param(BASE_ROW, TariffPeriod.BASE, Decimal("0.1952"), id="base"),
        pytest.param(BASE_ROW, TariffPeriod.PEAK, None, id="base-row-peak"),
        pytest.param(ROW_6_KVA, TariffPeriod.PEAK, Decimal("0.2100"), id="peak"),
        pytest.param(
            ROW_6_KVA, TariffPeriod.OFF_PEAK, Decimal("0.1500"), id="off-peak"
        ),
        pytest.param(ROW_6_KVA, TariffPeriod.BASE, None, id="hphc-row-base"),
    ],
)
def test_current_price(
    row: TariffRow, period: TariffPeriod, expected: Decimal | None
) -> None:
    """The price is the one of the period, or None if the row has none."""
    assert current_price(row, period) == expected


# Next period change.


@pytest.mark.parametrize("ranges", [(), NIGHT])
def test_next_period_change_base(ranges: tuple[OffPeakRange, ...]) -> None:
    """The period of the Base option never changes."""
    assert next_period_change(BASE, paris(2026, 1, 15, 12), ranges) is None


@pytest.mark.parametrize("option", [BASE, HPHC])
def test_next_period_change_naive_datetime(option: TariffOption) -> None:
    """A naive datetime is rejected."""
    with pytest.raises(ValueError, match="timezone-aware"):
        next_period_change(option, datetime(2026, 1, 15, 12), NIGHT)


def test_next_period_change_hphc_without_range() -> None:
    """The HP/HC option cannot work without off-peak ranges."""
    with pytest.raises(ValueError, match="needs off-peak ranges"):
        next_period_change(HPHC, paris(2026, 1, 15, 12), ())


@pytest.mark.parametrize(
    ("text", "now", "expected"),
    [
        pytest.param(
            "22:00-06:00",
            paris(2026, 1, 15, 12),
            paris(2026, 1, 15, 22),
            id="afternoon",
        ),
        pytest.param(
            "22:00-06:00",
            paris(2026, 1, 15, 21, 59, 59),
            paris(2026, 1, 15, 22),
            id="just-before-start",
        ),
        pytest.param(
            "22:00-06:00",
            paris(2026, 1, 15, 22),
            paris(2026, 1, 16, 6),
            id="on-start",
        ),
        pytest.param(
            "22:00-06:00",
            paris(2026, 1, 15, 23, 30),
            paris(2026, 1, 16, 6),
            id="evening",
        ),
        pytest.param(
            "22:00-06:00", paris(2026, 1, 16, 3), paris(2026, 1, 16, 6), id="night"
        ),
        pytest.param(
            "22:00-06:00",
            paris(2026, 1, 16, 6),
            paris(2026, 1, 16, 22),
            id="on-end",
        ),
        pytest.param(
            "22:00-06:00",
            paris(2026, 7, 1, 12),
            paris(2026, 7, 1, 22),
            id="summer",
        ),
        pytest.param(
            "22:00-06:00",
            paris(2026, 12, 31, 23),
            paris(2027, 1, 1, 6),
            id="new-year",
        ),
        pytest.param(
            "22:00-00:00,00:00-06:00",
            paris(2026, 1, 15, 20),
            paris(2026, 1, 15, 22),
            id="touching-before",
        ),
        pytest.param(
            "22:00-00:00,00:00-06:00",
            paris(2026, 1, 15, 23),
            paris(2026, 1, 16, 6),
            id="touching-midnight-is-not-a-change",
        ),
        pytest.param(
            "22:00-00:00,00:00-06:00",
            paris(2026, 1, 16, 0),
            paris(2026, 1, 16, 6),
            id="on-touching-boundary",
        ),
        pytest.param(
            "06:00-12:00,12:00-14:00",
            paris(2026, 1, 15, 7),
            paris(2026, 1, 15, 14),
            id="touching-in-the-day",
        ),
        pytest.param(
            "06:00-12:00,12:00-14:00",
            paris(2026, 1, 15, 15),
            paris(2026, 1, 16, 6),
            id="touching-in-the-day-next-day",
        ),
        pytest.param(
            "01:30-07:30,12:30-14:30",
            paris(2026, 1, 15, 0),
            paris(2026, 1, 15, 1, 30),
            id="two-ranges-night",
        ),
        pytest.param(
            "01:30-07:30,12:30-14:30",
            paris(2026, 1, 15, 8),
            paris(2026, 1, 15, 12, 30),
            id="two-ranges-morning",
        ),
        pytest.param(
            "01:30-07:30,12:30-14:30",
            paris(2026, 1, 15, 13),
            paris(2026, 1, 15, 14, 30),
            id="two-ranges-noon",
        ),
        pytest.param(
            "01:30-07:30,12:30-14:30",
            paris(2026, 1, 15, 15),
            paris(2026, 1, 16, 1, 30),
            id="two-ranges-afternoon",
        ),
        pytest.param(
            "20:00-00:00",
            paris(2026, 1, 15, 21),
            paris(2026, 1, 16, 0),
            id="ending-at-midnight",
        ),
        pytest.param(
            "20:00-00:00",
            paris(2026, 1, 16, 0),
            paris(2026, 1, 16, 20),
            id="on-midnight-end",
        ),
        pytest.param(
            "00:00-06:00",
            paris(2026, 1, 15, 23, 59, 59),
            paris(2026, 1, 16, 0),
            id="starting-at-midnight",
        ),
        pytest.param(
            "22:00-06:00",
            utc(2026, 1, 15, 21, 30),
            paris(2026, 1, 16, 6),
            id="utc-input",
        ),
        pytest.param(
            "22:00-06:00",
            datetime(2026, 1, 15, 16, 30, tzinfo=NEW_YORK),
            paris(2026, 1, 16, 6),
            id="new-york-input",
        ),
    ],
)
def test_next_period_change(text: str, now: datetime, expected: datetime) -> None:
    """The next change is the next start or end of off-peak hours."""
    ranges = parse_off_peak_ranges(text)
    assert_paris_instant(next_period_change(HPHC, now, ranges), expected)


@pytest.mark.parametrize("text", ["00:00-12:00,12:00-00:00", "23:59-00:00,0:00-23:59"])
@pytest.mark.parametrize(
    "now",
    [paris(2026, 1, 15, 12), utc(2026, 3, 29, 0, 30), utc(2026, 10, 25, 0, 30)],
    ids=["normal-day", "spring-day", "autumn-day"],
)
def test_next_period_change_never(text: str, now: datetime) -> None:
    """With off-peak hours all day long, the period never changes."""
    ranges = parse_off_peak_ranges(text)
    assert current_period(HPHC, now, ranges) is TariffPeriod.OFF_PEAK
    assert next_period_change(HPHC, now, ranges) is None


@pytest.mark.parametrize(
    ("text", "now", "expected"),
    [
        pytest.param(
            "22:00-06:00",
            utc(2026, 3, 28, 22),
            utc(2026, 3, 29, 4),
            id="spring-23:00-cet-to-06:00-cest",
        ),
        pytest.param(
            "22:00-06:00",
            utc(2026, 3, 29, 4),
            utc(2026, 3, 29, 20),
            id="spring-06:00-cest-to-22:00-cest",
        ),
        pytest.param(
            "02:30-07:00",
            utc(2026, 3, 28, 23),
            utc(2026, 3, 29, 1),
            id="spring-00:00-cet-to-03:00-cest-start-skipped",
        ),
        pytest.param(
            "02:30-07:00",
            utc(2026, 3, 29, 0, 59, 59),
            utc(2026, 3, 29, 1),
            id="spring-01:59:59-cet-to-03:00-cest-start-skipped",
        ),
        pytest.param(
            "02:30-07:00",
            utc(2026, 3, 29, 1),
            utc(2026, 3, 29, 5),
            id="spring-03:00-cest-to-07:00-cest",
        ),
        pytest.param(
            "01:00-02:30",
            utc(2026, 3, 28, 23),
            utc(2026, 3, 29, 0),
            id="spring-00:00-cet-to-01:00-cet",
        ),
        pytest.param(
            "01:00-02:30",
            utc(2026, 3, 29, 0),
            utc(2026, 3, 29, 1),
            id="spring-01:00-cet-to-03:00-cest-end-skipped",
        ),
        pytest.param(
            "23:30-02:00",
            utc(2026, 3, 28, 22, 30),
            utc(2026, 3, 29, 1),
            id="spring-23:30-cet-to-03:00-cest-end-skipped",
        ),
        pytest.param(
            "02:00-03:00",
            utc(2026, 3, 28, 2),
            utc(2026, 3, 30, 0),
            id="spring-range-skipped-saturday-03:00-cet-to-monday-02:00-cest",
        ),
        pytest.param(
            "02:00-03:00",
            utc(2026, 3, 29, 0),
            utc(2026, 3, 30, 0),
            id="spring-range-skipped-01:00-cet-to-monday-02:00-cest",
        ),
        pytest.param(
            "03:00-02:00",
            utc(2026, 3, 28, 2),
            utc(2026, 3, 30, 0),
            id="spring-peak-skipped-saturday-03:00-cet-to-monday-02:00-cest",
        ),
        pytest.param(
            "22:00-06:00",
            utc(2026, 10, 24, 21),
            utc(2026, 10, 25, 5),
            id="autumn-23:00-cest-to-06:00-cet",
        ),
        pytest.param(
            "02:30-07:00",
            utc(2026, 10, 24, 22),
            utc(2026, 10, 25, 0, 30),
            id="autumn-00:00-cest-to-02:30-cest",
        ),
        pytest.param(
            "02:30-07:00",
            utc(2026, 10, 25, 0, 30),
            utc(2026, 10, 25, 1),
            id="autumn-02:30-cest-to-02:00-cet-back-to-peak",
        ),
        pytest.param(
            "02:30-07:00",
            utc(2026, 10, 25, 1),
            utc(2026, 10, 25, 1, 30),
            id="autumn-02:00-cet-to-02:30-cet",
        ),
        pytest.param(
            "02:30-07:00",
            utc(2026, 10, 25, 1, 30),
            utc(2026, 10, 25, 6),
            id="autumn-02:30-cet-to-07:00-cet",
        ),
        pytest.param(
            "01:00-02:30",
            utc(2026, 10, 24, 23),
            utc(2026, 10, 25, 0, 30),
            id="autumn-01:00-cest-to-02:30-cest",
        ),
        pytest.param(
            "01:00-02:30",
            utc(2026, 10, 25, 0, 30),
            utc(2026, 10, 25, 1),
            id="autumn-02:30-cest-to-02:00-cet-back-to-off-peak",
        ),
        pytest.param(
            "01:00-02:30",
            utc(2026, 10, 25, 1),
            utc(2026, 10, 25, 1, 30),
            id="autumn-02:00-cet-to-02:30-cet",
        ),
        pytest.param(
            "01:00-02:30",
            utc(2026, 10, 25, 1, 30),
            utc(2026, 10, 26, 0),
            id="autumn-02:30-cet-to-monday-01:00-cet",
        ),
        pytest.param(
            "02:00-03:00",
            utc(2026, 10, 24, 22),
            utc(2026, 10, 25, 0),
            id="autumn-00:00-cest-to-02:00-cest",
        ),
        pytest.param(
            "02:00-03:00",
            utc(2026, 10, 25, 0),
            utc(2026, 10, 25, 2),
            id="autumn-02:00-cest-to-03:00-cet-clock-change-is-not-a-change",
        ),
        pytest.param(
            "03:00-02:00",
            utc(2026, 10, 25, 0),
            utc(2026, 10, 25, 2),
            id="autumn-peak-02:00-cest-to-03:00-cet",
        ),
    ],
)
def test_next_period_change_on_dst_days(
    text: str, now: datetime, expected: datetime
) -> None:
    """On daylight saving time days, the change is the real instant."""
    ranges = parse_off_peak_ranges(text)
    assert_paris_instant(next_period_change(HPHC, now, ranges), expected)


@pytest.mark.parametrize(
    "day",
    [SPRING_DAY, AUTUMN_DAY, date(2026, 6, 15)],
    ids=["spring-day", "autumn-day", "summer-day"],
)
@pytest.mark.parametrize(
    "text",
    [
        "22:00-06:00",
        "02:30-07:00",
        "01:00-02:30",
        "02:00-03:00",
        "03:00-02:00",
        "23:30-02:00",
        "01:30-02:15,02:45-03:30,12:00-14:00",
        "22:00-00:00,00:00-02:00,02:00-03:00",
    ],
)
def test_next_period_change_matches_a_minute_scan(text: str, day: date) -> None:
    """Around a day, the next change is the first later minute with another period.

    Periods only change on whole minutes: the reference scans the minutes in UTC
    and asks the current period of each one.
    """
    ranges = parse_off_peak_ranges(text)
    start = datetime.combine(day - timedelta(days=1), time(), tzinfo=UTC)
    minutes = 6 * 24 * 60  # Three days of samples, three more to see changes.
    periods = [
        current_period(HPHC, start + timedelta(minutes=index), ranges)
        for index in range(minutes)
    ]
    next_change: list[int | None] = [None] * minutes
    for index in range(minutes - 2, -1, -1):
        if periods[index + 1] is periods[index]:
            next_change[index] = next_change[index + 1]
        else:
            next_change[index] = index + 1
    # Every 7th minute of three days, and every minute around the clock change.
    samples = sorted({*range(0, 3 * 24 * 60, 7), *range(22 * 60, 28 * 60)})
    for index in samples:
        now = start + timedelta(minutes=index, seconds=(index % 3) * 20)
        expected = next_change[index]
        assert expected is not None
        result = next_period_change(HPHC, now, ranges)
        assert_paris_instant(result, start + timedelta(minutes=expected))


# Next midnight.


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        pytest.param(paris(2026, 1, 15, 12), utc(2026, 1, 15, 23), id="noon"),
        pytest.param(paris(2026, 1, 15), utc(2026, 1, 15, 23), id="on-midnight"),
        pytest.param(
            paris(2026, 1, 15, 23, 59, 59), utc(2026, 1, 15, 23), id="just-before"
        ),
        pytest.param(
            utc(2026, 1, 15, 23, 30), utc(2026, 1, 16, 23), id="utc-is-the-day-before"
        ),
        pytest.param(utc(2026, 7, 1, 21, 59), utc(2026, 7, 1, 22), id="summer"),
        pytest.param(
            datetime(2026, 1, 15, 20, tzinfo=NEW_YORK),
            utc(2026, 1, 16, 23),
            id="new-york",
        ),
        pytest.param(paris(2026, 12, 31, 12), utc(2026, 12, 31, 23), id="new-year"),
        pytest.param(
            paris(2026, 3, 28, 12), utc(2026, 3, 28, 23), id="spring-day-before"
        ),
        pytest.param(paris(2026, 3, 29), utc(2026, 3, 29, 22), id="spring-midnight"),
        pytest.param(
            paris(2026, 3, 29, 12), utc(2026, 3, 29, 22), id="spring-after-change"
        ),
        pytest.param(
            paris(2026, 10, 24, 12), utc(2026, 10, 24, 22), id="autumn-day-before"
        ),
        pytest.param(paris(2026, 10, 25), utc(2026, 10, 25, 23), id="autumn-midnight"),
        pytest.param(
            utc(2026, 10, 25, 1, 30), utc(2026, 10, 25, 23), id="autumn-02:30-cet"
        ),
    ],
)
def test_next_midnight(now: datetime, expected: datetime) -> None:
    """The next midnight is the start of the next day in Paris."""
    result = next_midnight(now)
    assert_paris_instant(result, expected)
    assert result.time() == time()
    assert result > now


def test_next_midnight_naive_datetime() -> None:
    """A naive datetime is rejected."""
    with pytest.raises(ValueError, match="timezone-aware"):
        next_midnight(datetime(2026, 1, 15, 12))
