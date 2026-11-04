"""International study permits to British Columbia — and who is coming to Canada.

Question: Where do BC's international students come from, and how is that
changing? This project answers it from IRCC's open study-permit data:
permits that became effective in each year (flows, not stocks).

Two lenses, because of how IRCC publishes the files:
  * British Columbia: permits by year and study level (the province file
    has no country split), plus BC's share of Canada.
  * Canada: top source countries by year (the country file has no
    province split). Province-by-country is not published in IRCC's
    current files, so countries are shown nationally, not for BC alone.
  * If the designated-learning-institution (DLI) file downloads, a third
    lens is added: BC's top institutions by permits. If it does not
    (the file has failed to open before), that lens is skipped with a
    warning and everything else still runs.

Run: python analysis.py  (downloads the IRCC CSVs if not already present,
prints findings, and writes filtered data to data/ and charts to charts/)

Calculations live in compute_*() / summarise(); plotting lives in the
plot_*() functions, so the numbers can be tested without drawing anything.
"""
import os
import socket
import urllib.request

socket.setdefaulttimeout(60)  # keep a stalled IRCC download from hanging the run

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

SCRATCH = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRATCH, "data")
CHART_DIR = os.path.join(SCRATCH, "charts")

PROVINCE_URL = ("https://www.ircc.canada.ca/opendata-donneesouvertes/data/"
                "ODP-TR-Study-IS_PT_study.csv")
COUNTRY_URL = ("https://www.ircc.canada.ca/opendata-donneesouvertes/data/"
               "ODP-TR-Study-IS_CITZ.csv")
DLI_URL = ("https://www.ircc.canada.ca/opendata-donneesouvertes/data/"
           "ODP-TR-Study-DLI_name_PT_Admin_type.csv")

PROVINCE_PATH = os.path.join(SCRATCH, "ircc_province_study.csv")
COUNTRY_PATH = os.path.join(SCRATCH, "ircc_country.csv")
DLI_PATH = os.path.join(SCRATCH, "ircc_dli.csv")

BC = "British Columbia"
LEVEL_POST_SECONDARY = "Post Secondary"
LEVEL_SECONDARY = "Secondary or less"
LEVEL_OTHER = "Other Studies"
LEVEL_NOT_STATED = "Education level not stated"


def download(url, path):
    """Download a file if not already present. Returns True on success."""
    if os.path.exists(path):
        return True
    print(f"Downloading {os.path.basename(path)} ...")
    try:
        urllib.request.urlretrieve(url, path)
    except Exception as exc:  # noqa: BLE001 - report and continue without it
        print(f"  WARNING: download failed ({exc}); continuing without it.")
        return False
    return True


def parse_total(value):
    """Parse an IRCC TOTAL cell.

    IRCC rounds values to the nearest 5 and suppresses values from 0 to 5
    as "--". Suppressed cells become NaN: they are excluded from sums,
    never counted as zero.
    """
    if value is None:
        return float("nan")
    text = str(value).strip()
    if text in ("", "--"):
        return float("nan")
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return float("nan")


def load_province(path):
    """Load the province/study-level file, normalised to English columns."""
    df = pd.read_csv(path, sep="\t", dtype=str, low_memory=False)
    df.columns = df.columns.str.strip()
    df = df.rename(columns={
        "EN_YEAR": "year",
        "EN_PROVINCE_TERRITORY": "province",
        "EN_STUDY_LEVEL": "level",
        "TOTAL": "total",
    })
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df["month"] = df["EN_MONTH"].astype(str).str.strip() if "EN_MONTH" in df else ""
    df["permits"] = df["total"].map(parse_total)
    return df.dropna(subset=["year"])


def load_country(path):
    """Load the country file (national, no province split)."""
    df = pd.read_csv(path, sep="\t", dtype=str, low_memory=False)
    df.columns = df.columns.str.strip()
    df = df.rename(columns={
        "EN_YEAR": "year",
        "EN_COUNTRY_OF_CITIZENSHIP": "country",
        "TOTAL": "total",
    })
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df["month"] = df["EN_MONTH"].astype(str).str.strip() if "EN_MONTH" in df else ""
    df["permits"] = df["total"].map(parse_total)
    return df.dropna(subset=["year"])


def complete_years(df, group_col=None):
    """Years with all 12 months present (the latest year is usually partial).

    With no group_col, completeness is judged on the whole file; with a
    group_col value (e.g. BC rows only), on that subset.
    """
    sub = df if group_col is None else df[df["province"] == group_col]
    months = sub.groupby("year")["month"].nunique()
    return sorted(int(y) for y, n in months.items() if n >= 12)


def compute_bc_yearly(prov, years):
    """BC permits by year and study level, plus BC's share of Canada."""
    bc = prov[(prov["province"] == BC) & (prov["year"].isin(years))]
    by_level = bc.pivot_table(index="year", columns="level", values="permits",
                              aggfunc="sum", dropna=False)
    for col in (LEVEL_POST_SECONDARY, LEVEL_SECONDARY, LEVEL_OTHER, LEVEL_NOT_STATED):
        if col not in by_level:
            by_level[col] = 0.0
    total = by_level.sum(axis=1)
    canada = (prov[prov["year"].isin(years)]
              .groupby("year")["permits"].sum(min_count=1))
    out = pd.DataFrame({
        "total": total,
        "post_secondary": by_level[LEVEL_POST_SECONDARY],
        "secondary_or_less": by_level[LEVEL_SECONDARY],
        "other_studies": by_level[LEVEL_OTHER],
        "level_not_stated": by_level[LEVEL_NOT_STATED],
        "post_secondary_share_pct": by_level[LEVEL_POST_SECONDARY] / total * 100,
        "bc_share_of_canada_pct": total / canada * 100,
    })
    out.index.name = "year"
    return out


def compute_countries(country, years, top_n=10):
    """Top source countries in the latest complete year, vs 2019.

    Returns a DataFrame with one row per country (top_n by latest year),
    plus the national total for share calculations.
    """
    sub = country[country["year"].isin(years)]
    piv = sub.pivot_table(index="country", columns="year", values="permits",
                          aggfunc="sum", dropna=False)
    latest = max(years)
    baseline = 2019 if 2019 in piv.columns else min(years)
    totals = sub.groupby("year")["permits"].sum(min_count=1)
    top = piv.sort_values(latest, ascending=False).head(top_n)
    out = pd.DataFrame({
        "permits_latest": top[latest],
        "permits_baseline": top[baseline] if baseline in top else float("nan"),
        "share_latest_pct": top[latest] / totals[latest] * 100,
    })
    out["change_pct"] = (out["permits_latest"] / out["permits_baseline"] - 1) * 100
    out.index.name = "country"
    return out, latest, baseline, totals


def try_load_dli(path):
    """Best-effort load of the DLI file; returns a BC top-institutions frame or None.

    Column names are detected, not assumed, because the file has not been
    inspected directly. Returns None if the file is missing or its columns
    do not match expectations.
    """
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, sep=None, engine="python", dtype=str)
    except Exception as exc:  # noqa: BLE001 - DLI lens is optional
        print(f"  WARNING: could not read DLI file ({exc}); skipping DLI lens.")
        return None
    cols = {c.strip().upper(): c for c in df.columns}
    prov_col = next((cols[c] for c in cols if "PROVINCE" in c), None)
    # The institution name column: prefer DESIGNATED (the DLI name column);
    # a bare "DLI" match would wrongly catch the province column.
    inst_col = next((cols[c] for c in cols if "DESIGNATED" in c), None)
    if inst_col is None:
        inst_col = next((cols[c] for c in cols
                         if "INSTITUTION" in c and "PROVINCE" not in c), None)
    year_col = cols.get("EN_YEAR") or next(
        (cols[c] for c in cols if "YEAR" in c), None)
    total_col = cols.get("TOTAL") or next(
        (cols[c] for c in cols if "TOTAL" in c), None)
    admin_col = next((cols[c] for c in cols if "ADMIN" in c), None)
    if not all([prov_col, inst_col, year_col, total_col]):
        print("  WARNING: DLI columns not recognised; skipping DLI lens.")
        return None
    rename = {prov_col: "province", inst_col: "institution",
              year_col: "year", total_col: "total"}
    if admin_col is not None:
        rename[admin_col] = "admin_type"
    df = df.rename(columns=rename)
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df["permits"] = df["total"].map(parse_total)
    df = df.dropna(subset=["year"])
    bc = df[df["province"].astype(str).str.strip() == BC]
    if bc.empty:
        print("  WARNING: no BC rows in DLI file; skipping DLI lens.")
        return None
    return bc


def compute_bc_institutions(bc_dli, years, top_n=10):
    """Top BC institutions by permits in the latest complete year."""
    sub = bc_dli[bc_dli["year"].isin(years)]
    piv = sub.pivot_table(index="institution", columns="year", values="permits",
                          aggfunc="sum", dropna=False)
    latest = max(years)
    top = piv.sort_values(latest, ascending=False).head(top_n)
    out = pd.DataFrame({"permits_latest": top[latest]})
    if "admin_type" in sub.columns:
        admin = (sub.groupby("institution")["admin_type"]
                 .agg(lambda s: s.mode().iloc[0] if not s.mode().empty else ""))
        out["admin_type"] = admin.reindex(out.index)
    out.index.name = "institution"
    return out, latest


def summarise(bc_yearly, countries, latest, baseline):
    """Headline findings as plain numbers, for printing and testing."""
    total = bc_yearly["total"]
    peak_year = int(total.idxmax())
    return {
        "years_min": int(total.index.min()),
        "years_max": int(total.index.max()),
        "bc_latest": total.loc[latest],
        "bc_peak": total.loc[peak_year],
        "bc_peak_year": peak_year,
        "bc_first": total.iloc[0],
        "bc_change_peak_to_latest": (total.loc[latest] / total.loc[peak_year] - 1) * 100,
        "bc_post_secondary_share_latest": bc_yearly["post_secondary_share_pct"].loc[latest],
        "bc_share_of_canada_latest": bc_yearly["bc_share_of_canada_pct"].loc[latest],
        "countries_latest_year": latest,
        "countries_baseline_year": baseline,
        "top_country": countries.index[0],
        "top_country_permits": countries.iloc[0]["permits_latest"],
        "top_country_share": countries.iloc[0]["share_latest_pct"],
        "top3_share": countries["share_latest_pct"].head(3).sum(),
    }


def print_findings(f):
    """Print the headline findings."""
    print("=== FINDINGS (study permits that became effective) ===")
    print(f"Years covered (complete years): {f['years_min']} to {f['years_max']}")
    print(f"BC total permits: {f['bc_first']:,.0f} in {f['years_min']}; "
          f"peak {f['bc_peak']:,.0f} in {f['bc_peak_year']}; "
          f"{f['bc_latest']:,.0f} in {f['years_max']} "
          f"({f['bc_change_peak_to_latest']:+.1f}% from peak)")
    print(f"BC post-secondary share of BC permits in {f['years_max']}: "
          f"{f['bc_post_secondary_share_latest']:.1f}%")
    print(f"BC share of Canada permits in {f['years_max']}: "
          f"{f['bc_share_of_canada_latest']:.1f}%")
    print(f"Top source country (Canada, {f['countries_latest_year']}): "
          f"{f['top_country']} ({f['top_country_permits']:,.0f} permits, "
          f"{f['top_country_share']:.1f}% of Canada)")
    print(f"Top 3 countries' share of Canada ({f['countries_latest_year']}): "
          f"{f['top3_share']:.1f}%")


def _save(fig, chart_dir, name):
    fig.tight_layout()
    fig.savefig(os.path.join(chart_dir, name + ".png"), dpi=150)
    fig.savefig(os.path.join(chart_dir, name + ".svg"))
    plt.close(fig)


def plot_bc_by_level(bc_yearly, chart_dir):
    """BC permits by year, stacked by study level."""
    years = [str(int(y)) for y in bc_yearly.index]
    x = range(len(years))
    fig, ax = plt.subplots(figsize=(10, 5.5))
    bottom = None
    for col, label, color in [
        ("post_secondary", "Post Secondary", "#1F4E79"),
        ("secondary_or_less", "Secondary or less", "#7FB3D5"),
        ("other_studies", "Other Studies", "#F2C572"),
        ("level_not_stated", "Level not stated", "#B0B0B0"),
    ]:
        values = bc_yearly[col]
        ax.bar(x, values, bottom=bottom, label=label, color=color)
        bottom = values if bottom is None else bottom + values
    ax.set_xticks(list(x)[::1], years, rotation=45)
    ax.set_ylabel("Study permits that became effective (BC)")
    ax.set_title("BC study permits by year and study level")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    _save(fig, chart_dir, "bc_permits_by_level")


def plot_top_countries(countries, latest, baseline, chart_dir):
    """Top source countries (Canada) in the latest year, vs baseline year.

    Only the latest year's bars are drawn; the change vs the baseline year
    is carried in the labels, so no baseline bar is ever hidden behind a
    larger latest-year bar.
    """
    data = countries.sort_values("permits_latest", ascending=True)
    fig, ax = plt.subplots(figsize=(10, 6.5))
    ax.barh(data.index, data["permits_latest"], color="#1F4E79")
    for i, (permits, change) in enumerate(zip(data["permits_latest"], data["change_pct"])):
        ax.text(permits + max(data["permits_latest"]) * 0.01, i,
                f"{permits:,.0f} ({change:+.0f}% vs {baseline})",
                va="center", fontsize=9)
    ax.set_xlabel("Study permits that became effective (Canada)")
    ax.set_title(f"Top source countries for study permits, Canada: {latest} "
                 f"(change vs {baseline} in brackets)")
    ax.grid(axis="x", alpha=0.3)
    ax.set_axisbelow(True)
    _save(fig, chart_dir, "top_countries")


def plot_bc_institutions(inst, latest, chart_dir):
    """Top BC designated learning institutions by post-secondary permits."""
    data = inst.sort_values("permits_latest", ascending=True)
    colors = ["#1F4E79" if t == "Public Institution" else "#C55A11"
              for t in data["admin_type"]]
    fig, ax = plt.subplots(figsize=(10, 6.5))
    ax.barh(data.index, data["permits_latest"], color=colors)
    for i, permits in enumerate(data["permits_latest"]):
        ax.text(permits + max(data["permits_latest"]) * 0.01, i,
                f"{permits:,.0f}", va="center", fontsize=9)
    ax.set_xlabel("Post-secondary study permits that became effective (BC)")
    ax.set_title(f"Top BC institutions by study permits, {latest} "
                 f"(navy = public, orange = private)")
    ax.grid(axis="x", alpha=0.3)
    ax.set_axisbelow(True)
    _save(fig, chart_dir, "bc_top_institutions")
def plot_executive_summary(bc_yearly, chart_dir):
    """One polished chart for the headline story.

    Bars: BC study permits by year. Line: BC's share of Canada's permits.
    The takeaway sentence is set from the computed values in the README.
    """
    years = [str(int(y)) for y in bc_yearly.index]
    x = range(len(years))
    total = bc_yearly["total"]
    share = bc_yearly["bc_share_of_canada_pct"]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.bar(x, total, color="#1F4E79", label="BC study permits")
    ax.set_ylabel("Study permits that became effective (BC)")
    ax.set_ylim(0, total.max() * 1.15)
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax2 = ax.twinx()
    ax2.plot(x, share, color="#C55A11", marker="o", markersize=3, linewidth=2,
             label="BC share of Canada (%)")
    ax2.set_ylabel("BC share of Canada (%)")
    ax2.set_ylim(0, share.max() * 1.3)
    ax2.spines["top"].set_visible(False)
    peak_idx = list(total.index).index(total.idxmax())
    last_idx = len(years) - 1
    ax.annotate(f"Peak {int(total.index[peak_idx])}: {total.iloc[peak_idx]:,.0f}",
                (peak_idx, total.iloc[peak_idx]),
                textcoords="offset points", xytext=(0, 8), ha="center", fontsize=9)
    ax.annotate(f"{years[last_idx]}: {total.iloc[last_idx]:,.0f}",
                (last_idx, total.iloc[last_idx]),
                textcoords="offset points", xytext=(0, 8), ha="center", fontsize=9)
    ax.set_xticks(list(x), years, rotation=45)
    ax.set_title("BC study permits by year — and BC's share of Canada",
                 fontsize=13, fontweight="bold", pad=12)
    lines, labels = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines + lines2, labels + labels2, loc="upper left")
    _save(fig, chart_dir, "executive_summary")


def main():
    have_prov = download(PROVINCE_URL, PROVINCE_PATH)
    have_country = download(COUNTRY_URL, COUNTRY_PATH)
    have_dli = download(DLI_URL, DLI_PATH)
    if not (have_prov and have_country):
        print("ERROR: essential IRCC files could not be downloaded; aborting.")
        return

    prov = load_province(PROVINCE_PATH)
    country = load_country(COUNTRY_PATH)
    years = complete_years(prov, group_col=BC)
    print(f"Complete years for BC: {years[0]}-{years[-1]} "
          f"(latest year in file is partial and excluded)")

    bc_yearly = compute_bc_yearly(prov, years)
    countries, latest, baseline, _ = compute_countries(country, years)
    findings = summarise(bc_yearly, countries, latest, baseline)
    print_findings(findings)

    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(CHART_DIR, exist_ok=True)
    bc_yearly.to_csv(os.path.join(DATA_DIR, "bc_permits_by_year.csv"))
    countries.to_csv(os.path.join(DATA_DIR, "canada_top_countries.csv"))

    plot_bc_by_level(bc_yearly, CHART_DIR)
    plot_top_countries(countries, latest, baseline, CHART_DIR)
    plot_executive_summary(bc_yearly, CHART_DIR)

    if have_dli:
        bc_dli = try_load_dli(DLI_PATH)
        if bc_dli is not None:
            inst, inst_year = compute_bc_institutions(bc_dli, years)
            inst.to_csv(os.path.join(DATA_DIR, "bc_top_institutions.csv"))
            plot_bc_institutions(inst, inst_year, CHART_DIR)
            print(f"BC top institutions ({inst_year}):")
            print(inst.to_string())
    print("Charts written to", CHART_DIR)


if __name__ == "__main__":
    main()
