"""An approximate distribution of taxable income, built from CRA Table 2.

CRA publishes filer counts and dollar totals by income range, not individual
records. To ask "how much taxable income lies above $258,482?" we assume:

- within each closed range, filers' taxable income is spread evenly over the
  range (rescaled so the range's average matches CRA's reported average);
- above $250,000, taxable income follows a Pareto distribution whose shape
  is set so the average matches CRA's reported average for that group.

This reproduces CRA's totals by construction. It is coarsest near range
boundaries and at the very top, where the Pareto shape does most of the work.
"""

import numpy as np


class IncomeDistribution:
    def __init__(self, table):
        self.table = table
        n = table["n_taxable_income"].to_numpy()
        ti = table["taxable_income"].to_numpy()
        lo = table["lo"].to_numpy(dtype=float)
        hi = table["hi"].to_numpy(dtype=float)
        mean_ti = np.divide(ti, n, out=np.zeros_like(ti), where=n > 0)

        # Closed ranges: stretch [lo, hi] so its midpoint equals the reported mean.
        mid = (lo[:-1] + hi[:-1]) / 2
        scale = mean_ti[:-1] / mid
        self.lo, self.hi, self.n = lo[:-1] * scale, hi[:-1] * scale, n[:-1]

        # Top range: Pareto shape from mean total income, location from mean taxable income.
        top = table.iloc[-1]
        mean_total = top["total_income"] / top["n_total_income"]
        self.alpha = mean_total / (mean_total - top["lo"])
        self.top_n = n[-1]
        self.top_lo = mean_ti[-1] * (self.alpha - 1) / self.alpha

    def count_above(self, t, growth=1.0):
        """Filers with taxable income above t, after incomes grow by `growth`."""
        t = t / growth
        closed = self.n * np.clip((self.hi - t) / (self.hi - self.lo), 0, 1)
        top = self.top_n if t <= self.top_lo else self.top_n * (self.top_lo / t) ** self.alpha
        return closed.sum() + top

    def income_of_filers_above(self, t, growth=1.0):
        """Total taxable income of filers whose taxable income exceeds t."""
        t = t / growth
        start = np.clip(t, self.lo, self.hi)
        closed = self.n / (self.hi - self.lo) * (self.hi ** 2 - start ** 2) / 2
        a, lo = self.alpha, self.top_lo
        cut = max(t, lo)
        top = self.top_n * lo ** a * a / (a - 1) * cut ** (1 - a)
        return (closed.sum() + top) * growth

    def income_above(self, t, growth=1.0):
        """Taxable income lying above t: the base a rate on income over t applies to."""
        return self.income_of_filers_above(t, growth) - t * self.count_above(t, growth)

    def income_between(self, lo, hi, growth=1.0):
        """Taxable income lying in the bracket [lo, hi)."""
        above_hi = self.income_above(hi, growth) if np.isfinite(hi) else 0.0
        return self.income_above(lo, growth) - above_hi

    def income_of_filers_between(self, lo, hi, growth=1.0):
        """Total taxable income of filers whose top dollar falls in [lo, hi)."""
        above_hi = self.income_of_filers_above(hi, growth) if np.isfinite(hi) else 0.0
        return self.income_of_filers_above(lo, growth) - above_hi
