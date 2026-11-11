"""Business rules of the EDF regulated tariffs (TRVE).

Pure functions with no Home Assistant dependency: off-peak ranges, tariff row in
force, current tariff period and price, next period change. Every time rule uses
the French legal time (``Europe/Paris``), whatever the time zone of the system.

Instants are compared in UTC inside this module: two aware datetimes of the same
zone compare by wall-clock time, which is wrong in the hour repeated in autumn.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
import re
from typing import Final
from zoneinfo import ZoneInfo

from .models import OffPeakRange, TariffGrid, TariffOption, TariffPeriod, TariffRow

PARIS: Final = ZoneInfo("Europe/Paris")
"""Time zone of every tariff rule: the French legal time."""

_MINUTES_PER_DAY: Final = 24 * 60

_SEARCH_DAYS: Final = 3
"""Local days searched for the next period change: today and the next two days.

Tomorrow shows every wall-clock time, or the day after when tomorrow skips an
hour in spring: if the period ever changes, it changes within these days.
"""

_HOUR: Final = r"([01]?[0-9]|2[0-3])"
_MINUTE: Final = r"([0-5][0-9])"
_RANGE: Final = re.compile(rf"{_HOUR}:{_MINUTE}\s*-\s*{_HOUR}:{_MINUTE}")


class InvalidOffPeakRangesError(ValueError):
    """The text of the off-peak ranges is not valid."""


def parse_off_peak_ranges(text: str) -> tuple[OffPeakRange, ...]:
    """Parse the off-peak ranges of a contract.

    Args:
        text: Comma-separated ranges ``HH:MM-HH:MM``, hours on one or two
            digits, for example ``"22:00-06:00"`` or ``"2:00-7:00, 14:00-17:00"``.
            Spaces are tolerated around the ranges and around the dashes. A
            range may cross midnight.

    Returns:
        The ranges, sorted by start time.

    Raises:
        InvalidOffPeakRangesError: The text holds no range, a range is badly
            formatted or starts and ends at the same time, or ranges overlap.
    """
    if not text.strip():
        raise InvalidOffPeakRangesError("No off-peak range")
    ranges = sorted(
        (_parse_range(item.strip()) for item in text.split(",")),
        key=lambda off_peak_range: off_peak_range.start,
    )
    covered: set[int] = set()
    for off_peak_range in ranges:
        minutes = _minutes_of(off_peak_range)
        if not covered.isdisjoint(minutes):
            raise InvalidOffPeakRangesError(
                f"Off-peak range {_format_range(off_peak_range)} overlaps another range"
            )
        covered |= minutes
    return tuple(ranges)


def _parse_range(item: str) -> OffPeakRange:
    """Parse one off-peak range ``HH:MM-HH:MM``."""
    match = _RANGE.fullmatch(item)
    if match is None:
        raise InvalidOffPeakRangesError(
            f"Invalid off-peak range {item!r}, expected HH:MM-HH:MM"
        )
    start_hour, start_minute, end_hour, end_minute = map(int, match.groups())
    off_peak_range = OffPeakRange(
        time(start_hour, start_minute), time(end_hour, end_minute)
    )
    if off_peak_range.start == off_peak_range.end:
        raise InvalidOffPeakRangesError(
            f"Off-peak range {item!r} starts and ends at the same time"
        )
    return off_peak_range


def _minutes_of(off_peak_range: OffPeakRange) -> set[int]:
    """Return the minutes of the day covered by a range, midnight being 0."""
    start = off_peak_range.start.hour * 60 + off_peak_range.start.minute
    end = off_peak_range.end.hour * 60 + off_peak_range.end.minute
    length = (end - start) % _MINUTES_PER_DAY
    return {(start + offset) % _MINUTES_PER_DAY for offset in range(length)}


def format_off_peak_ranges(ranges: Sequence[OffPeakRange]) -> str:
    """Format off-peak ranges as their canonical text.

    Args:
        ranges: Off-peak ranges.

    Returns:
        The ranges sorted by start time, as ``HH:MM-HH:MM,HH:MM-HH:MM``: the
        text that `parse_off_peak_ranges` reads back as the same ranges.
    """
    return ",".join(
        _format_range(off_peak_range)
        for off_peak_range in sorted(ranges, key=lambda item: item.start)
    )


def _format_range(off_peak_range: OffPeakRange) -> str:
    """Format one off-peak range as ``HH:MM-HH:MM``."""
    return f"{off_peak_range.start:%H:%M}-{off_peak_range.end:%H:%M}"


def is_off_peak(moment: time, ranges: Sequence[OffPeakRange]) -> bool:
    """Tell whether a wall-clock time is in off-peak hours.

    Args:
        moment: Naive local wall-clock time.
        ranges: Off-peak ranges, as returned by `parse_off_peak_ranges`.

    Returns:
        True if the time is in a range: start included, end excluded. A range
        whose end is before its start crosses midnight.
    """
    return any(_range_contains(off_peak_range, moment) for off_peak_range in ranges)


def _range_contains(off_peak_range: OffPeakRange, moment: time) -> bool:
    """Tell whether a wall-clock time is in one off-peak range."""
    start, end = off_peak_range.start, off_peak_range.end
    if start < end:
        return start <= moment < end
    return moment >= start or moment < end


def row_in_force(grid: TariffGrid, day: date, power_kva: int) -> TariffRow | None:
    """Return the tariff row of a subscribed power in force on a day.

    Args:
        grid: Tariff grid of the option.
        day: Local day in France.
        power_kva: Subscribed power, in kVA.

    Returns:
        The row of that power whose validity contains the day, its last day
        included; the one that starts last if several rows match. None if no
        row matches.
    """
    rows = [
        row for row in grid.rows if row.power_kva == power_kva and _in_force(row, day)
    ]
    return max(rows, key=lambda row: row.start, default=None)


def available_powers(grid: TariffGrid, day: date) -> tuple[int, ...]:
    """Return the subscribed powers that have a tariff row in force on a day.

    Args:
        grid: Tariff grid of the option.
        day: Local day in France.

    Returns:
        The powers in kVA, sorted, without duplicates.
    """
    return tuple(sorted({row.power_kva for row in grid.rows if _in_force(row, day)}))


def _in_force(row: TariffRow, day: date) -> bool:
    """Tell whether the validity of a tariff row contains a day."""
    return row.start <= day and (row.end is None or day <= row.end)


def current_period(
    option: TariffOption, now: datetime, off_peak: Sequence[OffPeakRange]
) -> TariffPeriod:
    """Return the tariff period in force at an instant.

    Args:
        option: Tariff option of the contract.
        now: Timezone-aware instant; the rules use its wall-clock time in Paris.
        off_peak: Off-peak ranges of the contract, needed by the HP/HC option.

    Returns:
        The base period for the Base option; for the HP/HC option, the
        off-peak period during the off-peak ranges and the peak period
        otherwise.

    Raises:
        ValueError: The instant is naive, or the option is HP/HC and there is no
            off-peak range.
    """
    local = _to_paris(now)
    if option is TariffOption.BASE:
        return TariffPeriod.BASE
    if not off_peak:
        raise ValueError("The HP/HC option needs off-peak ranges")
    return _hphc_period(local, off_peak)


def _to_paris(now: datetime) -> datetime:
    """Convert an aware instant to Paris time; reject a naive one."""
    if now.utcoffset() is None:
        raise ValueError(f"A timezone-aware datetime is expected, not {now}")
    return now.astimezone(PARIS)


def _hphc_period(instant: datetime, off_peak: Sequence[OffPeakRange]) -> TariffPeriod:
    """Return the HP/HC period at an aware instant."""
    wall_clock = instant.astimezone(PARIS).time()
    if is_off_peak(wall_clock, off_peak):
        return TariffPeriod.OFF_PEAK
    return TariffPeriod.PEAK


def current_price(row: TariffRow, period: TariffPeriod) -> Decimal | None:
    """Return the price of the kWh of a period.

    Args:
        row: Tariff row in force.
        period: Tariff period.

    Returns:
        The price in euros, taxes included, or None if the row has no price for
        that period.
    """
    return row.prices.get(period)


def next_period_change(
    option: TariffOption, now: datetime, off_peak: Sequence[OffPeakRange]
) -> datetime | None:
    """Return the next instant at which the tariff period changes.

    The period follows the wall-clock time in Paris, so it may also change when
    the clock is moved on daylight saving time days. With off-peak hours from
    02:30 to 07:00, off-peak hours start at 03:00 in spring, when the clock jumps
    from 02:00 to 03:00. In autumn, they start at 02:30, stop when the clock goes
    back from 03:00 to 02:00, and start again at the second 02:30. A boundary
    between two touching ranges is not a change.

    Args:
        option: Tariff option of the contract.
        now: Timezone-aware instant.
        off_peak: Off-peak ranges of the contract, needed by the HP/HC option.

    Returns:
        The earliest instant strictly after now at which the period changes, in
        Paris time; None for the Base option, or when the period never changes.

    Raises:
        ValueError: The instant is naive, or the option is HP/HC and there is no
            off-peak range.
    """
    period = current_period(option, now, off_peak)
    if option is TariffOption.BASE:
        return None
    after = now.astimezone(UTC)
    for instant in _clock_events(now.astimezone(PARIS).date(), off_peak):
        if instant > after and _hphc_period(instant, off_peak) is not period:
            return instant.astimezone(PARIS)
    return None


def _clock_events(first_day: date, off_peak: Sequence[OffPeakRange]) -> list[datetime]:
    """Return the instants at which the HP/HC period may change, in UTC, sorted.

    The period only depends on the wall-clock time: it may change when the clock
    shows the start or the end of a range, and when the clock is moved.
    """
    boundaries = {moment for item in off_peak for moment in (item.start, item.end)}
    events: set[datetime] = set()
    for offset in range(_SEARCH_DAYS):
        day = first_day + timedelta(days=offset)
        for boundary in boundaries:
            events.update(_instants_showing(day, boundary))
        clock_change = _clock_change(day)
        if clock_change is not None:
            events.add(clock_change)
    return sorted(events)


def _instants_showing(day: date, wall_clock: time) -> set[datetime]:
    """Return the instants, in UTC, at which the Paris clock shows a day and time.

    There is none in the hour skipped in spring, two in the hour repeated in
    autumn and one otherwise.
    """
    local = datetime.combine(day, wall_clock)
    candidates = (
        local.replace(tzinfo=PARIS, fold=fold).astimezone(UTC) for fold in (0, 1)
    )
    return {
        instant
        for instant in candidates
        if instant.astimezone(PARIS).replace(tzinfo=None) == local
    }


def _clock_change(day: date) -> datetime | None:
    """Return the instant, in UTC, at which the Paris clock is moved on a day.

    None if the clock is not moved that day.
    """
    start = _local_midnight(day)
    end = _local_midnight(day + timedelta(days=1))
    new_offset = _utc_offset(end)
    if _utc_offset(start) == new_offset:
        return None
    # Bisection on whole seconds: the old offset applies at `low` seconds after
    # midnight and the new one at `high` seconds.
    low, high = 0, int((end - start).total_seconds())
    while high - low > 1:
        middle = (low + high) // 2
        if _utc_offset(start + timedelta(seconds=middle)) == new_offset:
            high = middle
        else:
            low = middle
    return start + timedelta(seconds=high)


def _local_midnight(day: date) -> datetime:
    """Return the instant, in UTC, of the start of a day in Paris."""
    return datetime.combine(day, time(), tzinfo=PARIS).astimezone(UTC)


def _utc_offset(instant: datetime) -> timedelta | None:
    """Return the offset of the Paris time from UTC at an instant."""
    return instant.astimezone(PARIS).utcoffset()


def next_midnight(now: datetime) -> datetime:
    """Return the next midnight in Paris.

    Args:
        now: Timezone-aware instant.

    Returns:
        The start of the next day in Paris, strictly after now, in Paris time.

    Raises:
        ValueError: The instant is naive.
    """
    tomorrow = _to_paris(now).date() + timedelta(days=1)
    return _local_midnight(tomorrow).astimezone(PARIS)
