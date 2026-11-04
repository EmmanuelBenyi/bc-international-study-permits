"""Tests for the BC study-permits analysis.

Calculations are tested on small synthetic frames (no downloads), plus a
few regression checks against the data files the script writes.
"""
import math
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import (BC, complete_years, compute_bc_institutions,
                      compute_bc_yearly, compute_countries, parse_total)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data")


def test_parse_total():
    assert parse_total("120") == 120.0
    assert parse_total("  45 ") == 45.0
    assert math.isnan(parse_total("--"))
    assert math.isnan(parse_total(""))
    assert math.isnan(parse_total(None))
    assert math.isnan(parse_total("not a number"))


def _province_frame():
    # BC + Ontario, two years, one suppressed ("--") BC cell.
    rows = []
    for year, bc_ps, bc_sec, on_ps in [(2023, 100, 50, 400), (2024, 90, 60, 380)]:
        rows.append({"year": year, "province": BC, "level": "Post Secondary",
                     "month": "Jan", "permits": float(bc_ps)})
        rows.append({"year": year, "province": BC, "level": "Secondary or less",
                     "month": "Jan", "permits": float(bc_sec)})
        rows.append({"year": year, "province": "Ontario", "level": "Post Secondary",
                     "month": "Jan", "permits": float(on_ps)})
    rows.append({"year": 2024, "province": BC, "level": "Other Studies",
                 "month": "Jan", "permits": float("nan")})  # suppressed cell
    return pd.DataFrame(rows)


def test_bc_yearly_totals_and_suppression():
    out = compute_bc_yearly(_province_frame(), [2023, 2024])
    # Suppressed cells are excluded, not counted as zero: 2024 BC total is
    # 90 + 60 = 150, and the NaN "Other Studies" row adds nothing.
    assert out.loc[2023, "total"] == 150.0
    assert out.loc[2024, "total"] == 150.0
    assert out.loc[2023, "post_secondary"] == 100.0
    assert out.loc[2024, "secondary_or_less"] == 60.0
    # BC share of Canada: 150 / (150 + 400) in 2023.
    assert out.loc[2023, "bc_share_of_canada_pct"] == pytest.approx(150 / 550 * 100)
    assert out.loc[2023, "post_secondary_share_pct"] == pytest.approx(100 / 150 * 100)


def test_complete_years_requires_twelve_months():
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    rows = [{"year": 2023, "province": BC, "month": m, "permits": 10.0}
            for m in months]
    rows += [{"year": 2024, "province": BC, "month": m, "permits": 10.0}
             for m in months[:9]]  # partial year
    df = pd.DataFrame(rows)
    assert complete_years(df, group_col=BC) == [2023]


def _country_frame():
    rows = []
    for year, india, nigeria in [(2019, 1000, 100), (2025, 700, 300)]:
        rows.append({"year": year, "country": "India", "month": "Jan",
                     "permits": float(india)})
        rows.append({"year": year, "country": "Nigeria", "month": "Jan",
                     "permits": float(nigeria)})
    return pd.DataFrame(rows)


def test_countries_ranking_change_and_share():
    out, latest, baseline, _ = compute_countries(_country_frame(), [2019, 2025])
    assert latest == 2025 and baseline == 2019
    assert list(out.index) == ["India", "Nigeria"]
    assert out.loc["India", "change_pct"] == pytest.approx(-30.0)
    assert out.loc["Nigeria", "change_pct"] == pytest.approx(200.0)
    assert out.loc["India", "share_latest_pct"] == pytest.approx(70.0)


def test_bc_institutions_ranking_and_admin_type():
    rows = []
    for inst, admin, permits in [("Uni A", "Public Institution", 500),
                                 ("Uni B", "Private Institution", 900),
                                 ("Uni A", "Public Institution", 100)]:
        rows.append({"year": 2025, "institution": inst, "admin_type": admin,
                     "permits": float(permits)})
    df = pd.DataFrame(rows)
    out, latest = compute_bc_institutions(df, [2025])
    assert latest == 2025
    assert list(out.index) == ["Uni B", "Uni A"]
    assert out.loc["Uni B", "permits_latest"] == 900.0
    assert out.loc["Uni A", "admin_type"] == "Public Institution"


def test_saved_bc_yearly_regression():
    bc = pd.read_csv(os.path.join(DATA_DIR, "bc_permits_by_year.csv"), index_col="year")
    assert bc.loc[2023, "total"] == 130760.0
    assert bc.loc[2025, "total"] == 80565.0
    assert bc.loc[2025, "post_secondary_share_pct"] == pytest.approx(63.2, abs=0.1)
    assert bc.loc[2025, "bc_share_of_canada_pct"] == pytest.approx(20.1, abs=0.1)


def test_saved_countries_regression():
    countries = pd.read_csv(os.path.join(DATA_DIR, "canada_top_countries.csv"),
                            index_col="country")
    assert countries.loc["India", "permits_latest"] == 98945.0
    assert countries.loc["Nigeria", "change_pct"] == pytest.approx(252.1, abs=0.2)
    assert countries.index[0] == "India"
