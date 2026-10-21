"""Static and behavioural (Tier 1 and Tier 2) revenue estimates.

Each measure returns a Score: the change in federal revenue for each year of
the window, in dollars. Negative numbers are a cost (lost revenue).

- static: the rate change times the current base, with nobody changing behaviour.
- low / central / high: static plus the behavioural response, using the low,
  central and high elasticities from assumptions.yaml. Note that "low" means
  the low elasticity, which is the *smaller* behavioural offset.
- provincial: the knock-on change in provincial revenue (central case). Provinces
  other than Quebec tax the federal definition of income, so when federal
  changes shrink or grow the base, provincial revenue moves too.

There is no macroeconomic feedback here (growth, investment, wages). That is Tier 3.
"""

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

from . import explorer, sources

ROOT = Path(__file__).resolve().parent.parent
CASES = ("low", "central", "high")
BRACKET_NAMES = ["lowest", "second", "third", "fourth", "top"]


@dataclass
class Score:
    title: str
    measure: str
    years: list
    static: np.ndarray
    low: np.ndarray
    central: np.ndarray
    high: np.ndarray
    provincial: np.ndarray
    assumptions: list = field(default_factory=list)  # (label, value, source)
    caveats: list = field(default_factory=list)
    benchmark: str = ""
    sources: list = field(default_factory=list)
    debt_service: np.ndarray = None
    interest_rate: float = None


class Workbench:
    """Loads assumptions and data once; each method scores one kind of measure."""

    def __init__(self, assumptions_path=ROOT / "assumptions.yaml", overrides=(), refresh=False):
        self.a = yaml.safe_load(Path(assumptions_path).read_text())
        # Overrides look like "macro.nominal_gdp_growth.value=0.03".
        for item in overrides:
            path, value = item.split("=", 1)
            *parents, last = path.split(".")
            node = self.a
            for key in parents:
                node = node[key]
            node[last] = yaml.safe_load(value)
        self.refresh = refresh
        self._gdp = sources.nominal_gdp_annual(refresh=refresh)
        w = self.a["window"]
        self.years = list(range(w["start_year"], w["start_year"] + w["years"]))

    # --- projections ---

    def gdp(self, year):
        """Nominal GDP ($ millions): actual where published, then the growth assumption."""
        last = int(self._gdp.index.max())
        if year <= last:
            return float(self._gdp[year])
        g = self.a["macro"]["nominal_gdp_growth"]["value"]
        return float(self._gdp[last]) * (1 + g) ** (year - last)

    def growth(self, year, data_year):
        """How much bigger a base tied to nominal GDP is in `year` than in `data_year`."""
        return self.gdp(year) / self.gdp(data_year)

    def cpi_index(self, year, since=2026):
        cpi = self.a["macro"]["cpi_inflation"]["value"]
        return (1 + cpi) ** (year - since)

    def thresholds(self, year):
        b = self.a["pit"]["brackets_2026"]
        return [t * self.cpi_index(year) for t in b["thresholds"]]

    def _debt_service(self, score):
        """Extra public debt charges from carrying the central-case cost as debt."""
        series = self.a["macro"]["interest_rate_series"]["value"]
        y = sources.boc_series(series, refresh=self.refresh)
        rate = float(y.iloc[-1]) / 100
        change = score.central
        debt = np.cumsum(change) - change / 2  # mid-year convention
        score.debt_service = debt * rate
        score.interest_rate = rate
        score.sources.append(y.attrs["source"])
        return score

    def _common_sources(self):
        return [self._gdp.attrs["source"]]

    # --- personal income tax ---

    def pit_rate(self, bracket, new_rate):
        """Change the federal rate on one bracket (0 = lowest, 4 = top)."""
        law = explorer.current_law(self.a)
        rates = list(law["rates"])
        old_rate, rates[bracket] = rates[bracket], new_rate
        return self.pit_reform(dict(law, rates=rates), bracket=bracket,
                               title=f"Federal {BRACKET_NAMES[bracket]}-bracket rate: {old_rate:.1%} to {new_rate:.1%}",
                               measure=f"pit_rate bracket={bracket} new_rate={new_rate}")

    def pit_reform(self, reform, bracket=None, title="Personal income tax reform", measure="pit_reform"):
        """Score any federal schedule (thresholds, rates, basic personal amount).

        Uses the filer-level engine in explorer.py, the same one behind the web explorer.
        """
        p = self.a["pit"]
        rec, params, (nat, qc) = explorer.load(self.a, self)
        r = explorer.score(reform, params, rec)
        top = bracket == len(p["brackets_2026"]["rates"]) - 1
        score = Score(
            title=title, measure=measure, years=self.years,
            static=np.array(r["static"]), provincial=np.array(r["provincial"]),
            **{c: np.array(r[c]) for c in CASES},
            assumptions=[
                ("Filers and income", f"CRA Table 2, {explorer.DATA_YEAR} tax year, as about 500 representative filer groups",
                 "Grown with nominal GDP; brackets and credits indexed to CPI; calibrated to CRA net federal tax by income range"),
                ("Brackets and rates", "2026 federal schedule", p["brackets_2026"]["source"]),
                ("Elasticity of taxable income (lower brackets)",
                 " / ".join(str(p["eti"]["lower_brackets"][c]) for c in CASES), p["eti"]["lower_brackets"]["source"]),
                ("Elasticity of taxable income (top bracket)",
                 " / ".join(str(p["eti"]["top_bracket"][c]) for c in CASES), p["eti"]["top_bracket"]["source"]),
                ("Provincial marginal rates by bracket", p["provincial_marginal_rate"]["values"], p["provincial_marginal_rate"]["source"]),
                ("Quebec abatement", p["quebec_abatement"]["value"], p["quebec_abatement"]["source"]),
                ("Nominal GDP growth", self.a["macro"]["nominal_gdp_growth"]["value"], self.a["macro"]["nominal_gdp_growth"]["source"]),
            ],
            caveats=[
                "CRA groups filers by total income, not taxable income; the spread of taxable income within each range is interpolated.",
                "Above $250,000 the estimate rests on a Pareto shape fitted to one group average. The top bracket's base is sensitive to that shape.",
                "Credits other than the basic personal amount are set at each income range's average, so the split between filers who owe tax and those who don't is approximate.",
                "Below $40,000 of total income the model leaves out about $2.5B of the tax CRA reports (of $223B), which it can't attribute.",
                "The response is applied to the whole taxable income of affected filers, as in the elasticity-of-taxable-income literature. Some of it is timing (shifting income between years), which flatters the first years.",
                "Filer counts are held at 2024 levels; incomes per filer grow with nominal GDP. Top incomes are more volatile than GDP.",
            ],
            benchmark="pit_top_rate_2016" if top else ("pit_lowest_rate_cut_2025" if bracket == 0 else ""),
            sources=self._common_sources() + [nat.attrs["source"], qc.attrs["source"]],
        )
        return self._debt_service(score)

    # --- corporate income tax ---

    def cit_rate(self, new_rate, kind="general"):
        """Change the federal general (15%) or small business (9%) corporate rate."""
        c = self.a["cit"]
        old_rate = c[f"{kind}_rate"] if kind == "general" else c["small_business_rate"]
        ratio = c[f"{'general' if kind == 'general' else 'small'}_base_per_revenue_dollar"]
        prov = c["provincial_general_rate" if kind == "general" else "provincial_small_rate"]["value"]
        e = c["base_elasticity"]
        dr = new_rate - old_rate
        base0 = c["revenue"]["value"] * ratio["value"]

        static, prov_out = [], []
        cases = {k: [] for k in CASES}
        for year in self.years:
            base = base0 * self.growth(year, c["data_year"])
            s = dr * base
            t0, t1 = old_rate + prov, new_rate + prov
            for k in CASES:
                d_base = base * (((1 - t1) / (1 - t0)) ** e[k] - 1)
                cases[k].append(s + d_base * new_rate)
                if k == "central":
                    prov_out.append(d_base * prov)
            static.append(s)

        name = "general corporate" if kind == "general" else "small business"
        score = Score(
            title=f"Federal {name} rate: {old_rate:.1%} to {new_rate:.1%}",
            measure=f"cit_rate kind={kind} new_rate={new_rate}",
            years=self.years, static=np.array(static), provincial=np.array(prov_out),
            **{k: np.array(v) for k, v in cases.items()},
            assumptions=[
                ("Federal corporate revenue, FY 2024-25", f"${c['revenue']['value'] / 1e9:.1f}B", c["revenue"]["source"]),
                ("Base per dollar of revenue", ratio["value"], ratio["source"]),
                ("Elasticity of corporate taxable income", f"{e['low']} / {e['central']} / {e['high']}", e["source"]),
                ("Provincial rate", prov, "Approximate weighted average"),
                ("Nominal GDP growth", self.a["macro"]["nominal_gdp_growth"]["value"], self.a["macro"]["nominal_gdp_growth"]["source"]),
            ],
            caveats=[
                "The split of the corporate base between the general and small business rates comes from 2019, the last year StatCan published it. The mix may have shifted since.",
                "FY 2024-25 corporate revenue was a record. Corporate profits are cyclical, and projecting from a peak overstates the base in a downturn.",
                "Public Accounts revenue includes reassessments of prior years, so it is not a clean measure of one year's liability.",
                "No investment, wage or growth response is included (Tier 3). Rate cuts are the case where those effects are argued to matter most.",
            ],
            benchmark="cit_ready_reckoner_2014",
            sources=self._common_sources(),
        )
        return self._debt_service(score)

    # --- GST ---

    def gst_rate(self, new_rate):
        """Change the federal GST rate (5%). HST provinces' federal portion moves with it."""
        g_ = self.a["gst"]
        old_rate = g_["rate"]
        dr = new_rate - old_rate
        gross = g_["net_revenue"]["value"] + g_["gst_credit"]["value"]
        base0 = gross / old_rate
        e = g_["base_elasticity"]
        combined = g_["combined_sales_tax_rate"]["value"]

        static, prov_out = [], []
        cases = {k: [] for k in CASES}
        for year in self.years:
            base = base0 * self.growth(year, g_["data_year"])
            s = dr * base
            p0, p1 = 1 + combined, 1 + combined + dr
            for k in CASES:
                d_base = base * ((p0 / p1) ** e[k] - 1)
                cases[k].append(s + d_base * new_rate)
                if k == "central":
                    prov_out.append(d_base * (combined - old_rate))
            static.append(s)

        score = Score(
            title=f"GST rate: {old_rate:.0%} to {new_rate:.1%}",
            measure=f"gst_rate new_rate={new_rate}",
            years=self.years, static=np.array(static), provincial=np.array(prov_out),
            **{k: np.array(v) for k, v in cases.items()},
            assumptions=[
                ("GST revenue, FY 2024-25 (net)", f"${g_['net_revenue']['value'] / 1e9:.1f}B", g_["net_revenue"]["source"]),
                ("GST credit added back", f"${g_['gst_credit']['value'] / 1e9:.1f}B", g_["gst_credit"]["source"]),
                ("Base elasticity", f"{e['low']} / {e['central']} / {e['high']}", e["source"]),
                ("Nominal GDP growth", self.a["macro"]["nominal_gdp_growth"]["value"], self.a["macro"]["nominal_gdp_growth"]["source"]),
            ],
            caveats=[
                "FY 2024-25 GST revenue was reduced by the temporary GST/HST holiday (Dec 2024 to Feb 2025), so the base is understated slightly.",
                "A GST change moves the CPI. Indexed spending (OAS, CCB, the GST credit itself) and indexed brackets would shift with it; that feedback is not included.",
                "The behavioural elasticity is illustrative; there is little Canadian evidence.",
                "Government remissions and rebates are assumed to scale with the rate.",
            ],
            benchmark="gst_ready_reckoner_2014",
            sources=self._common_sources(),
        )
        return self._debt_service(score)

    # --- capital gains ---

    def capital_gains_inclusion(self, new_inclusion):
        """Change the inclusion rate for individuals' capital gains (currently 50%)."""
        cg = self.a["capital_gains"]
        p = self.a["pit"]
        old = cg["inclusion_rate"]
        e = cg["realization_elasticity"]
        prov = cg["provincial_rate_on_gains"]["value"]
        abatement = p["quebec_abatement"]["value"]

        # Realised gains by income range, net of the lifetime exemption and past
        # losses, as a share of GDP, averaged over several years to damp spikes.
        shares, srcs = [], []
        for y in cg["data_years"]:
            t = sources.cra_table2(y, "ac", refresh=self.refresh)
            net = (t["taxable_capital_gains"] - t["capital_gains_deduction"] - t["net_capital_losses"]).clip(lower=0)
            shares.append(net.to_numpy() / old / (self.gdp(y) * 1e6))
            srcs.append(t.attrs["source"])
        share = np.mean(shares, axis=0)
        latest = sources.cra_table2(cg["data_years"][-1], "ac", refresh=self.refresh)
        qc = sources.cra_table2(cg["data_years"][-1], "qc", refresh=self.refresh)
        qc_share = qc["taxable_capital_gains"].sum() / latest["taxable_capital_gains"].sum()
        mean_ti = (latest["taxable_income"] / latest["n_taxable_income"]).to_numpy()
        rates = p["brackets_2026"]["rates"]

        static, prov_out = [], []
        cases = {k: [] for k in CASES}
        for year in self.years:
            gains = share * self.gdp(year) * 1e6
            g = self.growth(year, cg["data_years"][-1])
            th = self.thresholds(year)
            mtr = np.array([rates[np.searchsorted(th, m * g, side="right") - 1] for m in mean_ti])
            fed_factor = 1 - abatement * qc_share
            s = ((new_inclusion - old) * gains * mtr).sum() * fed_factor
            for k in CASES:
                # Realisations respond to the effective tax rate on gains.
                ratio = (new_inclusion / old) ** (-e[k])
                realised = gains * ratio
                total = (new_inclusion * realised * mtr - old * gains * mtr).sum() * fed_factor
                cases[k].append(total)
                if k == "central":
                    prov_out.append(prov * (new_inclusion * realised - old * gains).sum())
            static.append(s)

        score = Score(
            title=f"Capital gains inclusion rate (individuals): {old:.0%} to {new_inclusion:.1%}",
            measure=f"capital_gains_inclusion new_inclusion={new_inclusion}",
            years=self.years, static=np.array(static), provincial=np.array(prov_out),
            **{k: np.array(v) for k, v in cases.items()},
            assumptions=[
                ("Realised gains", f"CRA Table 2, average of {cg['data_years'][0]}-{cg['data_years'][-1]} as a share of GDP",
                 "Net of the capital gains deduction and prior-year losses"),
                ("Marginal federal rate", "Assigned by each income range's average taxable income", "2026 brackets, CPI-indexed"),
                ("Realisation elasticity", f"{e['low']} / {e['central']} / {e['high']}", e["source"]),
                ("Provincial rate on gains", prov, cg["provincial_rate_on_gains"]["source"]),
            ],
            caveats=[
                "Individuals only. Corporations and trusts realise a large share of gains and are not modelled.",
                "2024 realisations were inflated by sales ahead of the proposed June 2024 increase; averaging three years only partly removes that.",
                "Every filer in an income range is assigned that range's marginal rate; gains push some filers into higher brackets.",
                "Announcement effects (selling before a hike, waiting for a cut) can swing the first year by more than the whole static estimate.",
                "The provincial line here includes the provinces' static change, because provinces use the federal inclusion rate.",
            ],
            benchmark="capital_gains_2024",
            sources=self._common_sources() + srcs + [qc.attrs["source"]],
        )
        return self._debt_service(score)
