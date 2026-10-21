"""Data fetchers for Canadian fiscal data.

Every download is cached in data/raw/ next to a .meta.json file recording the
source, URL and retrieval date, so any number in a memo can be traced back.
Delete a cached file (or pass refresh=True) to fetch a fresh copy.
"""

import csv
import io
import json
from datetime import date
from pathlib import Path

import pandas as pd
import requests

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
HEADERS = {"User-Agent": "fiscal-workbench/0.1 (research use)"}

# CRA's Table 2 income ranges ("total income assessed"), in dollars.
CRA_CLASS_BOUNDS = [
    (0, 5_000), (5_000, 10_000), (10_000, 15_000), (15_000, 20_000),
    (20_000, 25_000), (25_000, 30_000), (30_000, 35_000), (35_000, 40_000),
    (40_000, 45_000), (45_000, 50_000), (50_000, 55_000), (55_000, 60_000),
    (60_000, 70_000), (70_000, 80_000), (80_000, 90_000), (90_000, 100_000),
    (100_000, 150_000), (150_000, 250_000), (250_000, float("inf")),
]

# StatCan table 36-10-0104: nominal GDP, current prices, SAAR, millions.
NOMINAL_GDP_VECTOR = 62305783


def _cached(name, url, fetch, source, notes="", refresh=False):
    """Return cached bytes for `name`, downloading with `fetch()` if needed."""
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / name
    if refresh or not path.exists():
        path.write_bytes(fetch())
        meta = {"source": source, "url": url, "retrieved": date.today().isoformat(), "notes": notes}
        path.with_suffix(path.suffix + ".meta.json").write_text(json.dumps(meta, indent=2))
    return path.read_bytes()


def provenance(name):
    """The metadata recorded when a cached file was downloaded."""
    return json.loads((RAW / (name + ".meta.json")).read_text())


def _get(url):
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.content


def _post(url, payload):
    r = requests.post(url, json=payload, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.content


# --- CRA individual income tax statistics (formerly T1 Final Statistics) ---

def cra_table2_name(year, geo="ac"):
    return f"cra_t1_table2_{geo}_{year}.csv"


def cra_table2(year, geo="ac", refresh=False):
    """CRA Table 2 (line items by income range) for a tax year.

    geo: "ac" = all of Canada, "qc" = Quebec, etc.
    Returns a DataFrame with one row per income class: lo, hi, and for each
    line item a count column (n_<item>) and a dollar column (<item>).
    """
    base = f"https://www.canada.ca/content/dam/cra-arc/prog-policy/stats/t1-final-stats/{year}-tax-year/"
    # CRA renamed the files from tbl2_ac.csv to tbl2_ac_en.csv with the 2024 edition.
    candidates = [f"tbl2_{geo}_en.csv", f"tbl2_{geo}.csv"]

    def fetch():
        for f in candidates:
            r = requests.get(base + f, headers=HEADERS, timeout=60)
            if r.ok:
                return r.content
        raise RuntimeError(f"No CRA Table 2 found for {year} ({geo}) under {base}")

    raw = _cached(cra_table2_name(year, geo), base + candidates[0], fetch,
                  source=f"Canada Revenue Agency, Individual Income Tax Return Statistics, {year} tax year, "
                         f"Table 2 ({'all of Canada' if geo == 'ac' else geo.upper()})",
                  notes="Amounts in thousands of dollars in the source; converted to dollars on load.",
                  refresh=refresh)
    rows = list(csv.reader(io.StringIO(raw.decode("latin-1"))))
    n_values = 2 * (len(CRA_CLASS_BOUNDS) + 1)  # (count, $000) for Total + each class

    items = {}
    for row in rows[1:]:
        if len(row) < n_values + 2:
            continue
        label = row[1].strip().lower()
        values = [float(v) if v.strip() not in ("", "-") else 0.0 for v in row[-n_values:]]
        items[label] = values[2:]  # drop the Total pair

    out = pd.DataFrame(CRA_CLASS_BOUNDS, columns=["lo", "hi"])
    wanted = {
        "taxable income assessed": "taxable_income",
        "total income assessed": "total_income",
        "taxable capital gains": "taxable_capital_gains",
        "capital gains deduction": "capital_gains_deduction",
        "net capital losses of other years": "net_capital_losses",
        "net federal tax": "net_federal_tax",
        "total tax credits on personal amounts": "personal_credit_amounts",
    }
    for label, col in wanted.items():
        values = items.get(label)
        if values is None:
            raise KeyError(f"'{label}' not found in CRA Table 2 for {year} ({geo})")
        out["n_" + col] = values[0::2]
        out[col] = [v * 1000 for v in values[1::2]]
    out.attrs["source"] = provenance(cra_table2_name(year, geo))
    return out


# --- Statistics Canada Web Data Service ---

def statcan_vector(vector_id, periods=40, refresh=False):
    """Latest `periods` observations of a StatCan vector, as a Series by date."""
    url = "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods"
    name = f"statcan_v{vector_id}.json"
    raw = _cached(name, url, lambda: _post(url, [{"vectorId": vector_id, "latestN": periods}]),
                  source=f"Statistics Canada, vector v{vector_id}", refresh=refresh)
    obj = json.loads(raw)[0]["object"]
    points = obj["vectorDataPoint"]
    s = pd.Series({pd.Timestamp(p["refPer"]): p["value"] for p in points}).sort_index()
    s.attrs["source"] = provenance(name)
    return s


def nominal_gdp_annual(refresh=False):
    """Annual nominal GDP ($ millions) for complete calendar years only."""
    q = statcan_vector(NOMINAL_GDP_VECTOR, periods=48, refresh=refresh)
    by_year = q.groupby(q.index.year)
    annual = by_year.mean()[by_year.count() == 4]
    annual.attrs["source"] = q.attrs["source"]
    annual.attrs["source"]["notes"] = "Table 36-10-0104, current prices, SAAR; annual = mean of four quarters."
    return annual


# --- Bank of Canada Valet API ---

def boc_series(series, recent=30, refresh=False):
    """Recent observations of a Bank of Canada series, as a Series by date."""
    url = f"https://www.bankofcanada.ca/valet/observations/{series}/json?recent={recent}"
    name = f"boc_{series}.json"
    raw = _cached(name, url, lambda: _get(url), source=f"Bank of Canada Valet API, {series}", refresh=refresh)
    obs = json.loads(raw)["observations"]
    s = pd.Series({pd.Timestamp(o["d"]): float(o[series]["v"]) for o in obs if series in o}).sort_index()
    s.attrs["source"] = provenance(name)
    return s
