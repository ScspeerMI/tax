# Fiscal Workbench (Canada) — Phase 1

Back-of-the-envelope revenue estimates for Canadian federal tax changes, built from
public data, with every assumption written down and every result given as a range.

The easiest way to use it is to ask Claude in plain English, from this folder:

> "What would cutting the top federal rate from 33% to 30% cost over ten years?"
> "Score a one-point GST cut, but assume 3% nominal growth."
> "Why is the provincial number positive?"

Claude runs the model, writes a memo, and explains what drives the result.

## What it covers

| Measure | Command |
|---|---|
| Any personal income tax bracket rate | `python score.py pit --bracket top --rate 0.32` |
| General or small business corporate rate | `python score.py cit --rate 0.14` / `--kind small --rate 0.08` |
| GST rate | `python score.py gst --rate 0.04` |
| Capital gains inclusion rate (individuals) | `python score.py capgains --inclusion 0.6667` |

Each run writes a folder under `outputs/` containing:

- `memo.md`: bottom line, annual table, chart, method, assumptions, a comparison with
  published estimates, a red-team section on what could make the estimate wrong, and
  dated sources.
- `chart.png`: the chart, sized for a report or slide.
- `estimates.csv`: the numbers, for Excel.

To change an assumption for one run, add `--set`, for example
`--set macro.nominal_gdp_growth.value=0.03`. To change it permanently, edit `assumptions.yaml`.

## How it estimates

- **Static (Tier 1):** the rate change times the base. This is the "nobody changes
  behaviour" number.
- **Behavioural (Tier 2):** the base responds to the tax change, using elasticities
  from the literature. Each memo gives low, central and high cases.
- **Debt service:** the extra interest if the cost is borrowed, at the current
  10-year Government of Canada bond yield.
- **Provincial spillover:** most provinces tax the federal definition of income, so
  federal changes move provincial revenue too. This is reported separately.
- **Not included:** macroeconomic feedback (growth, investment, wages). That is Tier 3.

## Data sources (downloaded automatically, cached in `data/raw/`)

- Canada Revenue Agency, Individual Income Tax Return Statistics, Table 2: filers
  and income by income range (2022–2024 tax years).
- Statistics Canada, Table 36-10-0104: nominal GDP.
- Bank of Canada Valet API: 10-year bond yield.
- Public Accounts of Canada 2025: corporate tax and GST revenue (recorded in
  `assumptions.yaml`, because the Public Accounts have no data feed).

Each cached file has a `.meta.json` file beside it, recording where it came from and when
it was downloaded. To refresh the data, run with `--refresh`.

## The web explorer (`docs/`)

An interactive page for personal income tax reforms: edit brackets, rates and the
basic personal amount, and see revenue, filers affected and the average tax change
by income group. It is intended for publication at seanspeer.com/tax and has not been published yet.

- Preview it locally: start the `tax-explorer` server (Claude can do this), or run
  `python -m http.server 8767 --directory docs` and open http://localhost:8767.
- After changing `assumptions.yaml` or refreshing data, run
  `.venv\Scripts\python build_explorer.py`. It rebuilds `docs/data.json` and checks
  that the browser engine (`docs/engine.js`) matches the Python engine on seven test
  reforms. Node.js is required for that check.

The explorer and `score.py pit` use the same filer-level engine (`workbench/explorer.py`).
It represents CRA's 19 income ranges as about 500 representative filer groups,
calibrated to CRA's 2024 net federal tax by income range.

## Calibration check

A one-point cut to the lowest rate (14% to 13%) comes out at about **−$5.3B** in 2027
(static). The PBO's June 2025 costing of the actual 15%-to-14% cut was about **$6B a year**
net in 2026–30. Both net off the lower value of non-refundable credits. Part of the gap is
that the model leaves out about $2.5B of tax CRA reports from filers under $40,000.

## Setup (one time)

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Then run commands with `.venv\Scripts\python score.py ...`.

## Next phases

- **Phase 2:** sensitivity (tornado) charts, province-by-province rates, a library
  of published PBO and Finance estimates to benchmark against, and debt-to-GDP paths.
- **Phase 3:** macro feedback scenarios, explorer modules for corporate tax, GST and
  capital gains, and a synthetic filer file for winners and losers within income ranges.
