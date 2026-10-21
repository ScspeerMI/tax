// Page logic: reads the reform from the form, scores it with engine.js and
// draws the results. All numbers come from engine.js; nothing here models tax.

import { score } from "./engine.js";

const $ = (id) => document.getElementById(id);
const SVG = "http://www.w3.org/2000/svg";
const MINUS = "−";

let data, currentLaw, presets;
let state = null;

// --- formatting ---

function money(x) {
  const a = Math.abs(x);
  const sign = x < 0 ? MINUS : "";
  if (a >= 9.95e8) return `${sign}$${(a / 1e9).toFixed(1)}B`;
  if (a >= 5e5) return `${sign}$${Math.round(a / 1e6).toLocaleString("en-CA")}M`;
  return "$0";
}
const absMoney = (x) => money(Math.abs(x));
// Revenue in words, so the sign never needs a legend: "costs $3.6B" / "raises $1.2B".
const verbMoney = (x) => (Math.abs(x) < 5e5 ? "no change" : `${x < 0 ? "costs" : "raises"} ${absMoney(x)}`);
const cap = (s) => s[0].toUpperCase() + s.slice(1);

function perFiler(x) {
  const r = Math.round(x);
  if (r === 0) return "$0";
  return `${r < 0 ? MINUS : "+"}$${Math.abs(r).toLocaleString("en-CA")}`;
}
function count(n) {
  if (n >= 995000) return `${(n / 1e6).toFixed(1)} million`;
  if (n < 500) return "0";
  const digits = Math.max(0, Math.floor(Math.log10(n)) - 1);
  const step = 10 ** digits;
  return (Math.round(n / step) * step).toLocaleString("en-CA");
}
function pct(x, digits = 1) {
  const v = (x * 100).toFixed(digits);
  return `${x < 0 ? MINUS : ""}${v.replace("-", "")}%`;
}
const dollars = (n) => `$${Math.round(n).toLocaleString("en-CA")}`;
const sum = (a) => a.reduce((x, y) => x + y, 0);

// --- presets and URL state ---

function buildPresets(cl) {
  const withRate = (i, r) => ({ ...cl, rates: cl.rates.map((v, k) => (k === i ? r : v)) });
  return [
    ["current", "Current law (2026)", cl],
    ["low13", "Cut the lowest rate to 13%", withRate(0, 0.13)],
    ["low15", "Restore the 15% lowest rate", withRate(0, 0.15)],
    ["top29", "Top rate back to 29%", withRate(cl.rates.length - 1, 0.29)],
    ["new36", "New 36% bracket above $500,000", { ...cl, thresholds: [...cl.thresholds, 500000], rates: [...cl.rates, 0.36] }],
    ["bpa20", "Basic personal amount of $20,000", { ...cl, bpa_max: 20000 }],
    ["flat20", "Flat 20% tax", { ...cl, thresholds: [0], rates: [0.2] }],
  ];
}

// The link records only what differs from current law, so it stays short:
//   (nothing)               current law
//   #top29                  a preset
//   #r=14,20.5,26,29,30     custom rates (t= thresholds and b= basic amount only if changed)
//   ...&large               behavioural case, when not central
// Older links that spell everything out (t=0,...&r=...&b=...&c=high) still open.
const CASE_IN_URL = { low: "small", high: "large" };

function fromHash() {
  const tokens = location.hash.slice(1).split("&").filter(Boolean);
  if (!tokens.length) return null;
  let s = { ...currentLaw, case: "central" };
  for (const tok of tokens) {
    const [key, value = ""] = tok.split("=");
    const preset = presets.find(([id]) => id === key);
    const nums = value.split(",").map(Number);
    if (preset && !value) s = { ...preset[2], case: s.case };
    else if (key === "small" || key === "large") s.case = key === "small" ? "low" : "high";
    else if (key === "c" && ["low", "central", "high"].includes(value)) s.case = value;
    else if (key === "t") s.thresholds = nums[0] === 0 ? nums : [0, ...nums];
    else if (key === "r") s.rates = nums.map((v) => v / 100);
    else if (key === "b") s.bpa_max = nums[0];
    else return null;
  }
  const ok = s.thresholds.length === s.rates.length && !s.thresholds.some(isNaN) && !s.rates.some(isNaN) && s.bpa_max >= 0;
  return ok ? s : null;
}

function toHash(s) {
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const parts = [];
  const id = matchPreset();
  if (id !== "custom") {
    if (id !== "current") parts.push(id);
  } else {
    const rates = s.rates.map((v) => +(v * 100).toFixed(3));
    if (!same(s.thresholds, currentLaw.thresholds)) parts.push(`t=${s.thresholds.slice(1).join(",")}`);
    if (!same(rates, currentLaw.rates.map((v) => +(v * 100).toFixed(3))) || !same(s.thresholds, currentLaw.thresholds)) {
      parts.push(`r=${rates.join(",")}`);
    }
    if (s.bpa_max !== currentLaw.bpa_max) parts.push(`b=${s.bpa_max}`);
  }
  if (CASE_IN_URL[s.case]) parts.push(CASE_IN_URL[s.case]);
  return parts.join("&");
}

// --- the form ---

function renderBrackets() {
  const rows = $("bracket-rows");
  rows.innerHTML = "";
  state.thresholds.forEach((t, i) => {
    const row = document.createElement("div");
    row.className = "bracket-row";
    const from = i === 0
      ? `<span class="fixed-zero">0</span>`
      : `<span class="input-prefix"><span>$</span><input type="number" inputmode="numeric" min="0" step="1000" value="${t}" data-kind="t" data-i="${i}" aria-label="Bracket ${i + 1} starts at"></span>`;
    row.innerHTML = `${from}
      <span class="input-suffix"><input type="number" inputmode="decimal" min="0" max="100" step="0.5" value="${+(state.rates[i] * 100).toFixed(3)}" data-kind="r" data-i="${i}" aria-label="Bracket ${i + 1} rate"><span>%</span></span>
      ${i > 0 ? `<button type="button" class="remove" data-i="${i}" aria-label="Remove bracket ${i + 1}">×</button>` : "<span></span>"}`;
    rows.appendChild(row);
  });
}

function setState(s, { presetId = null } = {}) {
  state = { ...s, thresholds: [...s.thresholds], rates: [...s.rates] };
  renderBrackets();
  $("bpa").value = state.bpa_max;
  document.querySelector(`input[name="case"][value="${state.case}"]`).checked = true;
  $("preset").value = presetId ?? matchPreset();
  update();
}

function matchPreset() {
  for (const [id, , p] of presets) {
    if (JSON.stringify(p.thresholds) === JSON.stringify(state.thresholds)
      && JSON.stringify(p.rates.map((r) => +r.toFixed(5))) === JSON.stringify(state.rates.map((r) => +r.toFixed(5)))
      && p.bpa_max === state.bpa_max) return id;
  }
  return "custom";
}

function validate() {
  const errors = [];
  document.querySelectorAll("#bracket-rows input").forEach((el) => el.removeAttribute("aria-invalid"));
  state.rates.forEach((r, i) => {
    if (!(r >= 0 && r <= 0.99)) {
      errors.push(isNaN(r) ? `Bracket ${i + 1}: enter a rate.` : `Bracket ${i + 1}: the rate must be between 0% and 99%.`);
      document.querySelector(`input[data-kind="r"][data-i="${i}"]`)?.setAttribute("aria-invalid", "true");
    }
  });
  for (let i = 1; i < state.thresholds.length; i++) {
    if (!(state.thresholds[i] > state.thresholds[i - 1])) {
      errors.push(isNaN(state.thresholds[i]) ? `Bracket ${i + 1}: enter where it starts.` : `Bracket ${i + 1} must start above bracket ${i}.`);
      document.querySelector(`input[data-kind="t"][data-i="${i}"]`)?.setAttribute("aria-invalid", "true");
    }
  }
  if (isNaN(state.bpa_max)) errors.push("Enter a basic personal amount.");
  else if (state.bpa_max < 0) errors.push("The basic personal amount can't be negative.");
  return errors;
}

let timer;
function update() {
  clearTimeout(timer);
  timer = setTimeout(run, 80);
}

function run() {
  const errors = validate();
  $("errors").textContent = errors.length ? `${errors.join(" ")} Showing the last valid reform.` : "";
  $("explorer").classList.toggle("stale", errors.length > 0);
  if (errors.length) {
    updateMobileBar("Check the highlighted field", true);
    return;
  }
  const hash = toHash(state);
  history.replaceState(null, "", hash ? `#${hash}` : location.pathname + location.search);
  $("bpa-hint").textContent = state.bpa_max === currentLaw.bpa_max ? "" : `Current law ${dollars(currentLaw.bpa_max)}`;
  const reform = { thresholds: state.thresholds, rates: state.rates, bpa_max: state.bpa_max, bpa_min: currentLaw.bpa_min };
  render(score(reform, data.params, data.records, data.groups));
}

// --- results ---

let lastResult = null;
let resizeTimer;
addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => lastResult && render(lastResult), 150);
});

function render(r) {
  lastResult = r;
  const c = state.case;
  const years = r.years;
  const d = r.distribution;
  const total = sum(r[c]);
  const [lo, hi] = [sum(r.low), sum(r.high)].sort((a, b) => a - b);
  const less = sum(d.map((g) => g.pay_less));
  const more = sum(d.map((g) => g.pay_more));
  const noChange = less + more < 500 && r.static.every((v) => Math.abs(v) < 5e5);

  document.querySelectorAll(".first-year").forEach((el) => (el.textContent = years[0]));
  $("details").hidden = noChange;
  $("secondary").hidden = noChange;
  $("headline-row").hidden = noChange;
  $("caveat").hidden = false;

  if (noChange) {
    $("verb").textContent = "";
    $("ten-year").textContent = $("preset").value === "current" ? "Current law" : "No change";
    $("period").textContent = "";
    $("range-line").textContent = "Pick a preset or change a rate, threshold or the basic personal amount.";
    updateMobileBar("Current law");
    return;
  }

  // The focal point: ten-year change, in words, with its range and the static estimate.
  $("verb").textContent = Math.abs(total) < 5e5 ? "" : cap(total < 0 ? "costs" : "raises");
  $("ten-year").textContent = Math.abs(total) < 5e5 ? "$0" : absMoney(total);
  $("period").textContent = `over ten years, ${years[0]}–${String(years[years.length - 1]).slice(2)}`;
  const sameSign = Math.sign(lo) === Math.sign(hi) && Math.sign(lo) === Math.sign(total);
  const range = sameSign
    ? `Range ${absMoney(Math.abs(lo) < Math.abs(hi) ? lo : hi)} to ${absMoney(Math.abs(lo) < Math.abs(hi) ? hi : lo)}`
    : `Range: ${verbMoney(lo)} to ${verbMoney(hi)}`;
  const st = sum(r.static);
  const staticText = Math.sign(st) === Math.sign(total) ? absMoney(st) : verbMoney(st);
  $("range-line").textContent = `${range} across behavioural responses · Static estimate ${staticText}`;

  $("first-year").innerHTML = `<strong>${cap(verbMoney(r[c][0]))}</strong> in ${years[0]}`;
  $("affected").innerHTML = affectedText(d, less, more);

  drawRevenue(r, c);
  drawDistribution(d);
  fillTable(d, less, more);

  const debt = sum(r.debt_service);
  $("fact-debt").textContent = `With ${total < 0 ? "interest on the added debt" : "interest saved on lower debt"} at the current ${(data.params.interest_rate * 100).toFixed(2)}% ten-year yield: ${verbMoney(total + debt)} over ten years.`;
  const prov = sum(r.provincial);
  $("fact-prov").textContent = Math.abs(prov) < 1e8
    ? "Provincial revenue: no material change."
    : `Provincial revenue ${prov < 0 ? "falls" : "rises"} by ${absMoney(prov)} over ten years, as filers report ${prov < 0 ? "less" : "more"} income.`;

  updateMobileBar(`${cap(verbMoney(total))} over 10 years`);
}

function affectedText(d, less, more) {
  const filers = sum(d.map((g) => g.filers));
  const change = sum(d.map((g) => g.avg_change * g.filers));
  const share = pct((less + more) / filers, 0);
  const when = `in ${data.params.years[0]} (${share} of filers)`;
  if (less >= 500 && more < 500) return `<strong>${count(less)} filers pay less</strong> ${when}, by ${dollars(-change / less)} on average before behavioural response`;
  if (more >= 500 && less < 500) return `<strong>${count(more)} filers pay more</strong> ${when}, by ${dollars(change / more)} on average before behavioural response`;
  return `<strong>${count(less)} pay less, ${count(more)} pay more</strong> ${when}`;
}

function fillTable(d, less, more) {
  const filers = sum(d.map((g) => g.filers));
  const change = sum(d.map((g) => g.avg_change * g.filers));
  const income = sum(d.map((g) => g.income));
  // Columns that would be all zeros are left out.
  const cols = [
    ["Total income", (g) => g.group, "All filers"],
    ["Filers", (g) => count(g.filers), count(filers)],
    ...(less >= 500 ? [["Pay less", (g) => count(g.pay_less), count(less)]] : []),
    ...(more >= 500 ? [["Pay more", (g) => count(g.pay_more), count(more)]] : []),
    ["Avg change per filer", (g) => perFiler(g.avg_change), perFiler(change / filers)],
    ["% of taxable income", (g) => pct(g.pct_income, 2), pct(change / income, 2)],
    ...(less >= 500 ? [["Share of cuts", (g) => (g.share_of_cuts ? pct(g.share_of_cuts, 0) : "–"), "100%"]] : []),
    ...(more >= 500 ? [["Share of increases", (g) => (g.share_of_increases ? pct(g.share_of_increases, 0) : "–"), "100%"]] : []),
  ];
  const t = $("dist-table");
  t.tHead.innerHTML = `<tr>${cols.map(([h]) => `<th scope="col">${h}</th>`).join("")}</tr>`;
  t.tBodies[0].innerHTML = d.map((g) => {
    const zero = g.pay_less + g.pay_more < 500;
    return `<tr${zero ? ' class="zero"' : ""}>${cols.map(([, f]) => `<td>${f(g)}</td>`).join("")}</tr>`;
  }).join("");
  t.tFoot.innerHTML = `<tr>${cols.map(([, , total]) => `<td>${total}</td>`).join("")}</tr>`;
}

// While the form is on screen and the headline number isn't, a bar keeps the result in view (phones).
let headlineVisible = true, formVisible = false, barText = "", barStale = false;
function updateMobileBar(text, stale = false) {
  barText = text;
  barStale = stale;
  const bar = $("mobile-bar");
  bar.classList.toggle("stale", stale);
  bar.innerHTML = `<span>${text}</span><span class="arrow" aria-hidden="true">↑</span>`;
  bar.setAttribute("aria-label", `${text}. Back to the result`);
  bar.hidden = headlineVisible || !formVisible;
}
function watchMobileBar() {
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.target.id === "verdict") headlineVisible = e.isIntersecting;
      if (e.target.id === "form-block") formVisible = e.isIntersecting;
    }
    updateMobileBar(barText, barStale);
  });
  io.observe($("verdict"));  // the number itself, not the whole result block
  io.observe($("form-block"));
  $("mobile-bar").addEventListener("click", () => $("headline").scrollIntoView({ block: "start" }));
}

// --- charts ---

function el(name, attrs = {}, text) {
  const e = document.createElementNS(SVG, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text !== undefined) e.textContent = text;
  return e;
}

function niceTicks(min, max, n = 4) {
  const span = max - min || 1;
  const step0 = span / n;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0);
  const ticks = [];
  for (let v = Math.floor(min / step) * step; v <= max + step * 1e-9; v += step) ticks.push(+v.toFixed(10));
  return ticks;
}

// A bar with 4px rounded corners at the value end, square at the baseline.
function barPath(x0, x1, y0, y1, horizontal) {
  const r = 4;
  if (horizontal) {
    const [a, b] = [Math.min(x0, x1), Math.max(x0, x1)];
    const rr = Math.min(r, (b - a) / 2, (y1 - y0) / 2);
    if (x1 >= x0) return `M${a},${y0}H${b - rr}Q${b},${y0} ${b},${y0 + rr}V${y1 - rr}Q${b},${y1} ${b - rr},${y1}H${a}Z`;
    return `M${b},${y0}H${a + rr}Q${a},${y0} ${a},${y0 + rr}V${y1 - rr}Q${a},${y1} ${a + rr},${y1}H${b}Z`;
  }
  const [top, bot] = [Math.min(y0, y1), Math.max(y0, y1)];
  const rr = Math.min(r, (bot - top) / 2, (x1 - x0) / 2);
  if (y1 <= y0) return `M${x0},${bot}V${top + rr}Q${x0},${top} ${x0 + rr},${top}H${x1 - rr}Q${x1},${top} ${x1},${top + rr}V${bot}Z`;
  return `M${x0},${top}V${bot - rr}Q${x0},${bot} ${x0 + rr},${bot}H${x1 - rr}Q${x1},${bot} ${x1},${bot - rr}V${top}Z`;
}

function tooltip(target, html) {
  const tip = $("tooltip");
  const show = (x, y) => {
    tip.innerHTML = html;
    tip.hidden = false;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = `${Math.min(x + 14, innerWidth - w - 8)}px`;
    tip.style.top = `${Math.max(8, y - h - 12)}px`;
  };
  target.addEventListener("pointermove", (e) => show(e.clientX, e.clientY));
  target.addEventListener("pointerleave", () => (tip.hidden = true));
  target.addEventListener("focus", () => {
    const b = target.getBoundingClientRect();
    show(b.left + b.width / 2, b.top);
  });
  target.addEventListener("blur", () => (tip.hidden = true));
}

// Charts are drawn at their container's real width so text stays legible on phones.
const chartWidth = (id) => Math.max(300, Math.round($(id).clientWidth || 640));

function drawDistribution(d) {
  const W = chartWidth("dist-chart");
  const narrow = W < 520;  // on phones, put each label above its bar
  const vals = d.map((g) => g.avg_change);
  const labelW = narrow ? 0 : 104;
  const rowH = narrow ? 44 : 34, top = 8;
  // Leave room beside the bars for their value labels.
  const left = labelW + (Math.min(0, ...vals) < 0 ? 68 : 8);
  const rightPad = 8 + (Math.max(0, ...vals) > 0 ? 68 : 30);  // 30 still fits a "$0" label
  const H = top + rowH * d.length + 24;
  let min = Math.min(0, ...vals), max = Math.max(0, ...vals);
  if (max - min < 10) { min = Math.min(min, -5); max = Math.max(max, 5); }
  const ticks = niceTicks(min, max, narrow ? 2 : 4);
  min = Math.min(min, ticks[0]); max = Math.max(max, ticks[ticks.length - 1]);
  const x = (v) => left + ((v - min) / (max - min)) * (W - left - rightPad);
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Average change in federal tax per filer by income range" });

  ticks.forEach((t) => {
    svg.appendChild(el("line", { x1: x(t), x2: x(t), y1: top, y2: H - 22, stroke: "var(--grid)" }));
    svg.appendChild(el("text", { x: x(t), y: H - 6, "text-anchor": "middle", "font-size": 11 }, shortDollars(t)));
  });
  d.forEach((g, i) => {
    const rowTop = top + i * rowH;
    const y0 = narrow ? rowTop + 20 : rowTop + 7, y1 = narrow ? rowTop + rowH - 4 : rowTop + rowH - 7;
    const v = g.avg_change;
    const zero = Math.round(v) === 0;
    svg.appendChild(el("text", { ...(narrow ? { x: 0, y: rowTop + 14 } : { x: 0, y: (y0 + y1) / 2 + 4 }), "font-size": 12, class: zero ? "muted-label" : "" }, g.group));
    if (Math.abs(x(v) - x(0)) >= 1) {
      svg.appendChild(el("path", { d: barPath(x(0), x(v), y0, y1, true), style: `fill: var(${v < 0 ? "--down" : "--up"})` }));
    }
    const lx = v < 0 ? x(v) - 6 : x(Math.max(v, 0)) + 6;
    svg.appendChild(el("text", { x: lx, y: (y0 + y1) / 2 + 4, "text-anchor": v < 0 ? "end" : "start", "font-size": 12, class: zero ? "muted-label" : "value" }, perFiler(v)));
    const hit = el("rect", { x: 0, y: rowTop, width: W, height: rowH, class: "hit", tabindex: 0 });
    tooltip(hit, `<strong>${g.group}</strong>Average change: ${perFiler(v)} per filer<br>${count(g.pay_less)} pay less · ${count(g.pay_more)} pay more<br><span class="muted">${pct(g.pct_income, 2)} of taxable income · ${count(g.filers)} filers</span>`);
    svg.appendChild(hit);
  });
  svg.appendChild(el("line", { x1: x(0), x2: x(0), y1: top, y2: H - 22, stroke: "var(--ink-soft)" }));
  $("dist-chart").replaceChildren(svg);
  // A legend only when both colours appear; otherwise the signed labels say it.
  const both = vals.some((v) => v <= -1) && vals.some((v) => v >= 1);
  $("dist-legend").innerHTML = both
    ? `<span><i class="swatch" style="background:var(--down)"></i>Pays less on average</span><span><i class="swatch" style="background:var(--up)"></i>Pays more on average</span>`
    : "";
}

function shortDollars(t) {
  const a = Math.abs(t);
  const body = a >= 1000 ? `$${+(a / 1000).toFixed(1)}k` : `$${a}`;
  return t < 0 ? MINUS + body : body;
}

function drawRevenue(r, c) {
  const W = chartWidth("rev-chart"), H = 240, top = 14, bottom = 26, left = 52, right = 8;
  const n = r.years.length;
  const all = [...r[c], ...r.low, ...r.high, ...r.static].map((v) => v / 1e9);
  let min = Math.min(0, ...all), max = Math.max(0, ...all);
  if (min === max) max = 1;
  const ticks = niceTicks(min, max, 4);
  min = Math.min(min, ticks[0]); max = Math.max(max, ticks[ticks.length - 1]);
  const y = (v) => top + (1 - (v - min) / (max - min)) * (H - top - bottom);
  const band = (W - left - right) / n;
  const cx = (i) => left + band * (i + 0.5);
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Change in federal revenue by year" });

  ticks.forEach((t) => {
    svg.appendChild(el("line", { x1: left, x2: W - right, y1: y(t), y2: y(t), stroke: "var(--grid)" }));
    svg.appendChild(el("text", { x: left - 8, y: y(t) + 4, "text-anchor": "end", "font-size": 11 }, `${t < 0 ? MINUS : ""}$${Math.abs(t)}B`));
  });
  r.years.forEach((yr, i) => {
    const v = r[c][i] / 1e9;
    const bw = Math.min(30, band * 0.55);
    if (Math.abs(y(v) - y(0)) >= 1) {
      svg.appendChild(el("path", { d: barPath(cx(i) - bw / 2, cx(i) + bw / 2, y(0), y(v), false), style: "fill: var(--down)" }));
    }
    const [lo, hi] = [r.low[i], r.high[i]].map((x) => x / 1e9).sort((a, b) => a - b);
    svg.appendChild(el("line", { x1: cx(i), x2: cx(i), y1: y(lo), y2: y(hi), stroke: "var(--ink-soft)", "stroke-width": 2 }));
    svg.appendChild(el("circle", { cx: cx(i), cy: y(r.static[i] / 1e9), r: 4.5, style: "fill: var(--paper); stroke: var(--ink-soft)", "stroke-width": 2 }));
    if (band >= 34 || i % 2 === 0) {
      svg.appendChild(el("text", { x: cx(i), y: H - 8, "text-anchor": "middle", "font-size": 11 }, band >= 34 ? yr : `’${String(yr).slice(2)}`));
    }
    const hit = el("rect", { x: cx(i) - band / 2, y: top, width: band, height: H - top - bottom, class: "hit", tabindex: 0 });
    tooltip(hit, `<strong>${yr}</strong>${caseName(c)} response: ${verbMoney(r[c][i])}<br>Static: ${verbMoney(r.static[i])}<br><span class="muted">Range: ${verbMoney(Math.min(r.low[i], r.high[i]))} to ${verbMoney(Math.max(r.low[i], r.high[i]))}</span>`);
    svg.appendChild(hit);
  });
  svg.appendChild(el("line", { x1: left, x2: W - right, y1: y(0), y2: y(0), stroke: "var(--ink-soft)" }));
  $("rev-chart").replaceChildren(svg);
  $("rev-legend").innerHTML = `<span><i class="swatch" style="background:var(--down)"></i>${caseName(c)} response</span><span><i class="swatch line"></i>Range</span><span><i class="swatch ring"></i>Static</span>`;
}
const caseName = (c) => ({ low: "Small", central: "Central", high: "Large" })[c];

// --- methods section ---

function renderMethods() {
  const p = data.params, a = data.assumptions;
  $("built").textContent = `CRA 2024 data, updated ${new Date(data.built + "T12:00").toLocaleDateString("en-CA", { year: "numeric", month: "long", day: "numeric" })}`;
  $("growth-assumption").textContent = pct(a.nominal_gdp_growth.value, 2);
  $("cpi-assumption").textContent = `${pct(a.cpi_inflation.value, 0)} a year after 2026`;
  $("eti-list").innerHTML = `
    <li>Below the top bracket: ${a.eti_lower.low} (small) / ${a.eti_lower.central} (central) / ${a.eti_lower.high} (large). ${a.eti_lower.source}</li>
    <li>Top bracket: ${a.eti_top.low} / ${a.eti_top.central} / ${a.eti_top.high}. ${a.eti_top.source}</li>`;
  $("response-label").title = `Elasticity of taxable income: small ${a.eti_lower.low}/${a.eti_top.low}, central ${a.eti_lower.central}/${a.eti_top.central}, large ${a.eti_lower.high}/${a.eti_top.high} (below the top bracket / in it)`;
  document.querySelector("#calibration tbody").innerHTML = data.calibration.map((g) => `<tr>
    <td>${g.group}</td><td>${money(g.model_tax)}</td><td>${money(g.cra_tax)}</td><td>${count(g.model_taxable)}</td><td>${count(g.cra_taxable)}</td></tr>`).join("");
  $("benchmark-low").textContent = a.benchmark_lowest_rate;
  const cut = score({ ...currentLaw, rates: currentLaw.rates.map((r, i) => (i === 0 ? r - 0.01 : r)) }, p, data.records, data.groups);
  $("benchmark-model").textContent = `This model puts a one-point cut in today's lowest rate (14% to 13%) at ${money(cut.static[0])} in ${cut.years[0]} (static). Part of any gap is that the model leaves out some tax paid by low-income filers.`;
  $("sources").innerHTML = data.sources.map((s) =>
    `<li>${s.source}. <a href="${s.url}">${s.url}</a> (retrieved ${s.retrieved}).</li>`).join("") +
    `<li>Elasticity estimates: Sillamaa &amp; Veall (2001), <i>Journal of Public Economics</i>; Saez, Slemrod &amp; Giertz (2012), <i>Journal of Economic Literature</i>; Milligan &amp; Smart (2015), <i>Canadian Journal of Economics</i>; Alexandre Laurin, C.D. Howe Institute.</li>`;
}

// --- start ---

async function init() {
  data = await (await fetch("data.json")).json();
  currentLaw = data.params.current_law;
  presets = buildPresets(currentLaw);
  $("preset").innerHTML = presets.map(([id, label]) => `<option value="${id}">${label}</option>`).join("")
    + `<option value="custom" disabled>Custom reform</option>`;

  $("preset").addEventListener("change", (e) => {
    const p = presets.find(([id]) => id === e.target.value);
    if (p) setState({ ...p[2], case: state.case }, { presetId: p[0] });
  });
  $("bracket-rows").addEventListener("input", (e) => {
    const i = Number(e.target.dataset.i);
    const v = e.target.value === "" ? NaN : Number(e.target.value);
    if (e.target.dataset.kind === "t") state.thresholds[i] = v;
    if (e.target.dataset.kind === "r") state.rates[i] = v / 100;
    $("preset").value = matchPreset();
    update();
  });
  $("bracket-rows").addEventListener("click", (e) => {
    if (!e.target.classList.contains("remove")) return;
    const i = Number(e.target.dataset.i);
    state.thresholds.splice(i, 1);
    state.rates.splice(i, 1);
    renderBrackets();
    $("preset").value = matchPreset();
    update();
  });
  $("add-bracket").addEventListener("click", () => {
    const last = state.thresholds[state.thresholds.length - 1];
    state.thresholds.push(Math.max(last * 2, last + 50000));
    state.rates.push(Math.min(state.rates[state.rates.length - 1] + 0.02, 0.99));
    renderBrackets();
    $("preset").value = matchPreset();
    update();
  });
  $("bpa").addEventListener("input", (e) => {
    state.bpa_max = e.target.value === "" ? NaN : Number(e.target.value);
    $("preset").value = matchPreset();
    update();
  });
  document.querySelectorAll('input[name="case"]').forEach((r) =>
    r.addEventListener("change", (e) => { state.case = e.target.value; update(); }));
  $("copy-link").addEventListener("click", async () => {
    const btn = $("copy-link");
    try {
      await navigator.clipboard.writeText(location.href);
      btn.textContent = "Copied";
    } catch {
      btn.textContent = "Copy the address bar";
    }
    setTimeout(() => (btn.textContent = "Copy link"), 2000);
  });
  $("methods-link").addEventListener("click", (e) => {
    e.preventDefault();  // a #methods hash would replace the reform in the shareable link
    $("methods-details").open = true;
    $("methods").scrollIntoView({ block: "start" });
  });

  renderMethods();
  watchMobileBar();
  const fromUrl = fromHash();
  setState(fromUrl ?? { ...currentLaw, case: "central" });
}

init().catch((err) => {
  $("ten-year").textContent = "Couldn't load";
  $("errors").textContent = `The explorer couldn't load its data (${err.message}).`;
});
