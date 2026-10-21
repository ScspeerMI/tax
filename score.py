"""Score a Canadian federal tax change and write a memo.

Examples:
    python score.py pit --bracket top --rate 0.32
    python score.py pit --bracket lowest --rate 0.13
    python score.py cit --rate 0.14
    python score.py cit --kind small --rate 0.08
    python score.py gst --rate 0.04
    python score.py capgains --inclusion 0.6667

Change any assumption for one run with --set, e.g.
    python score.py pit --bracket top --rate 0.32 --set macro.nominal_gdp_growth.value=0.03
"""

import argparse

from workbench import report
from workbench.model import Workbench

BRACKETS = {"lowest": 0, "second": 1, "third": 2, "fourth": 3, "top": 4}


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="override an assumption in assumptions.yaml for this run")
    common.add_argument("--refresh", action="store_true", help="re-download source data")
    common.add_argument("--out", help="output folder (default: outputs/<date>-<title>)")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="measure", required=True)

    p = sub.add_parser("pit", parents=[common], help="personal income tax bracket rate")
    p.add_argument("--bracket", choices=BRACKETS, required=True)
    p.add_argument("--rate", type=float, required=True, help="new rate, e.g. 0.32")

    c = sub.add_parser("cit", parents=[common], help="corporate income tax rate")
    c.add_argument("--kind", choices=["general", "small"], default="general")
    c.add_argument("--rate", type=float, required=True)

    g = sub.add_parser("gst", parents=[common], help="GST rate")
    g.add_argument("--rate", type=float, required=True)

    k = sub.add_parser("capgains", parents=[common], help="capital gains inclusion rate (individuals)")
    k.add_argument("--inclusion", type=float, required=True, help="new inclusion rate, e.g. 0.6667")

    args = parser.parse_args()
    wb = Workbench(overrides=args.set, refresh=args.refresh)
    if args.measure == "pit":
        score = wb.pit_rate(BRACKETS[args.bracket], args.rate)
    elif args.measure == "cit":
        score = wb.cit_rate(args.rate, kind=args.kind)
    elif args.measure == "gst":
        score = wb.gst_rate(args.rate)
    else:
        score = wb.capital_gains_inclusion(args.inclusion)

    if args.set:
        score.assumptions.append(("Overrides for this run", "; ".join(args.set), "Command line"))
    out = report.write(score, wb.a.get("benchmarks", {}), args.out)
    lo, hi = sorted([score.low.sum(), score.high.sum()])
    print(score.title)
    m = report.money
    print(f"  {score.years[0]}-{score.years[-1]} change in federal revenue: central {m(score.central.sum())} "
          f"(range {m(lo)} to {m(hi)}); static {m(score.static.sum())}")
    print(f"  Memo: {out / 'memo.md'}")


if __name__ == "__main__":
    main()
