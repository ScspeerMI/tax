"""Filer-level engine behind the web explorer (docs/).

The explorer needs answers the aggregate model can't give, such as how many
filers a reform affects and by how much. So it represents CRA's 19 income ranges
as about 500 representative "filer groups" (records). Each record has a taxable
income, a weight (number of filers), a Quebec share and credit amounts. Federal
tax is computed record by record, under current law and under the reform.

Calibration: CRA reports net federal tax by income range. The schedule plus
personal credits doesn't capture everything (dividend tax credit, donations,
foreign tax credit and so on), so each range gets a fixed extra credit, solved
so that modelled 2024 tax matches CRA's 2024 net federal tax. The extra credit
is never negative: below $40,000 of total income, the model can't reproduce
some of the tax CRA reports (about $2.5B of $223B), and leaves it out
rather than inventing a tax on every low-income filer.

This module is the reference implementation. docs/engine.js must produce the
same numbers; build_explorer.py checks that it does.
"""

import numpy as np

from . import sources
from .distribution import IncomeDistribution

DATA_YEAR = 2024
LAW_2024 = {
    "thresholds": [0, 55867, 111733, 173205, 246752],
    "rates": [0.15, 0.205, 0.26, 0.29, 0.33],
    "bpa_max": 15705, "bpa_min": 14156,
}
CLOSED_BINS = 25
# Quantile cut points for the Pareto top range; finer towards the very top.
TOP_CUTS = list(np.arange(0, 0.9, 0.025)) + [0.9, 0.925, 0.95, 0.97, 0.98, 0.99, 0.995,
                                              0.998, 0.999, 0.9995, 0.9999, 1.0]

# Display groups, as ranges of CRA income classes (by total income).
GROUPS = [
    ("Under $20k", range(0, 4)), ("$20k–$40k", range(4, 8)), ("$40k–$60k", range(8, 12)),
    ("$60k–$80k", range(12, 14)), ("$80k–$100k", range(14, 16)), ("$100k–$150k", range(16, 17)),
    ("$150k–$250k", range(17, 18)), ("$250k and over", range(18, 19)),
]


def build_records(nat, qc):
    """Representative records from CRA Table 2 (national and Quebec)."""
    dist = IncomeDistribution(nat)
    ti, w, cls = [], [], []
    for c in range(len(dist.n)):
        edges = np.linspace(dist.lo[c], dist.hi[c], CLOSED_BINS + 1)
        ti += list((edges[:-1] + edges[1:]) / 2)
        w += [dist.n[c] / CLOSED_BINS] * CLOSED_BINS
        cls += [c] * CLOSED_BINS

    # Pareto top: each bin carries its exact conditional mean.
    a, lo, top = dist.alpha, dist.top_lo, len(dist.n)
    k = 1 - 1 / a
    for ua, ub in zip(TOP_CUTS[:-1], TOP_CUTS[1:]):
        mean = lo / (ub - ua) * ((1 - ua) ** k - (1 - ub) ** k) / k
        ti.append(mean)
        w.append(dist.top_n * (ub - ua))
        cls.append(top)

    ti, w, cls = np.array(ti), np.array(w), np.array(cls)
    qc_share = (qc["taxable_income"] / nat["taxable_income"]).fillna(0).to_numpy()

    # Personal credit amounts per filer, excluding the basic personal amount
    # (CRA reports the credit value at 15%, so divide by 0.15 to get the amount).
    per_filer = (nat["personal_credit_amounts"] / nat["n_personal_credit_amounts"]).fillna(0).to_numpy() / 0.15
    bpa = bpa_amount(nat["taxable_income"].to_numpy() / nat["n_taxable_income"].to_numpy(),
                     LAW_2024["bpa_max"], LAW_2024["bpa_min"], LAW_2024["thresholds"][3], LAW_2024["thresholds"][4])
    other = np.clip(per_filer - bpa, 0, None)

    return {
        "ti": ti, "w": w, "cls": cls,
        "qc": qc_share[cls],
        "other_credits": other[cls],
        "fixed_credit": calibrate_fixed_credits(ti, w, cls, other[cls], nat),
    }


def bpa_amount(ti, bpa_max, bpa_min, phase_start, phase_end):
    """Basic personal amount: the enhanced part phases out between the 4th and 5th thresholds."""
    frac = np.clip((ti - phase_start) / (phase_end - phase_start), 0, 1)
    return bpa_max - (bpa_max - min(bpa_min, bpa_max)) * frac


def basic_tax(ti, thresholds, rates):
    tax = np.zeros_like(ti, dtype=float)
    edges = list(thresholds[1:]) + [np.inf]
    for lo, hi, r in zip(thresholds, edges, rates):
        tax += r * np.clip(np.minimum(ti, hi) - lo, 0, None)
    return tax


def tax_before_fixed(ti, other_credits, law):
    """Basic tax minus personal credits (credits are valued at the lowest rate)."""
    bpa = bpa_amount(ti, law["bpa_max"], law["bpa_min"], law["phase_start"], law["phase_end"])
    return basic_tax(ti, law["thresholds"], law["rates"]) - law["rates"][0] * (bpa + other_credits)


def calibrate_fixed_credits(ti, w, cls, other, nat):
    """Per-class fixed credit so modelled 2024 net federal tax equals CRA's."""
    law = dict(LAW_2024, phase_start=LAW_2024["thresholds"][3], phase_end=LAW_2024["thresholds"][4])
    pre = tax_before_fixed(ti, other, law)
    fixed = np.zeros(len(nat))
    target = nat["net_federal_tax"].to_numpy()
    for c in range(len(nat)):
        m = cls == c
        lo_c, hi_c = 0.0, 500_000.0
        for _ in range(100):  # bisection; modelled tax falls as the credit rises
            mid = (lo_c + hi_c) / 2
            if (w[m] * np.maximum(pre[m] - mid, 0)).sum() > target[c]:
                lo_c = mid
            else:
                hi_c = mid
        fixed[c] = (lo_c + hi_c) / 2
    return fixed[cls]


def current_law(a):
    """Current-law schedule from assumptions.yaml (2026 dollars)."""
    b = a["pit"]["brackets_2026"]
    return {
        "thresholds": list(b["thresholds"]), "rates": list(b["rates"]),
        "bpa_max": a["pit"]["basic_personal_amount_2026"]["value"],
        "bpa_min": a["pit"]["basic_personal_amount_min_2026"]["value"],
    }


def index_law(law, cpi_index, phase):
    """A 2026-dollar schedule expressed in a later year's dollars."""
    return {
        "thresholds": [t * cpi_index for t in law["thresholds"]], "rates": law["rates"],
        "bpa_max": law["bpa_max"] * cpi_index, "bpa_min": law["bpa_min"] * cpi_index,
        "phase_start": phase[0] * cpi_index, "phase_end": phase[1] * cpi_index,
    }


def federal_tax(ti, rec, law, growth):
    """Federal tax after the Quebec abatement, per filer in the record."""
    pre = tax_before_fixed(ti, rec["other_credits"] * rec["credit_index"], law) - rec["fixed_credit"] * growth
    return np.maximum(pre, 0) * (1 - rec["abatement"] * rec["qc"])


def score(reform, params, rec):
    """Score a reform (a dict like current_law's) against current law.

    params holds the projection: years, growth, cpi and credit indexes,
    provincial rates, elasticities, abatement and interest rate. Everything
    here is mirrored line for line in docs/engine.js.
    """
    base = params["current_law"]
    phase = (base["thresholds"][3], base["thresholds"][4])  # BPA phase-out stays on current-law thresholds
    rec = dict(rec, abatement=params["abatement"])
    out = {"years": params["years"], "static": [], "low": [], "central": [], "high": [], "provincial": []}

    for i, year in enumerate(params["years"]):
        g, cpi = params["growth"][i], params["cpi_index"][i]
        rec["credit_index"] = params["credit_index"][i]
        law0, law1 = index_law(base, cpi, phase), index_law(reform, cpi, phase)
        ti = rec["ti"] * g
        t0 = federal_tax(ti, rec, law0, g)
        t1 = federal_tax(ti, rec, law1, g)
        w = rec["w"]
        out["static"].append(float((w * (t1 - t0)).sum()))

        # Behaviour: response to the change in the combined marginal rate.
        h = 100.0
        m0 = (federal_tax(ti + h, rec, law0, g) - t0) / h
        m1 = (federal_tax(ti + h, rec, law1, g) - t1) / h
        prov_rates = np.array(params["provincial_rates"])
        prov = prov_rates[np.searchsorted(law0["thresholds"], ti, side="right") - 1]
        ratio = (1 - (m1 + prov)) / (1 - (m0 + prov))
        top = ti > law0["thresholds"][-1]
        for case in ("low", "central", "high"):
            eti = np.where(top, params["eti_top"][case], params["eti_lower"][case])
            d_ti = ti * (ratio ** eti - 1)
            t1b = federal_tax(ti + d_ti, rec, law1, g)
            out[case].append(float((w * (t1b - t0)).sum()))
            if case == "central":
                out["provincial"].append(float((w * d_ti * prov).sum()))

        if i == 0:
            out["distribution"] = distribution(t0, t1, ti, w, rec["cls"])

    central = np.array(out["central"])
    out["debt_service"] = list((np.cumsum(central) - central / 2) * params["interest_rate"])
    return out


def distribution(t0, t1, ti, w, cls):
    """First-year static effects by income group."""
    d = t1 - t0
    total = (w * d).sum()
    all_cuts = (w * np.minimum(d, 0)).sum()
    all_increases = (w * np.maximum(d, 0)).sum()
    rows = []
    for name, members in GROUPS:
        m = np.isin(cls, list(members))
        filers = w[m].sum()
        less = w[m][d[m] <= -1].sum()
        more = w[m][d[m] >= 1].sum()
        change = (w[m] * d[m]).sum()
        income = (w[m] * ti[m]).sum()
        rows.append({
            "group": name, "filers": float(filers), "pay_less": float(less), "pay_more": float(more),
            "avg_change": float(change / filers),
            "avg_change_affected": float(change / (less + more)) if less + more else 0.0,
            "income": float(income),
            "pct_income": float(change / income),
            "share": float(change / total) if total else 0.0,
            "share_of_cuts": float((w[m] * np.minimum(d[m], 0)).sum() / all_cuts) if all_cuts else 0.0,
            "share_of_increases": float((w[m] * np.maximum(d[m], 0)).sum() / all_increases) if all_increases else 0.0,
        })
    return rows


def load(a, wb):
    """Records plus projection parameters, ready for score() or for export."""
    nat = sources.cra_table2(DATA_YEAR, "ac")
    qc = sources.cra_table2(DATA_YEAR, "qc")
    rec = build_records(nat, qc)
    p = a["pit"]
    cpi = a["macro"]["cpi_inflation"]["value"]
    actual = p["credit_indexation_since_data_year"]["values"]
    credit_index = []
    for year in wb.years:
        idx = 1.0
        for y in range(DATA_YEAR + 1, year + 1):
            idx *= 1 + actual.get(y, cpi)
        credit_index.append(idx)
    rate = float(sources.boc_series(a["macro"]["interest_rate_series"]["value"]).iloc[-1]) / 100
    params = {
        "years": wb.years,
        "growth": [wb.growth(y, DATA_YEAR) for y in wb.years],
        "cpi_index": [wb.cpi_index(y) for y in wb.years],
        "credit_index": credit_index,
        "current_law": current_law(a),
        "provincial_rates": p["provincial_marginal_rate"]["values"],
        "eti_lower": {k: p["eti"]["lower_brackets"][k] for k in ("low", "central", "high")},
        "eti_top": {k: p["eti"]["top_bracket"][k] for k in ("low", "central", "high")},
        "abatement": p["quebec_abatement"]["value"],
        "interest_rate": rate,
    }
    return rec, params, (nat, qc)
