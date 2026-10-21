// Filer-level tax engine for the browser.
//
// A line-for-line port of workbench/explorer.py. build_explorer.py runs both
// on the same test reforms and fails if they differ by more than $1M a year,
// so change the two together.

export const CASES = ["low", "central", "high"];

function bpaAmount(ti, max, min, start, end) {
  const frac = Math.min(Math.max((ti - start) / (end - start), 0), 1);
  return max - (max - Math.min(min, max)) * frac;
}

function basicTax(ti, thresholds, rates) {
  let tax = 0;
  for (let k = 0; k < rates.length; k++) {
    const lo = thresholds[k];
    const hi = k + 1 < thresholds.length ? thresholds[k + 1] : Infinity;
    tax += rates[k] * Math.max(Math.min(ti, hi) - lo, 0);
  }
  return tax;
}

function indexLaw(law, cpi, phase) {
  return {
    thresholds: law.thresholds.map((t) => t * cpi),
    rates: law.rates,
    bpa_max: law.bpa_max * cpi,
    bpa_min: law.bpa_min * cpi,
    phase_start: phase[0] * cpi,
    phase_end: phase[1] * cpi,
  };
}

// Federal tax after the Quebec abatement, for one filer in record i.
function federalTax(ti, rec, i, law, growth, creditIndex, abatement) {
  const bpa = bpaAmount(ti, law.bpa_max, law.bpa_min, law.phase_start, law.phase_end);
  const credits = law.rates[0] * (bpa + rec.other_credits[i] * creditIndex);
  const pre = basicTax(ti, law.thresholds, law.rates) - credits - rec.fixed_credit[i] * growth;
  return Math.max(pre, 0) * (1 - abatement * rec.qc[i]);
}

function bracketIndex(thresholds, ti) {
  let k = 0;
  while (k + 1 < thresholds.length && ti >= thresholds[k + 1]) k++;
  return k;
}

export function score(reform, params, rec, groups) {
  const base = params.current_law;
  const phase = [base.thresholds[3], base.thresholds[4]];
  const n = rec.ti.length;
  const out = { years: params.years, static: [], low: [], central: [], high: [], provincial: [] };

  params.years.forEach((year, y) => {
    const g = params.growth[y];
    const ci = params.credit_index[y];
    const law0 = indexLaw(base, params.cpi_index[y], phase);
    const law1 = indexLaw(reform, params.cpi_index[y], phase);
    const sums = { static: 0, low: 0, central: 0, high: 0, provincial: 0 };
    const t0s = new Float64Array(n);
    const t1s = new Float64Array(n);

    for (let i = 0; i < n; i++) {
      const ti = rec.ti[i] * g;
      const w = rec.w[i];
      const t0 = federalTax(ti, rec, i, law0, g, ci, params.abatement);
      const t1 = federalTax(ti, rec, i, law1, g, ci, params.abatement);
      t0s[i] = t0;
      t1s[i] = t1;
      sums.static += w * (t1 - t0);

      // Behaviour: response to the change in the combined marginal rate.
      const h = 100;
      const m0 = (federalTax(ti + h, rec, i, law0, g, ci, params.abatement) - t0) / h;
      const m1 = (federalTax(ti + h, rec, i, law1, g, ci, params.abatement) - t1) / h;
      const prov = params.provincial_rates[bracketIndex(law0.thresholds, ti)];
      const ratio = (1 - (m1 + prov)) / (1 - (m0 + prov));
      const top = ti > law0.thresholds[law0.thresholds.length - 1];
      for (const c of CASES) {
        const eti = top ? params.eti_top[c] : params.eti_lower[c];
        const dTi = ti * (Math.pow(ratio, eti) - 1);
        const t1b = federalTax(ti + dTi, rec, i, law1, g, ci, params.abatement);
        sums[c] += w * (t1b - t0);
        if (c === "central") sums.provincial += w * dTi * prov;
      }
    }
    for (const k of Object.keys(sums)) out[k].push(sums[k]);
    if (y === 0) out.distribution = distribution(t0s, t1s, rec, g, groups);
  });

  let cum = 0;
  out.debt_service = out.central.map((c) => {
    cum += c;
    return (cum - c / 2) * params.interest_rate;
  });
  return out;
}

// First-year static effects by income group.
function distribution(t0, t1, rec, growth, groups) {
  let total = 0, allCuts = 0, allIncreases = 0;
  for (let i = 0; i < t0.length; i++) {
    const wd = rec.w[i] * (t1[i] - t0[i]);
    total += wd;
    if (wd < 0) allCuts += wd;
    else allIncreases += wd;
  }
  return groups.map(({ name, classes }) => {
    const members = new Set(classes);
    let filers = 0, less = 0, more = 0, change = 0, income = 0, cuts = 0, increases = 0;
    for (let i = 0; i < t0.length; i++) {
      if (!members.has(rec.cls[i])) continue;
      const w = rec.w[i];
      const d = t1[i] - t0[i];
      filers += w;
      if (d <= -1) less += w;
      if (d >= 1) more += w;
      change += w * d;
      if (d < 0) cuts += w * d;
      else increases += w * d;
      income += w * rec.ti[i] * growth;
    }
    return {
      group: name,
      filers,
      pay_less: less,
      pay_more: more,
      income,
      avg_change: change / filers,
      avg_change_affected: less + more ? change / (less + more) : 0,
      pct_income: change / income,
      share: total ? change / total : 0,
      share_of_cuts: allCuts ? cuts / allCuts : 0,
      share_of_increases: allIncreases ? increases / allIncreases : 0,
    };
  });
}
