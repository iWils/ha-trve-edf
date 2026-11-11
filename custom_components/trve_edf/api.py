"""Client of the regulated tariff grids published by the CRE.

All the network access of the integration goes through this module. It receives
the HTTP session from its caller (Home Assistant's shared session in the
integration) and has no Home Assistant dependency.

The CRE publishes one CSV file per tariff option on data.gouv.fr, with ``;`` as
separator and a header line. The columns are read by their name, and only the
amounts with taxes included (TTC) are kept. A grid is either fully valid or
rejected: an invalid response is never kept.
"""

from __future__ import annotations

from collections.abc import Mapping
import csv
from datetime import date
from decimal import Decimal
from http import HTTPStatus
import io
import logging
import re
from typing import Final

import aiohttp

from .models import OPTION_PERIODS, TariffGrid, TariffOption, TariffPeriod, TariffRow

_LOGGER = logging.getLogger(__name__)

CRE_GRID_URLS: Final[Mapping[TariffOption, str]] = {
    TariffOption.BASE: (
        "https://www.data.gouv.fr/fr/datasets/r/c13d05e5-9e55-4d03-bf7e-042a2ade7e49"
    ),
    TariffOption.HPHC: (
        "https://www.data.gouv.fr/fr/datasets/r/f7303b3a-93c7-4242-813d-84919034c416"
    ),
}
"""Stable data.gouv.fr URL of the CRE tariff grid of each option.

Each URL redirects to the file on the CRE website.
"""

REQUEST_TIMEOUT: Final = aiohttp.ClientTimeout(total=30)
"""Timeout of a whole request, from connection to the end of the body."""

_START: Final = "DATE_DEBUT"
_END: Final = "DATE_FIN"
_POWER: Final = "P_SOUSCRITE"
_SUBSCRIPTION: Final = "PART_FIXE_TTC"
_PRICE_COLUMNS: Final[Mapping[TariffOption, Mapping[TariffPeriod, str]]] = {
    TariffOption.BASE: {TariffPeriod.BASE: "PART_VARIABLE_TTC"},
    TariffOption.HPHC: {
        TariffPeriod.PEAK: "PART_VARIABLE_HP_TTC",
        TariffPeriod.OFF_PEAK: "PART_VARIABLE_HC_TTC",
    },
}
"""Column of the price of each period, for each option."""

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


async def async_fetch_grid(
    session: aiohttp.ClientSession, option: TariffOption
) -> TariffGrid:
    """Download and parse the CRE tariff grid of an option.

    The body is decoded as UTF-8 (with or without byte order mark), or as
    Windows-1252 when it is not valid UTF-8.

    Args:
        session: HTTP session used for the request.
        option: Tariff option of the grid.

    Returns:
        The grid of the option, with its rows in file order.

    Raises:
        CreConnectionError: The grid could not be downloaded.
        CreDataError: The downloaded grid is invalid.
    """
    try:
        async with session.get(
            CRE_GRID_URLS[option], timeout=REQUEST_TIMEOUT, allow_redirects=True
        ) as response:
            if response.status >= HTTPStatus.BAD_REQUEST:
                raise CreConnectionError(
                    f"The CRE tariff grid ({option}) could not be downloaded: "
                    f"HTTP status {response.status}"
                )
            body = await response.read()
    except (aiohttp.ClientError, TimeoutError) as err:
        reason = str(err) or type(err).__name__
        raise CreConnectionError(
            f"The CRE tariff grid ({option}) could not be downloaded: {reason}"
        ) from err
    grid = parse_grid(option, _decode(option, body))
    _LOGGER.debug("CRE tariff grid (%s) downloaded: %d rows", option, len(grid.rows))
    return grid


def parse_grid(option: TariffOption, text: str) -> TariffGrid:
    """Parse the CSV tariff grid of an option, as published by the CRE.

    Columns are read by their header name, extra columns are ignored. Dates may
    be written ``DD/MM/YYYY`` or ``YYYY-MM-DD``, decimals with ``,`` or ``.``.
    Blank lines and rows without any amount (gaps in the history) are skipped.

    Args:
        option: Tariff option of the grid.
        text: Content of the CSV file.

    Returns:
        The grid of the option, with its rows in file order.

    Raises:
        CreDataError: The grid is invalid: a required column is missing, a cell
            cannot be parsed, a row is inconsistent or no row is usable.
    """
    reader = csv.DictReader(
        io.StringIO(text.removeprefix(_BOM), newline=""),
        delimiter=";",
        skipinitialspace=True,
    )
    rows: list[TariffRow] = []
    try:
        _read_header(option, reader)
        for record in reader:
            if (row := _parse_record(option, record, reader.line_num)) is not None:
                rows.append(row)
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


def _decode(option: TariffOption, body: bytes) -> str:
    """Decode the body of a CRE tariff grid."""
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        text = body.decode("cp1252")
    except UnicodeDecodeError as err:
        raise CreDataError(
            f"The CRE tariff grid ({option}) is neither UTF-8 nor Windows-1252 text"
        ) from err
    _LOGGER.debug("CRE tariff grid (%s) decoded as Windows-1252", option)
    return text


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


def _parse_record(
    option: TariffOption, record: Mapping[str | None, str | list[str] | None], line: int
) -> TariffRow | None:
    """Parse a record of the CSV reader.

    Args:
        option: Tariff option of the grid.
        record: Cells of the row by column name. Cells beyond the header are
            listed under None; columns beyond the row are None.
        line: Line number of the row, for the error messages.

    Returns:
        The row, or None when the line is blank or has no amount at all.

    Raises:
        CreDataError: The row is invalid.
    """
    extra = record.get(None)
    if isinstance(extra, list) and any(field.strip() for field in extra):
        raise _row_error(option, line, "the row has more fields than the header")
    cells = {
        name: value.strip() if isinstance(value, str) else None
        for name, value in record.items()
        if name is not None
    }
    if not any(cells[column] for column in _amount_columns(option)):
        # A blank line, or a gap in the history: no price is known for this row.
        return None
    required = _required_columns(option)
    if any(cells[column] is None for column in required):
        raise _row_error(option, line, "the row has fewer fields than the header")
    try:
        return _build_row(option, {column: cells[column] or "" for column in required})
    except ValueError as err:
        raise _row_error(option, line, str(err)) from err


def _row_error(option: TariffOption, line: int, detail: str) -> CreDataError:
    """Return the error about an invalid row of a CRE tariff grid."""
    return CreDataError(f"Line {line} of the CRE tariff grid ({option}): {detail}")


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
            period: _parse_amount(columns[period], values[columns[period]])
            for period in OPTION_PERIODS[option]
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
