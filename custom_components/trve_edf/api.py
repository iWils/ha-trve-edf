"""Clients of the regulated tariff grids (CRE) and of the Tempo colors.

All the network access of the integration goes through this module. It receives
the HTTP session from its caller (Home Assistant's shared session in the
integration) and has no Home Assistant dependency. Every request has a timeout,
and an invalid response is never kept.

The CRE publishes one CSV file per tariff option on data.gouv.fr, with ``;`` as
separator and a header line. The columns are read by their name, and only the
amounts with taxes included (TTC) are kept. An invalid row that may still apply
rejects the whole grid. An invalid row that ended before the current day cannot
affect any price: when the caller gives the current day, such a row is skipped
and logged instead.

The Tempo colors published by RTE are read from the history of Jour Tempo, a CSV
file with one line per day. When it cannot be used, the colors are read from
api-couleur-tempo.fr instead, one request per day.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import csv
from datetime import date
from decimal import Decimal
from http import HTTPStatus
import io
import json
import logging
import re
from typing import Final

import aiohttp

from .models import (
    OPTION_PRICES,
    PriceKey,
    TariffGrid,
    TariffOption,
    TariffRow,
    TempoColor,
)

_LOGGER = logging.getLogger(__name__)

CRE_GRID_URLS: Final[Mapping[TariffOption, str]] = {
    TariffOption.BASE: (
        "https://www.data.gouv.fr/fr/datasets/r/c13d05e5-9e55-4d03-bf7e-042a2ade7e49"
    ),
    TariffOption.HPHC: (
        "https://www.data.gouv.fr/fr/datasets/r/f7303b3a-93c7-4242-813d-84919034c416"
    ),
    TariffOption.TEMPO: (
        "https://www.data.gouv.fr/fr/datasets/r/0c3d1d36-c412-4620-8566-e5cbb4fa2b5a"
    ),
}
"""Stable data.gouv.fr URL of the CRE tariff grid of each option.

Each URL redirects to the file on the CRE website.
"""

JOUR_TEMPO_HISTORY_URL: Final = "https://jourtempo.fr/api/v1/tempo-historique.csv"
"""History of the Tempo colors published by Jour Tempo, the primary source.

A CSV file with one line per day since 1 September 2014, today and tomorrow
included as soon as RTE has published their color.
"""

FALLBACK_TEMPO_URL: Final = "https://www.api-couleur-tempo.fr/api/jourTempo/{day}"
"""Tempo color of one day on api-couleur-tempo.fr, the fallback source.

``{day}`` is the day, written ``YYYY-MM-DD``.
"""

REQUEST_TIMEOUT: Final = aiohttp.ClientTimeout(total=30)
"""Timeout of a whole request, from connection to the end of the body."""

_START: Final = "DATE_DEBUT"
_END: Final = "DATE_FIN"
_POWER: Final = "P_SOUSCRITE"
_SUBSCRIPTION: Final = "PART_FIXE_TTC"
_PRICE_COLUMNS: Final[Mapping[TariffOption, Mapping[PriceKey, str]]] = {
    TariffOption.BASE: {PriceKey.BASE: "PART_VARIABLE_TTC"},
    TariffOption.HPHC: {
        PriceKey.PEAK: "PART_VARIABLE_HP_TTC",
        PriceKey.OFF_PEAK: "PART_VARIABLE_HC_TTC",
    },
    TariffOption.TEMPO: {
        PriceKey.BLUE_PEAK: "PART_VARIABLE_HPBleu_TTC",
        PriceKey.BLUE_OFF_PEAK: "PART_VARIABLE_HCBleu_TTC",
        PriceKey.WHITE_PEAK: "PART_VARIABLE_HPBlanc_TTC",
        PriceKey.WHITE_OFF_PEAK: "PART_VARIABLE_HCBlanc_TTC",
        PriceKey.RED_PEAK: "PART_VARIABLE_HPRouge_TTC",
        PriceKey.RED_OFF_PEAK: "PART_VARIABLE_HCRouge_TTC",
    },
}
"""Column of each price of the kWh, for each option."""

_HISTORY: Final = "Jour Tempo history"
"""Name of the primary Tempo source in the messages."""
_HISTORY_DATE: Final = "date"
_HISTORY_COLOR: Final = "couleur"
_HISTORY_COLORS: Final[Mapping[str, TempoColor]] = {
    "bleu": TempoColor.BLUE,
    "blanc": TempoColor.WHITE,
    "rouge": TempoColor.RED,
}
"""Tempo color of each color word of the history, in lower case."""

_FALLBACK_DATE: Final = "dateJour"
_FALLBACK_CODE: Final = "codeJour"
_FALLBACK_COLORS: Final[Mapping[int, TempoColor | None]] = {
    0: None,
    1: TempoColor.BLUE,
    2: TempoColor.WHITE,
    3: TempoColor.RED,
}
"""Tempo color of each day code of the fallback source; 0 is not known yet."""

_BOM: Final = "﻿"
_FRENCH_DATE: Final = re.compile(
    r"(?P<day>[0-9]{1,2})/(?P<month>[0-9]{1,2})/(?P<year>[0-9]{4})"
)
_ISO_DATE: Final = re.compile(
    r"(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})"
)
_INTEGER: Final = re.compile(r"[0-9]+")
_AMOUNT: Final = re.compile(r"[+-]?[0-9]+(?:[.,][0-9]+)?")


class TrveEdfError(Exception):
    """Base error of the EDF regulated tariffs (TRVE) integration."""


class CreConnectionError(TrveEdfError):
    """A CRE tariff grid could not be downloaded.

    Raised on a network error, a timeout or an HTTP error status.
    """


class CreDataError(TrveEdfError):
    """A downloaded CRE tariff grid is invalid."""


class TempoConnectionError(TrveEdfError):
    """The Tempo colors could not be downloaded.

    Raised on a network error, a timeout or an HTTP error status.
    """


class TempoDataError(TrveEdfError):
    """Downloaded Tempo colors are invalid."""


async def async_fetch_grid(
    session: aiohttp.ClientSession,
    option: TariffOption,
    *,
    today: date | None = None,
) -> TariffGrid:
    """Download and parse the CRE tariff grid of an option.

    The body is decoded as UTF-8 (with or without byte order mark), or as
    Windows-1252 when it is not valid UTF-8.

    Args:
        session: HTTP session used for the request.
        option: Tariff option of the grid.
        today: Current day in France, to skip the invalid past rows; see
            parse_grid.

    Returns:
        The grid of the option, with its rows in file order.

    Raises:
        CreConnectionError: The grid could not be downloaded.
        CreDataError: The downloaded grid is invalid.
    """
    source = f"CRE tariff grid ({option})"
    body = await _async_download(
        session, CRE_GRID_URLS[option], source, CreConnectionError
    )
    grid = parse_grid(option, _decode(body, source, CreDataError), today=today)
    _LOGGER.debug("CRE tariff grid (%s) downloaded: %d rows", option, len(grid.rows))
    return grid


def parse_grid(
    option: TariffOption, text: str, *, today: date | None = None
) -> TariffGrid:
    """Parse the CSV tariff grid of an option, as published by the CRE.

    Columns are read by their header name, extra columns are ignored. Dates may
    be written ``DD/MM/YYYY`` or ``YYYY-MM-DD``, decimals with ``,`` or ``.``.
    Blank lines and rows without any amount (gaps in the history) are skipped.

    Args:
        option: Tariff option of the grid.
        text: Content of the CSV file.
        today: Current day in France. When given, an invalid row whose end date
            is before this day is skipped, with a warning for the whole grid,
            instead of rejecting the grid: it cannot affect any price. When
            None, every row must be valid.

    Returns:
        The grid of the option, with its rows in file order.

    Raises:
        CreDataError: The grid is invalid: a required column is missing, a row
            that may still apply cannot be parsed or is inconsistent, or no row
            is usable.
    """
    reader = csv.DictReader(
        io.StringIO(text.removeprefix(_BOM), newline=""),
        delimiter=";",
        skipinitialspace=True,
    )
    try:
        _read_header(option, reader)
        rows = _read_rows(option, reader, today)
    except csv.Error as err:
        # The dict reader counts the lines read successfully: the underlying
        # reader counts the line being read.
        raise CreDataError(
            f"The CRE tariff grid ({option}) is not valid CSV, "
            f"line {reader.reader.line_num}: {err}"
        ) from err
    if not rows:
        raise CreDataError(f"The CRE tariff grid ({option}) has no usable row")
    return TariffGrid(option=option, rows=tuple(rows))


async def async_fetch_tempo_colors(
    session: aiohttp.ClientSession, days: Sequence[date]
) -> dict[date, TempoColor]:
    """Download the known Tempo colors of some days.

    The colors are read from the Jour Tempo history. When it cannot be
    downloaded or is invalid, a warning is logged and each day is asked to
    api-couleur-tempo.fr instead. A body is decoded as UTF-8 (with or without
    byte order mark); the history may also be Windows-1252 text. The colors are
    taken from one source only, and an error never gives partial colors. When
    the fallback source fails too, its error is raised while handling the error
    of the history, which is its context: the traceback shows both.

    Args:
        session: HTTP session used for the requests.
        days: Tempo days whose color is wanted. Without any day, nothing is
            downloaded.

    Returns:
        The color of each requested day that is known; a day whose color is not
        published yet is left out.

    Raises:
        TempoConnectionError: The history could not be used, and the fallback
            source could not be downloaded.
        TempoDataError: The history could not be used, and the fallback source
            is invalid.
    """
    wanted = tuple(dict.fromkeys(days))
    if not wanted:
        return {}
    try:
        return await _async_fetch_history(session, wanted)
    except (TempoConnectionError, TempoDataError) as err:
        _LOGGER.warning("%s; using api-couleur-tempo.fr instead", err)
        return await _async_fetch_fallback(session, wanted)


def parse_tempo_history(text: str, days: Sequence[date]) -> dict[date, TempoColor]:
    """Parse the Jour Tempo history and return the colors of some days.

    The file has a header line, with ``,`` or ``;`` as separator (the one used
    in the header). Columns are read by their name, ``date`` (``YYYY-MM-DD``)
    and ``couleur`` (``bleu``, ``blanc`` or ``rouge``, in any case); the others
    are ignored. Spaces around names and values are ignored, and so are blank
    lines.

    Every line must have a valid date: a line whose date cannot be read may be
    the line of a requested day. Beyond its date, a line of another day is not
    checked.

    Args:
        text: Content of the CSV file.
        days: Days whose color is wanted.

    Returns:
        The color of each requested day that is known. A day without a line, or
        whose color is empty, is not published yet: it is left out.

    Raises:
        TempoDataError: The history is invalid: it is empty or not valid CSV, a
            required column is missing or duplicated, a date cannot be read,
            the color of a requested day is unknown, or a requested day has two
            lines with different colors.
    """
    text = text.removeprefix(_BOM)
    header = text.splitlines()[0] if text else ""
    reader = csv.DictReader(
        io.StringIO(text, newline=""),
        delimiter=";" if header.count(";") > header.count(",") else ",",
        skipinitialspace=True,
    )
    try:
        _read_history_header(reader)
        return _read_history_colors(reader, frozenset(days))
    except csv.Error as err:
        raise TempoDataError(
            f"The {_HISTORY} is not valid CSV, line {reader.reader.line_num}: {err}"
        ) from err


async def _async_download(
    session: aiohttp.ClientSession,
    url: str,
    source: str,
    error: type[TrveEdfError],
) -> bytes:
    """Download a resource and return its body.

    The request has a timeout and follows the redirects.

    Args:
        session: HTTP session used for the request.
        url: URL of the resource.
        source: Name of the resource in the messages.
        error: Error to raise when the resource cannot be downloaded.

    Raises:
        TrveEdfError: Of the given type, on a network error, a timeout or an
            HTTP error status; chained to the cause.
    """
    try:
        async with session.get(
            url, timeout=REQUEST_TIMEOUT, allow_redirects=True
        ) as response:
            if response.status >= HTTPStatus.BAD_REQUEST:
                raise error(
                    f"The {source} could not be downloaded: "
                    f"HTTP status {response.status}"
                )
            return await response.read()
    except (aiohttp.ClientError, TimeoutError) as err:
        reason = str(err) or type(err).__name__
        raise error(f"The {source} could not be downloaded: {reason}") from err


def _decode(body: bytes, source: str, error: type[TrveEdfError]) -> str:
    """Decode a body as UTF-8, with or without byte order mark, or Windows-1252.

    Args:
        body: Body of the response.
        source: Name of the resource in the messages.
        error: Error to raise when the body cannot be decoded.

    Raises:
        TrveEdfError: Of the given type, when the body is neither UTF-8 nor
            Windows-1252 text.
    """
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        text = body.decode("cp1252")
    except UnicodeDecodeError as err:
        raise error(f"The {source} is neither UTF-8 nor Windows-1252 text") from err
    _LOGGER.debug("%s decoded as Windows-1252", source)
    return text


# CRE tariff grids.


def _required_columns(option: TariffOption) -> tuple[str, ...]:
    """Return the columns needed to build the rows of an option."""
    return (_START, _END, _POWER, *_amount_columns(option))


def _amount_columns(option: TariffOption) -> tuple[str, ...]:
    """Return the columns of the amounts used for an option."""
    return (_SUBSCRIPTION, *_PRICE_COLUMNS[option].values())


def _read_header(option: TariffOption, reader: csv.DictReader[str]) -> None:
    """Read and check the header line, ignoring spaces around the names."""
    if reader.fieldnames is None:
        raise CreDataError(f"The CRE tariff grid ({option}) is empty")
    header = [name.strip() for name in reader.fieldnames]
    reader.fieldnames = header
    required = _required_columns(option)
    if missing := [column for column in required if column not in header]:
        raise CreDataError(
            f"The CRE tariff grid ({option}) lacks the required columns: "
            f"{', '.join(missing)}"
        )
    if duplicates := [column for column in required if header.count(column) > 1]:
        raise CreDataError(
            f"The CRE tariff grid ({option}) has duplicate columns: "
            f"{', '.join(duplicates)}"
        )


type _Record = Mapping[str | None, str | list[str] | None]
"""Record of the CSV reader: cells by column name.

Cells beyond the header are listed under None; columns beyond the row are None.
"""


def _read_rows(
    option: TariffOption, reader: csv.DictReader[str], today: date | None
) -> list[TariffRow]:
    """Read the rows that follow the header.

    Args:
        option: Tariff option of the grid.
        reader: CSV reader, after the header.
        today: Current day, to skip the invalid rows that ended before it; None
            to reject every invalid row.

    Returns:
        The usable rows, in file order.

    Raises:
        CreDataError: A row that may still apply is invalid.
    """
    rows: list[TariffRow] = []
    skipped: list[tuple[int, str]] = []
    for record in reader:
        try:
            row = _parse_record(option, record)
        except ValueError as err:
            if today is None or not _ended_before(record, today):
                raise CreDataError(
                    f"Line {reader.line_num} of the CRE tariff grid ({option}): {err}"
                ) from err
            skipped.append((reader.line_num, str(err)))
            continue
        if row is not None:
            rows.append(row)
    if skipped:
        line, reason = skipped[0]
        _LOGGER.warning(
            "Skipped %d invalid row(s) of the CRE tariff grid (%s) that ended "
            "before %s; first at line %d: %s",
            len(skipped),
            option,
            today,
            line,
            reason,
        )
    return rows


def _ended_before(record: _Record, today: date) -> bool:
    """Tell whether a record has a valid end date before the given day."""
    end = record.get(_END)
    if not isinstance(end, str):
        return False  # The row stops before its end date.
    try:
        return _parse_date(_END, end.strip()) < today
    except ValueError:
        return False  # No end date or an unreadable one: the row may apply.


def _parse_record(option: TariffOption, record: _Record) -> TariffRow | None:
    """Parse a record of the CSV reader.

    Args:
        option: Tariff option of the grid.
        record: Cells of the row by column name.

    Returns:
        The row, or None when the line is blank or has no amount at all.

    Raises:
        ValueError: The row is invalid.
    """
    extra = record.get(None)
    if isinstance(extra, list) and any(field.strip() for field in extra):
        raise ValueError("the row has more fields than the header")
    cells = _cells(record)
    if not any(cells[column] for column in _amount_columns(option)):
        # A blank line, or a gap in the history: no price is known for this row.
        return None
    required = _required_columns(option)
    if any(cells[column] is None for column in required):
        raise ValueError("the row has fewer fields than the header")
    return _build_row(option, {column: cells[column] or "" for column in required})


def _cells(record: _Record) -> dict[str, str | None]:
    """Return the stripped cells of a record, None for the missing ones."""
    return {
        name: value.strip() if isinstance(value, str) else None
        for name, value in record.items()
        if name is not None
    }


def _build_row(option: TariffOption, values: Mapping[str, str]) -> TariffRow:
    """Build a tariff row from its stripped cells.

    Raises:
        ValueError: A cell is empty or cannot be parsed, or the row ends before it
            starts.
    """
    for column in (_START, _POWER, *_amount_columns(option)):
        if not values[column]:
            raise ValueError(f"{column} is empty")
    start = _parse_date(_START, values[_START])
    end = _parse_date(_END, values[_END]) if values[_END] else None
    if end is not None and end < start:
        raise ValueError(
            f"{_END} {end.isoformat()} is before {_START} {start.isoformat()}"
        )
    columns = _PRICE_COLUMNS[option]
    return TariffRow(
        start=start,
        end=end,
        power_kva=_parse_power(values[_POWER]),
        subscription=_parse_amount(_SUBSCRIPTION, values[_SUBSCRIPTION]),
        prices={
            key: _parse_amount(columns[key], values[columns[key]])
            for key in OPTION_PRICES[option]
        },
    )


def _parse_date(column: str, text: str) -> date:
    """Parse a ``DD/MM/YYYY`` or ``YYYY-MM-DD`` date.

    Raises:
        ValueError: The text is not a valid date.
    """
    match = _FRENCH_DATE.fullmatch(text) or _ISO_DATE.fullmatch(text)
    if match is None:
        raise ValueError(f"{column} is not a date: {text!r}")
    try:
        return date(int(match["year"]), int(match["month"]), int(match["day"]))
    except ValueError as err:
        raise ValueError(f"{column} is not a valid date: {text!r} ({err})") from err


def _parse_power(text: str) -> int:
    """Parse a subscribed power, a positive integer of kVA.

    Raises:
        ValueError: The text is not a positive integer.
    """
    if _INTEGER.fullmatch(text) is None or (power := int(text)) == 0:
        raise ValueError(f"{_POWER} is not a positive integer: {text!r}")
    return power


def _parse_amount(column: str, text: str) -> Decimal:
    """Parse an amount in euros, with ``,`` or ``.`` as decimal separator.

    The amount is parsed exactly, never through a float.

    Raises:
        ValueError: The text is not a number, or is negative.
    """
    if _AMOUNT.fullmatch(text) is None:
        raise ValueError(f"{column} is not an amount: {text!r}")
    amount = Decimal(text.replace(",", "."))
    if amount.is_signed():  # Also true for -0, which is no valid amount either.
        raise ValueError(f"{column} is negative: {text!r}")
    return amount


# Tempo colors.


async def _async_fetch_history(
    session: aiohttp.ClientSession, days: Sequence[date]
) -> dict[date, TempoColor]:
    """Download the Jour Tempo history and return the colors of some days.

    Raises:
        TempoConnectionError: The history could not be downloaded.
        TempoDataError: The history is invalid.
    """
    body = await _async_download(
        session, JOUR_TEMPO_HISTORY_URL, _HISTORY, TempoConnectionError
    )
    colors = parse_tempo_history(_decode(body, _HISTORY, TempoDataError), days)
    _LOGGER.debug(
        "%s downloaded: %d of %d requested colors known",
        _HISTORY,
        len(colors),
        len(days),
    )
    return colors


def _read_history_header(reader: csv.DictReader[str]) -> None:
    """Read and check the header line, ignoring spaces around the names."""
    if reader.fieldnames is None:
        raise TempoDataError(f"The {_HISTORY} is empty")
    header = [name.strip() for name in reader.fieldnames]
    reader.fieldnames = header
    required = (_HISTORY_DATE, _HISTORY_COLOR)
    if missing := [column for column in required if column not in header]:
        raise TempoDataError(
            f"The {_HISTORY} lacks the required columns: {', '.join(missing)}"
        )
    if duplicates := [column for column in required if header.count(column) > 1]:
        raise TempoDataError(
            f"The {_HISTORY} has duplicate columns: {', '.join(duplicates)}"
        )


def _read_history_colors(
    reader: csv.DictReader[str], days: frozenset[date]
) -> dict[date, TempoColor]:
    """Read the lines that follow the header and keep the requested colors.

    Raises:
        TempoDataError: A date cannot be read, the color of a requested day is
            unknown, or a requested day has two different colors.
    """
    colors: dict[date, TempoColor] = {}
    for record in reader:
        cells = _cells(record)
        if not any(cells.values()):
            continue  # A blank line.
        line = f"Line {reader.line_num} of the {_HISTORY}"
        day_text = cells[_HISTORY_DATE] or ""
        if (day := _parse_iso_date(day_text)) is None:
            raise TempoDataError(
                f"{line}: {_HISTORY_DATE} is not a valid date: {day_text!r}"
            )
        if day not in days or not (color_text := cells[_HISTORY_COLOR]):
            continue  # Another day, or a color not published yet.
        if (color := _HISTORY_COLORS.get(color_text.lower())) is None:
            raise TempoDataError(
                f"{line}: unknown {_HISTORY_COLOR} of {day.isoformat()}: {color_text!r}"
            )
        if colors.setdefault(day, color) != color:
            raise TempoDataError(
                f"{line}: {day.isoformat()} has two colors: {colors[day]} and {color}"
            )
    return colors


def _parse_iso_date(text: str) -> date | None:
    """Parse a ``YYYY-MM-DD`` date, or return None if the text is not one."""
    if (match := _ISO_DATE.fullmatch(text)) is None:
        return None
    try:
        return date(int(match["year"]), int(match["month"]), int(match["day"]))
    except ValueError:
        return None


async def _async_fetch_fallback(
    session: aiohttp.ClientSession, days: Sequence[date]
) -> dict[date, TempoColor]:
    """Download the Tempo colors of some days from api-couleur-tempo.fr.

    Raises:
        TempoConnectionError: The color of a day could not be downloaded.
        TempoDataError: The color of a day is invalid.
    """
    colors: dict[date, TempoColor] = {}
    for day in days:
        source = f"Tempo color of {day.isoformat()} from api-couleur-tempo.fr"
        body = await _async_download(
            session,
            FALLBACK_TEMPO_URL.format(day=day.isoformat()),
            source,
            TempoConnectionError,
        )
        if (color := _parse_fallback_color(source, day, body)) is not None:
            colors[day] = color
    _LOGGER.debug(
        "Tempo colors downloaded from api-couleur-tempo.fr: %d of %d known",
        len(colors),
        len(days),
    )
    return colors


def _parse_fallback_color(source: str, day: date, body: bytes) -> TempoColor | None:
    """Parse the color of a day returned by api-couleur-tempo.fr.

    Returns:
        The color of the day, or None when it is not known yet.

    Raises:
        TempoDataError: The body is not the JSON color of the day.
    """
    try:
        data = json.loads(body.decode("utf-8-sig"))
    except ValueError as err:  # UnicodeDecodeError is a ValueError too.
        raise TempoDataError(f"The {source} is not valid JSON: {err}") from err
    if not isinstance(data, dict):
        raise TempoDataError(f"The {source} is not a JSON object")
    if (answered := data.get(_FALLBACK_DATE)) != day.isoformat():
        raise TempoDataError(
            f"The {source} is for another day: {_FALLBACK_DATE} is {answered!r}"
        )
    code = data.get(_FALLBACK_CODE)
    # A JSON boolean is a Python int too, but no valid code.
    if (
        isinstance(code, bool)
        or not isinstance(code, int)
        or code not in _FALLBACK_COLORS
    ):
        raise TempoDataError(f"The {source} has an invalid {_FALLBACK_CODE}: {code!r}")
    return _FALLBACK_COLORS[code]
