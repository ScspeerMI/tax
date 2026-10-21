"""Build the web explorer's data file and check the browser engine against Python.

    python build_explorer.py

Writes docs/data.json (filer records, projection parameters, sources and
calibration results), then runs docs/engine.js under Node on a set of test
reforms and confirms it matches workbench/explorer.py to within $1M a year.
Re-run this whenever assumptions.yaml or the source data change.
"""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np

from workbench import explorer
from workbench.model import Workbench

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
TOLERANCE = 1e6  # dollars per year


def test_reforms(law):
    def with_rate(i, r):
        rates = list(law["rates"])
        rates[i] = r
        return dict(law, rates=rates)

    return {
        "current law": law,
        "lowest rate 13%": with_rate(0, 0.13),
        "lowest rate back to 15%": with_rate(0, 0.15),
        "top rate 29%": with_rate(4, 0.29),
        "BPA $20,000": dict(law, bpa_max=20000),
        "new 36% bracket over $500k": dict(law, thresholds=law["thresholds"] + [500000], rates=law["rates"] + [0.36]),
        "flat 20%": dict(law, thresholds=[0], rates=[0.20]),
    }


def records_from(data):
    r = data["records"]
    return {k: np.array(r[k], dtype=float) for k in r} | {"cls": np.array(r["cls"])}


def main():
    wb = Workbench()
    rec, params, (nat, qc) = explorer.load(wb.a, wb)

    # Calibration check: modelled 2024 tax against CRA, by display group.
    law24 = dict(explorer.LAW_2024, phase_start=explorer.LAW_2024["thresholds"][3],
                 phase_end=explorer.LAW_2024["thresholds"][4])
    t24 = np.maximum(explorer.tax_before_fixed(rec["ti"], rec["other_credits"], law24) - rec["fixed_credit"], 0)
    calibration = []
    for name, members in explorer.GROUPS:
        m = np.isin(rec["cls"], list(members))
        cra = float(nat["net_federal_tax"].iloc[list(members)].sum())
        cra_taxable = float(nat["n_net_federal_tax"].iloc[list(members)].sum())
        calibration.append({
            "group": name, "model_tax": float((rec["w"][m] * t24[m]).sum()), "cra_tax": cra,
            "model_taxable": float(rec["w"][m][t24[m] > 0].sum()), "cra_taxable": cra_taxable,
        })

    sources = [wb._gdp.attrs["source"], nat.attrs["source"], qc.attrs["source"]]
    data = {
        "built": date.today().isoformat(),
        "data_year": explorer.DATA_YEAR,
        "params": params,
        "groups": [{"name": n, "classes": list(m)} for n, m in explorer.GROUPS],
        "records": {
            "ti": [round(float(v), 2) for v in rec["ti"]],
            "w": [round(float(v), 3) for v in rec["w"]],
            "cls": [int(v) for v in rec["cls"]],
            "qc": [round(float(v), 6) for v in rec["qc"]],
            "other_credits": [round(float(v), 2) for v in rec["other_credits"]],
            "fixed_credit": [round(float(v), 2) for v in rec["fixed_credit"]],
        },
        "calibration": calibration,
        "assumptions": {
            "nominal_gdp_growth": wb.a["macro"]["nominal_gdp_growth"],
            "cpi_inflation": wb.a["macro"]["cpi_inflation"],
            "eti_lower": wb.a["pit"]["eti"]["lower_brackets"],
            "eti_top": wb.a["pit"]["eti"]["top_bracket"],
            "provincial_marginal_rate": wb.a["pit"]["provincial_marginal_rate"],
            "benchmark_lowest_rate": wb.a["benchmarks"]["pit_lowest_rate_cut_2025"]["text"],
            "benchmark_top_rate": wb.a["benchmarks"]["pit_top_rate_2016"]["text"],
        },
        "sources": sources,
    }
    DOCS.mkdir(exist_ok=True)
    (DOCS / "data.json").write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote docs/data.json ({len(rec['ti'])} records)")

    # Score the test reforms in Python, from the same rounded records the browser sees.
    exported = json.loads((DOCS / "data.json").read_text(encoding="utf-8"))
    rec_r = records_from(exported)
    reforms = test_reforms(params["current_law"])
    expected = {name: explorer.score(r, params, rec_r) for name, r in reforms.items()}

    cases = ROOT / "tests" / "cases.json"
    cases.parent.mkdir(exist_ok=True)
    cases.write_text(json.dumps({"reforms": reforms}, default=float), encoding="utf-8")
    run = subprocess.run(["node", str(ROOT / "tests" / "run_engine.mjs"), str(cases)],
                         capture_output=True, text=True)
    if run.returncode != 0:
        print(run.stderr)
        sys.exit("Browser engine failed to run.")
    got = json.loads(run.stdout)

    worst, worst_dist = 0.0, 0.0
    for name, py in expected.items():
        js = got[name]
        for key in ("static", "low", "central", "high", "provincial", "debt_service"):
            worst = max(worst, float(np.max(np.abs(np.array(py[key]) - np.array(js[key])))))
        for a, b in zip(py["distribution"], js["distribution"]):
            for key in ("avg_change", "avg_change_affected", "pct_income", "share_of_cuts", "share_of_increases"):
                worst_dist = max(worst_dist, abs(a[key] - b[key]))
        print(f"  {name:30s} 10-yr central: Python {sum(py['central']) / 1e9:8.2f}B   "
              f"browser {sum(js['central']) / 1e9:8.2f}B")
    status = "OK" if worst <= TOLERANCE and worst_dist <= 0.01 else "MISMATCH"
    print(f"Largest difference: ${worst:,.0f} a year in revenue, ${worst_dist:.4f} per filer  ->  {status}")
    if status != "OK":
        sys.exit(1)


if __name__ == "__main__":
    main()
