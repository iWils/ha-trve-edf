"""Tests of the conversion of tariff grids to and from saved data."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.trve_edf.models import grid_from_dict, grid_to_dict

from .common import BASE_GRID, HPHC_GRID, TEMPO_GRID


@pytest.mark.parametrize(
    "grid", [BASE_GRID, HPHC_GRID, TEMPO_GRID], ids=["base", "hphc", "tempo"]
)
async def test_round_trip(grid: Any) -> None:
    """A grid converted to data and back is unchanged, amounts included."""
    assert grid_from_dict(grid_to_dict(grid)) == grid


def _base_data() -> dict[str, Any]:
    return grid_to_dict(BASE_GRID)


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(None, id="none"),
        pytest.param("grid", id="text"),
        pytest.param({**_base_data(), "option": "unknown"}, id="unknown-option"),
        pytest.param({**_base_data(), "rows": []}, id="no-row"),
        pytest.param({"option": "base"}, id="no-rows-key"),
        pytest.param(
            {**_base_data(), "rows": [{**_base_data()["rows"][0], "start": "x"}]},
            id="bad-date",
        ),
        pytest.param(
            {
                **_base_data(),
                "rows": [{**_base_data()["rows"][0], "subscription": "abc"}],
            },
            id="bad-amount",
        ),
        pytest.param(
            {**_base_data(), "rows": [{**_base_data()["rows"][0], "prices": {}}]},
            id="missing-price",
        ),
        pytest.param({**grid_to_dict(HPHC_GRID), "option": "base"}, id="wrong-periods"),
    ],
)
async def test_invalid_data(data: Any) -> None:
    """Data that is not a valid grid gives None."""
    assert grid_from_dict(data) is None


async def test_grid_saved_by_version_0_1_0_is_read() -> None:
    """A grid saved by 0.1.0, as written on disk, is read unchanged."""
    saved = {
        "option": "hphc",
        "rows": [
            {
                "start": "2026-08-01",
                "end": None,
                "power_kva": 6,
                "subscription": "190.8131821",
                "prices": {"peak": "0.2142", "off_peak": "0.1589"},
            }
        ],
    }

    grid = grid_from_dict(saved)

    assert grid is not None
    assert grid_to_dict(grid) == saved
