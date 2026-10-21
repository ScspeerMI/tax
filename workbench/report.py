"""Turn a Score into a chart, a CSV and a one-page score memo."""

import re
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "outputs"

# House chart style: one quiet surface, recessive axes, two fixed series colours.
SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e4e3df"
CENTRAL = "#2a78d6"  # behavioural, central case
STATIC = "#eb6834"   # static

METHODS = {
    "pit_rate": (
        "The rate change is applied to the slice of taxable income inside the bracket, using CRA's "
        "income distribution grown with nominal GDP, with bracket thresholds indexed to CPI. Quebec "
        "residents' share is reduced by the 16.5% abatement. For the lowest bracket, the change in the "
        "value of non-refundable credits (which are valued at the lowest rate) is netted off. "
        "Behaviour: filers whose top dollar falls in the bracket change their taxable income by the "
        "elasticity of taxable income times the percentage change in their combined federal-provincial "
        "net-of-tax rate."
    ),
    "cit_rate": (
        "The corporate base taxed at this rate is federal corporate revenue times a base-per-dollar ratio "
        "from StatCan's corporate taxation statistics, grown with nominal GDP. Behaviour: the base responds "
        "to the change in the combined federal-provincial net-of-tax rate."
    ),
    "gst_rate": (
        "The GST base is gross GST revenue (net revenue plus the GST credit) divided by the 5% rate, grown "
        "with nominal GDP. Behaviour: the taxable consumption base responds to the change in the "
        "tax-inclusive price."
    ),
    "capital_gains_inclusion": (
        "Individuals' realised capital gains, by income range, net of the lifetime exemption and prior-year "
        "losses, are taken as a share of GDP averaged over three years. Each range is taxed at the federal "
        "marginal rate for its average taxable income. Behaviour: realisations respond to the change in the "
        "effective tax rate on gains."
    ),
}


def bn(x):
    return f"{x / 1e9:,.1f}"


def money(x):
    """-45.5e9 -> '-$45.5B'."""
    return f"{'-' if x < 0 else ''}${abs(x) / 1e9:,.1f}B"


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def chart(score, path):
    years = score.years
    x = range(len(years))
    central = score.central / 1e9
    lo = [min(a, b) / 1e9 for a, b in zip(score.low, score.high)]
    hi = [max(a, b) / 1e9 for a, b in zip(score.low, score.high)]

    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.bar(x, central, width=0.55, color=CENTRAL, label="With behavioural response (central)", zorder=2)
    ax.vlines(x, lo, hi, color=TEXT_2, linewidth=1.5, zorder=3, label="Range across elasticities")
    ax.scatter(x, score.static / 1e9, s=40, color=STATIC, edgecolor=SURFACE, linewidth=1.5, zorder=4, label="Static")
    ax.axhline(0, color=TEXT_2, linewidth=1)

    ax.set_xticks(list(x), [str(y) for y in years])
    ax.set_ylabel("$ billions", color=TEXT_2)
    ax.tick_params(colors=TEXT_2, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)

    # Direct-label the first and last central bars.
    for i in (0, len(years) - 1):
        v = central[i]
        ax.annotate(f"{v:,.1f}", (i, v), xytext=(0, 3 if v >= 0 else -3), textcoords="offset points",
                    ha="center", va="bottom" if v >= 0 else "top", fontsize=8, color=TEXT, zorder=5,
                    bbox=dict(boxstyle="round,pad=0.2", facecolor=SURFACE, edgecolor="none"))

    fig.suptitle(score.title, x=0.06, ha="left", fontsize=12, color=TEXT, fontweight="bold")
    ax.set_title("Change in federal revenue by tax year (negative = cost)", loc="left", fontsize=9, color=TEXT_2)
    handles, labels = ax.get_legend_handles_labels()
    order = [labels.index(l) for l in ("With behavioural response (central)", "Range across elasticities", "Static")]
    ax.legend([handles[i] for i in order], [labels[i] for i in order], loc="best", frameon=False,
              fontsize=8, labelcolor=TEXT_2)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def table(score):
    df = pd.DataFrame({
        "year": score.years,
        "static": score.static,
        "low_elasticity": score.low,
        "central": score.central,
        "high_elasticity": score.high,
        "provincial_spillover": score.provincial,
        "debt_service": score.debt_service,
    })
    return df


def write(score, benchmarks, out_dir=None):
    """Write memo.md, chart.png and estimates.csv; return the output folder."""
    out = Path(out_dir) if out_dir else OUTPUTS / f"{date.today().isoformat()}-{slug(score.title)}"
    out.mkdir(parents=True, exist_ok=True)
    chart(score, out / "chart.png")
    df = table(score)
    df.to_csv(out / "estimates.csv", index=False)

    y0, y1 = score.years[0], score.years[-1]
    lo, hi = sorted([score.low.sum(), score.high.sum()])
    kind = score.measure.split()[0]
    lines = [
        f"# {score.title}",
        "",
        f"*Score memo · Fiscal Workbench (static and behavioural estimates) · {date.today():%B %d, %Y}*",
        "",
        "## Bottom line",
        "",
        f"- **Change in federal revenue, {y0}–{y1}: {money(score.central.sum())}** in the central case, "
        f"with a range of {money(lo)} to {money(hi)} across plausible behavioural responses. Negative numbers are a cost.",
        f"- Static estimate (no behavioural change): {money(score.static.sum())}. "
        f"First full year ({y0}): {money(score.central[0])} central, {money(score.static[0])} static.",
        f"- Including extra interest on the debt (at the current 10-year bond yield of {score.interest_rate:.2%}): "
        f"{money(score.central.sum() + score.debt_service.sum())}.",
        f"- Knock-on change in provincial revenue (central case): {money(score.provincial.sum())} over the same period. "
        "This is not a federal cost, but provinces would feel it.",
        "",
        "## Annual estimates ($ billions)",
        "",
        "| Year | Static | Low elasticity | Central | High elasticity | Provincial |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for _, r in df.iterrows():
        lines.append(f"| {int(r.year)} | {bn(r.static)} | {bn(r.low_elasticity)} | {bn(r.central)} | "
                     f"{bn(r.high_elasticity)} | {bn(r.provincial_spillover)} |")
    lines.append(f"| **Total** | **{bn(score.static.sum())}** | **{bn(score.low.sum())}** | "
                 f"**{bn(score.central.sum())}** | **{bn(score.high.sum())}** | **{bn(score.provincial.sum())}** |")
    lines += [
        "",
        "![Chart](chart.png)",
        "",
        "## How this was estimated",
        "",
        METHODS.get(kind, ""),
        "",
        "There is no macroeconomic feedback: changes to growth, investment or wages are not included.",
        "",
        "## Assumptions",
        "",
        "| Assumption | Value | Source |",
        "|---|---|---|",
    ]
    for label, value, source in score.assumptions:
        lines.append(f"| {label} | {value} | {' '.join(str(source).split())} |")
    if score.benchmark and score.benchmark in benchmarks:
        lines += ["", "## How this compares", "", " ".join(benchmarks[score.benchmark]["text"].split())]
    lines += [
        "",
        "## Red team: reasons this estimate could be wrong",
        "",
    ]
    lines += [f"- {c}" for c in score.caveats]
    lines += [
        "- Nominal GDP growth after the last published year is an assumption. A recession would shrink every base here.",
        "- The behavioural range reflects the literature, not this proposal. Design details (anti-avoidance rules, "
        "transition, announcement timing) can move the real response outside it.",
        "- Tax years are reported, not fiscal years; government budget tables use fiscal years and include timing lags.",
        "- This is a back-of-the-envelope estimate built from published aggregates, not a microsimulation. Treat it as a "
        "check on official estimates, not a replacement for them.",
        "",
        "## Sources",
        "",
    ]
    seen = set()
    for s in score.sources:
        key = s["url"]
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {s['source']}. <{s['url']}> (retrieved {s['retrieved']}). {s.get('notes', '')}".rstrip())
    lines.append("- Parameters and literature sources: `assumptions.yaml` in this workbench.")
    (out / "memo.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
