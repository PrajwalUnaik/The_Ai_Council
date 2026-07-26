"""Generate a self-contained HTML report for an RQ1 benchmark run.

Reads results.jsonl (+ run_config.json) from a run directory and writes
report.html next to it: KPI tiles, agreement-vs-accuracy charts, run
progression, per-model and per-domain accuracy, and a full item table.
Can be run mid-run for a progress snapshot; re-run after completion for
the final page.

Usage:
    uv run python benchmarks/make_report.py benchmarks/results/rq1-main
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def load_run(run_dir: Path):
    results_path = run_dir / "results.jsonl"
    if not results_path.exists():
        sys.exit(f"No results.jsonl in {run_dir}")
    records = []
    with results_path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    config = {}
    config_path = run_dir / "run_config.json"
    if config_path.exists():
        config = json.loads(config_path.read_text())
    return records, config


def slim(records):
    """Keep only the fields the page needs (drop long response texts)."""
    out = []
    for r in records:
        agreement = r.get("agreement") or {}
        out.append({
            "item_id": r.get("item_id"),
            "domain": r.get("domain"),
            "w": agreement.get("kendalls_w"),
            "tau": agreement.get("mean_pairwise_tau"),
            "top1": agreement.get("top1_agreement"),
            "entropy": agreement.get("top1_entropy"),
            "state": agreement.get("council_state"),
            "answer": r.get("extracted_answer"),
            "key": r.get("correct_answer"),
            "correct": bool(r.get("correct")),
            "top1_model": r.get("top1_model"),
            "top1_correct": r.get("top1_model_correct"),
            "members": [
                {"model": m.get("model"), "answer": m.get("answer"),
                 "correct": bool(m.get("correct"))}
                for m in (r.get("members") or [])
            ],
            "cost": r.get("total_cost_usd"),
            "elapsed": r.get("elapsed_s"),
            "error": r.get("error"),
        })
    return out


def pick_examples(records, benchmark_path, k=5):
    """Choose k illustrative items and attach their question/options text."""
    questions = {}
    if benchmark_path and benchmark_path.exists():
        with benchmark_path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    item = json.loads(line)
                    questions[item["item_id"]] = item
    graded = [r for r in records if not r.get("error")]
    w = lambda r: (r.get("agreement") or {}).get("kendalls_w")
    top1 = lambda r: (r.get("agreement") or {}).get("top1_agreement")
    with_w = [r for r in graded if w(r) is not None]

    picks = []
    def add(label, blurb, candidates):
        chosen = {p[2]["item_id"] for p in picks}
        for r in candidates:
            if r["item_id"] not in chosen and r["item_id"] in questions:
                picks.append((label, blurb, r))
                return
    correct_by_w = sorted([r for r in with_w if r["correct"]], key=w)
    add("Strong agreement → correct",
        "The typical good case: rankings almost identical, answer right.",
        list(reversed(correct_by_w)))
    add("Chairman overruled the top vote → correct",
        "The council's favourite response was wrong; the chairman's synthesis fixed it.",
        sorted([r for r in graded
                if r["correct"] and r.get("top1_model_correct") is False],
               key=lambda r: top1(r) or 0, reverse=True))
    add("Weak agreement → correct (council recovered)",
        "Rankings disagreed, yet synthesis still landed on the key.",
        correct_by_w)
    add("Split top-1 vote → correct",
        "No response got a majority of best-votes, but the final answer held.",
        sorted([r for r in graded if r["correct"] and top1(r) is not None], key=top1))
    add("Weak agreement → wrong (the warning light works)",
        "The council scattered and the final answer missed — low W flagged it.",
        sorted([r for r in with_w if not r["correct"]], key=w))
    # Backfill with further correct items if any selector came up empty;
    # prefer middling agreement so the set stays varied.
    for r in sorted(correct_by_w, key=lambda r: abs(w(r) - 0.6)):
        if len(picks) >= k:
            break
        add("Moderate agreement → correct",
            "An in-between case: partial ranking agreement, answer still right.", [r])

    examples = []
    for label, blurb, r in picks[:k]:
        q = questions[r["item_id"]]
        agreement = r.get("agreement") or {}
        examples.append({
            "label": label, "blurb": blurb,
            "item_id": r["item_id"], "domain": r.get("domain"),
            "question": q["question"],
            "options": q["options"],
            "key": r.get("correct_answer"),
            "answer": r.get("extracted_answer"),
            "correct": bool(r.get("correct")),
            "w": agreement.get("kendalls_w"),
            "top1": agreement.get("top1_agreement"),
            "state": agreement.get("council_state"),
            "members": [
                {"model": (m.get("model") or "?").split("/")[-1],
                 "answer": m.get("answer"), "correct": bool(m.get("correct"))}
                for m in (r.get("members") or [])
            ],
        })
    return examples


HTML_TEMPLATE = r"""<title>RQ1 Benchmark Run — The AI Counsel</title>
<style>
  .viz-root {
    color-scheme: light;
    --surface-1: #fcfcfb; --page: #f9f9f7;
    --ink-1: #0b0b0b; --ink-2: #52514e; --ink-3: #898781;
    --grid: #e1e0d9; --baseline: #c3c2b7;
    --border: rgba(11,11,11,0.10);
    --series-1: #2a78d6; --series-2: #008300; --series-3: #e87ba4; --series-4: #eda100;
    --seq-250: #86b6ef; --seq-350: #5598e7; --seq-450: #2a78d6; --seq-550: #1c5cab; --seq-650: #104281;
    --deemph: #c3c2b7;
    --good: #0ca30c; --critical: #d03b3b;
    --good-text: #006300;
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    background: var(--page); color: var(--ink-1);
    margin: 0; padding: 24px; line-height: 1.45;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) .viz-root {
      color-scheme: dark;
      --surface-1: #1a1a19; --page: #0d0d0d;
      --ink-1: #ffffff; --ink-2: #c3c2b7; --ink-3: #898781;
      --grid: #2c2c2a; --baseline: #383835;
      --border: rgba(255,255,255,0.10);
      --series-1: #3987e5; --series-2: #008300; --series-3: #d55181; --series-4: #c98500;
      --seq-250: #86b6ef; --seq-350: #5598e7; --seq-450: #3987e5; --seq-550: #256abf; --seq-650: #184f95;
      --deemph: #52514e;
      --good-text: #0ca30c;
    }
  }
  :root[data-theme="dark"] .viz-root {
    color-scheme: dark;
    --surface-1: #1a1a19; --page: #0d0d0d;
    --ink-1: #ffffff; --ink-2: #c3c2b7; --ink-3: #898781;
    --grid: #2c2c2a; --baseline: #383835;
    --border: rgba(255,255,255,0.10);
    --series-1: #3987e5; --series-2: #008300; --series-3: #d55181; --series-4: #c98500;
    --seq-250: #86b6ef; --seq-350: #5598e7; --seq-450: #3987e5; --seq-550: #256abf; --seq-650: #184f95;
    --deemph: #52514e;
    --good-text: #0ca30c;
  }
  .viz-root * { box-sizing: border-box; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  h2 { font-size: 15px; margin: 28px 0 4px; }
  .sub { color: var(--ink-2); font-size: 13px; margin: 0 0 6px; }
  .note { color: var(--ink-3); font-size: 12px; margin: 2px 0 10px; }
  .card {
    background: var(--surface-1); border: 1px solid var(--border);
    border-radius: 10px; padding: 14px 16px;
  }
  .kpis { display: flex; flex-wrap: wrap; gap: 10px; margin: 16px 0 4px; }
  .kpis .card { flex: 1 1 150px; min-width: 150px; }
  .kpi-label { font-size: 12px; color: var(--ink-2); }
  .kpi-value { font-size: 30px; font-weight: 600; margin-top: 2px; }
  .kpi-detail { font-size: 12px; color: var(--ink-3); margin-top: 2px; }
  .row { display: flex; flex-wrap: wrap; gap: 10px; }
  .row .card { flex: 1 1 300px; min-width: 280px; }
  .chart-title { font-size: 13px; font-weight: 600; margin: 0 0 2px; }
  .chart-sub { font-size: 12px; color: var(--ink-3); margin: 0 0 8px; }
  svg { display: block; max-width: 100%; }
  svg text { font-family: inherit; }
  .legend { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12px;
            color: var(--ink-2); margin-top: 8px; align-items: center; }
  .legend .swatch { display: inline-block; width: 10px; height: 10px;
                    border-radius: 2px; margin-right: 5px; vertical-align: -1px; }
  .strip { display: flex; flex-wrap: wrap; gap: 2px; }
  .strip .cell { width: 14px; height: 14px; border-radius: 3px; cursor: default; }
  .strip .cell:hover { outline: 2px solid var(--ink-2); outline-offset: 1px; }
  .tablewrap { overflow-x: auto; max-height: 420px; overflow-y: auto;
               border: 1px solid var(--border); border-radius: 8px; }
  table { border-collapse: collapse; font-size: 12px; width: 100%;
          font-variant-numeric: tabular-nums; }
  th { position: sticky; top: 0; background: var(--surface-1);
       text-align: left; color: var(--ink-2); font-weight: 600; z-index: 1; }
  th, td { padding: 6px 10px; border-bottom: 1px solid var(--grid);
           white-space: nowrap; }
  td { color: var(--ink-1); }
  td.ok { color: var(--good-text); font-weight: 600; }
  td.bad { color: var(--critical); font-weight: 600; }
  #tooltip {
    position: fixed; pointer-events: none; z-index: 10; display: none;
    background: var(--surface-1); border: 1px solid var(--border);
    border-radius: 8px; padding: 8px 10px; font-size: 12px;
    box-shadow: 0 4px 14px rgba(0,0,0,0.18); max-width: 300px;
  }
  #tooltip .tt-title { color: var(--ink-2); margin-bottom: 3px; }
  #tooltip .tt-row { display: flex; gap: 8px; align-items: center; }
  #tooltip .tt-val { font-weight: 600; }
  #tooltip .tt-key { display: inline-block; width: 12px; height: 3px;
                     border-radius: 2px; }
  footer { color: var(--ink-3); font-size: 12px; margin-top: 26px; }
  .examples { display: flex; flex-direction: column; gap: 10px; }
  .ex-head { display: flex; justify-content: space-between; gap: 10px;
             align-items: baseline; flex-wrap: wrap; }
  .ex-tag { font-size: 11px; font-weight: 600; letter-spacing: 0.04em;
            text-transform: uppercase; color: var(--ink-2); }
  .ex-verdict { font-size: 12px; font-weight: 600; }
  .ex-verdict.ok { color: var(--good-text); }
  .ex-verdict.bad { color: var(--critical); }
  .ex-blurb { font-size: 12px; color: var(--ink-3); margin: 2px 0 8px; }
  .ex-q { font-size: 13px; margin: 0 0 10px; max-width: 72ch; }
  .ex-meta { font-size: 12px; color: var(--ink-3); margin-top: 10px; }
  .opt { display: flex; gap: 8px; align-items: baseline; padding: 5px 8px;
         border-left: 3px solid var(--grid); margin: 3px 0; font-size: 12.5px; }
  .opt.key { border-left-color: var(--good); }
  .opt.wrongpick { border-left-color: var(--critical); }
  .opt-letter { font-weight: 600; min-width: 14px; }
  .chip { display: inline-block; font-size: 10.5px; padding: 1px 7px;
          border: 1px solid var(--border); border-radius: 999px;
          color: var(--ink-2); margin-left: 4px; white-space: nowrap; }
  .chip.keychip { border-color: var(--good); color: var(--good-text); }
  .chip.chair { border-color: var(--series-1); color: var(--ink-1); font-weight: 600; }
  details.ex-all { margin-top: 6px; font-size: 12px; color: var(--ink-2); }
  details.ex-all summary { cursor: pointer; color: var(--ink-3); }
  details.ex-all li { margin: 3px 0; }
</style>
<div class="viz-root">
  <h1>RQ1 Benchmark Run</h1>
  <p class="sub" id="subtitle"></p>
  <p class="note" id="runmeta"></p>

  <div class="kpis" id="kpis"></div>

  <h2>Does agreement predict correctness?</h2>
  <p class="note">Exploratory view — the formal RQ1 test (logistic regression / AUROC) runs on the exported CSV.</p>
  <div class="row">
    <div class="card">
      <p class="chart-title">Accuracy by council state</p>
      <p class="chart-sub" id="state-sub"></p>
      <div id="chart-state"></div>
    </div>
    <div class="card">
      <p class="chart-title">Accuracy by top-1 vote agreement</p>
      <p class="chart-sub">share of rankers voting for the same response</p>
      <div id="chart-top1"></div>
    </div>
    <div class="card">
      <p class="chart-title">Accuracy by Kendall's W</p>
      <p class="chart-sub" id="w-sub"></p>
      <div id="chart-w"></div>
    </div>
  </div>

  <h2>Run progression</h2>
  <div class="row">
    <div class="card" style="flex:2 1 420px">
      <p class="chart-title">Cumulative accuracy over the run</p>
      <p class="chart-sub">chairman answer, in run order</p>
      <div id="chart-cum"></div>
    </div>
    <div class="card" style="flex:1 1 300px">
      <p class="chart-title">Item outcomes in run order</p>
      <p class="chart-sub">hover a cell for the item</p>
      <div class="strip" id="strip"></div>
      <div class="legend">
        <span><span class="swatch" style="background:var(--good)"></span>✓ correct</span>
        <span><span class="swatch" style="background:var(--critical)"></span>✗ incorrect</span>
        <span><span class="swatch" style="background:var(--deemph)"></span>error / ungraded</span>
      </div>
    </div>
  </div>

  <h2>Who gets it right?</h2>
  <div class="row">
    <div class="card" style="flex:3 1 420px">
      <p class="chart-title">Accuracy: council members vs top-voted vs chairman</p>
      <p class="chart-sub">chairman (final answer) highlighted</p>
      <div id="chart-models"></div>
    </div>
    <div class="card" style="flex:2 1 320px">
      <p class="chart-title">Accuracy by domain</p>
      <p class="chart-sub">chairman answer per MMLU-Pro category</p>
      <div id="chart-domains"></div>
    </div>
  </div>

  <h2>All items</h2>
  <div class="tablewrap"><table id="items-table"></table></div>

  <h2>Five worked examples</h2>
  <p class="note">Real items from this run, chosen to show each regime the agreement signal can be in.</p>
  <div class="examples" id="examples"></div>

  <footer id="footer"></footer>
  <div id="tooltip"></div>
</div>

<script>
const DATA = __DATA__;
const CONFIG = __CONFIG__;
const GENERATED = __GENERATED__;
const EXAMPLES = __EXAMPLES__;

const fmtPct = v => (v == null ? "–" : Math.round(v * 100) + "%");
const fmtUsd = v => (v == null ? "–" : "$" + v.toFixed(2));
const esc = s => String(s == null ? "–" : s);

const graded = DATA.filter(r => !r.error);
const errors = DATA.filter(r => r.error);
const nCorrect = graded.filter(r => r.correct).length;
const accuracy = graded.length ? nCorrect / graded.length : null;
const totalCost = graded.reduce((s, r) => s + (r.cost || 0), 0);
const consensus = graded.filter(r => r.state === "consensus");
const divided = graded.filter(r => r.state === "divided");
const ws = graded.map(r => r.w).filter(v => v != null);
const meanW = ws.length ? ws.reduce((a, b) => a + b, 0) / ws.length : null;

// ---------- header ----------
document.getElementById("subtitle").textContent =
  "The AI Counsel — inter-model agreement vs answer quality (MMLU-Pro)";
const councilNames = (CONFIG.models || []).map(m => m.split("/").pop());
document.getElementById("runmeta").textContent =
  "Council: " + councilNames.join(", ") +
  "  ·  Chairman: " + String(CONFIG.chairman || "settings default").split("/").pop() +
  "  ·  Benchmark: " + (CONFIG.benchmark || "?") +
  "  ·  Generated " + GENERATED;

// ---------- tooltip ----------
const tip = document.getElementById("tooltip");
function showTip(evt, title, rows) {
  tip.textContent = "";
  const t = document.createElement("div");
  t.className = "tt-title";
  t.textContent = title;
  tip.appendChild(t);
  for (const [label, value, color] of rows) {
    const row = document.createElement("div");
    row.className = "tt-row";
    if (color) {
      const k = document.createElement("span");
      k.className = "tt-key";
      k.style.background = color;
      row.appendChild(k);
    }
    const v = document.createElement("span");
    v.className = "tt-val";
    v.textContent = value;
    row.appendChild(v);
    const l = document.createElement("span");
    l.textContent = label;
    l.style.color = "var(--ink-3)";
    row.appendChild(l);
    tip.appendChild(row);
  }
  tip.style.display = "block";
  moveTip(evt);
}
function moveTip(evt) {
  const pad = 14;
  let x = evt.clientX + pad, y = evt.clientY + pad;
  const r = tip.getBoundingClientRect();
  if (x + r.width > innerWidth - 8) x = evt.clientX - r.width - pad;
  if (y + r.height > innerHeight - 8) y = evt.clientY - r.height - pad;
  tip.style.left = x + "px";
  tip.style.top = y + "px";
}
function hideTip() { tip.style.display = "none"; }

// ---------- KPI tiles ----------
const kpis = [
  ["Items graded", String(graded.length),
   errors.length ? errors.length + " errors" : "no errors"],
  ["Chairman accuracy", fmtPct(accuracy), nCorrect + " of " + graded.length + " correct"],
  ["Consensus share", fmtPct(graded.length ? consensus.length / graded.length : null),
   consensus.length + " consensus · " + divided.length + " divided"],
  ["Mean Kendall's W", meanW == null ? "–" : meanW.toFixed(3), "ranking concordance"],
  ["Total cost", fmtUsd(totalCost),
   graded.length ? fmtUsd(totalCost / graded.length).replace("$", "$") + " per item" : ""],
];
document.getElementById("kpis").innerHTML = kpis.map(() =>
  '<div class="card"><div class="kpi-label"></div><div class="kpi-value"></div><div class="kpi-detail"></div></div>'
).join("");
document.querySelectorAll("#kpis .card").forEach((el, i) => {
  el.querySelector(".kpi-label").textContent = kpis[i][0];
  el.querySelector(".kpi-value").textContent = kpis[i][1];
  el.querySelector(".kpi-detail").textContent = kpis[i][2];
});

// ---------- SVG helpers ----------
const SVGNS = "http://www.w3.org/2000/svg";
function el(name, attrs, parent) {
  const node = document.createElementNS(SVGNS, name);
  for (const k in attrs) node.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(node);
  return node;
}
function svgText(parent, x, y, str, attrs) {
  const t = el("text", Object.assign({ x, y, "font-size": 11, fill: "var(--ink-2)" }, attrs || {}), parent);
  t.textContent = str;
  return t;
}
// Column with 4px rounded top corners, square baseline.
function roundedColumn(parent, x, yTop, w, h, fill) {
  const r = Math.min(4, w / 2, h);
  const d = h <= 0 ? "" :
    `M${x},${yTop + h} L${x},${yTop + r} Q${x},${yTop} ${x + r},${yTop}` +
    ` L${x + w - r},${yTop} Q${x + w},${yTop} ${x + w},${yTop + r}` +
    ` L${x + w},${yTop + h} Z`;
  return el("path", { d, fill }, parent);
}
// Horizontal bar with 4px rounded right end, square at baseline (left).
function roundedBar(parent, x, y, w, h, fill) {
  const r = Math.min(4, h / 2, w);
  const d = w <= 0 ? "" :
    `M${x},${y} L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r}` +
    ` L${x + w},${y + h - r} Q${x + w},${y + h} ${x + w - r},${y + h}` +
    ` L${x},${y + h} Z`;
  return el("path", { d, fill }, parent);
}

// Generic accuracy column chart: bins = [{label, sub, acc, n, fill}]
function accuracyColumns(containerId, bins, opts) {
  const container = document.getElementById(containerId);
  const W = opts && opts.width || 320, H = 190;
  const m = { t: 14, r: 8, b: 34, l: 34 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%" });
  container.appendChild(svg);
  // gridlines at 0/50/100%
  for (const g of [0, 0.5, 1]) {
    const y = m.t + ih - g * ih;
    el("line", { x1: m.l, x2: m.l + iw, y1: y, y2: y,
                 stroke: g === 0 ? "var(--baseline)" : "var(--grid)", "stroke-width": 1 }, svg);
    svgText(svg, m.l - 6, y + 4, Math.round(g * 100) + "%",
            { "text-anchor": "end", fill: "var(--ink-3)", "font-size": 10 });
  }
  const slot = iw / bins.length;
  const bw = Math.min(24, slot * 0.55);
  bins.forEach((b, i) => {
    const cx = m.l + slot * i + slot / 2;
    const h = (b.acc == null ? 0 : b.acc) * ih;
    const y = m.t + ih - h;
    const bar = roundedColumn(svg, cx - bw / 2, y, bw, h, b.fill);
    if (b.acc != null)
      svgText(svg, cx, y - 5, Math.round(b.acc * 100) + "%",
              { "text-anchor": "middle", "font-weight": 600, fill: "var(--ink-1)" });
    svgText(svg, cx, m.t + ih + 14, b.label, { "text-anchor": "middle" });
    svgText(svg, cx, m.t + ih + 27, "n=" + b.n,
            { "text-anchor": "middle", fill: "var(--ink-3)", "font-size": 10 });
    const hit = el("rect", { x: m.l + slot * i, y: m.t, width: slot, height: ih + m.b,
                             fill: "transparent" }, svg);
    for (const target of [bar, hit]) {
      target.addEventListener("pointermove", evt => {
        showTip(evt, b.sub || b.label, [
          ["accuracy", fmtPct(b.acc), b.fill],
          ["items", String(b.n)],
        ]);
      });
      target.addEventListener("pointerleave", hideTip);
    }
  });
}

// ---------- agreement charts ----------
function acc(list) {
  const g = list.filter(r => !r.error);
  return g.length ? g.filter(r => r.correct).length / g.length : null;
}
document.getElementById("state-sub").textContent =
  "threshold: top-1 agreement ≥ 0.75 → consensus";
accuracyColumns("chart-state", [
  { label: "consensus", acc: acc(consensus), n: consensus.length, fill: "var(--seq-550)" },
  { label: "divided", acc: acc(divided), n: divided.length, fill: "var(--seq-250)" },
]);

const top1Groups = {};
for (const r of graded) {
  if (r.top1 == null) continue;
  const key = Math.round(r.top1 * 100) + "%";
  (top1Groups[key] = top1Groups[key] || []).push(r);
}
const top1Keys = Object.keys(top1Groups).sort((a, b) => parseInt(a) - parseInt(b));
const seqSteps = ["var(--seq-250)", "var(--seq-350)", "var(--seq-450)", "var(--seq-550)", "var(--seq-650)"];
accuracyColumns("chart-top1", top1Keys.map((k, i) => ({
  label: k, sub: "top-1 agreement " + k,
  acc: acc(top1Groups[k]), n: top1Groups[k].length,
  fill: seqSteps[Math.min(i + (5 - top1Keys.length), 4)] || seqSteps[4],
})));

const wBins = [
  { label: "< 0.4", test: w => w < 0.4, fill: "var(--seq-250)" },
  { label: "0.4–0.7", test: w => w >= 0.4 && w < 0.7, fill: "var(--seq-450)" },
  { label: "≥ 0.7", test: w => w >= 0.7, fill: "var(--seq-650)" },
].map(b => {
  const items = graded.filter(r => r.w != null && b.test(r.w));
  return { label: b.label, sub: "Kendall's W " + b.label, acc: acc(items), n: items.length, fill: b.fill };
});
document.getElementById("w-sub").textContent = "ranking concordance, binned";
accuracyColumns("chart-w", wBins);

// ---------- cumulative accuracy line ----------
(function cumulative() {
  const pts = [];
  let c = 0;
  graded.forEach((r, i) => {
    c += r.correct ? 1 : 0;
    pts.push({ i: i + 1, acc: c / (i + 1), id: r.item_id, correct: r.correct });
  });
  const container = document.getElementById("chart-cum");
  if (!pts.length) { container.textContent = "No data yet."; return; }
  const W = 560, H = 200;
  const m = { t: 12, r: 14, b: 26, l: 38 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%" });
  container.appendChild(svg);
  const x = i => m.l + (pts.length === 1 ? iw / 2 : (i - 1) / (pts.length - 1) * iw);
  const y = a => m.t + ih - a * ih;
  for (const g of [0, 0.25, 0.5, 0.75, 1]) {
    el("line", { x1: m.l, x2: m.l + iw, y1: y(g), y2: y(g),
                 stroke: g === 0 ? "var(--baseline)" : "var(--grid)", "stroke-width": 1 }, svg);
    svgText(svg, m.l - 6, y(g) + 4, Math.round(g * 100) + "%",
            { "text-anchor": "end", fill: "var(--ink-3)", "font-size": 10 });
  }
  svgText(svg, m.l + iw / 2, H - 6, "items completed (run order)",
          { "text-anchor": "middle", fill: "var(--ink-3)", "font-size": 10 });
  const dLine = pts.map((p, k) => (k ? "L" : "M") + x(p.i) + "," + y(p.acc)).join(" ");
  el("path", { d: dLine + ` L${x(pts[pts.length - 1].i)},${y(0)} L${x(pts[0].i)},${y(0)} Z`,
               fill: "var(--series-1)", opacity: 0.1 }, svg);
  el("path", { d: dLine, fill: "none", stroke: "var(--series-1)", "stroke-width": 2,
               "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
  const last = pts[pts.length - 1];
  el("circle", { cx: x(last.i), cy: y(last.acc), r: 4.5, fill: "var(--series-1)",
                 stroke: "var(--surface-1)", "stroke-width": 2 }, svg);
  svgText(svg, x(last.i) - 6, y(last.acc) - 9, fmtPct(last.acc),
          { "text-anchor": "end", "font-weight": 600, fill: "var(--ink-1)" });
  // crosshair
  const cross = el("line", { y1: m.t, y2: m.t + ih, stroke: "var(--baseline)",
                             "stroke-width": 1, visibility: "hidden" }, svg);
  const dot = el("circle", { r: 4.5, fill: "var(--series-1)", stroke: "var(--surface-1)",
                             "stroke-width": 2, visibility: "hidden" }, svg);
  const hit = el("rect", { x: m.l, y: m.t, width: iw, height: ih, fill: "transparent" }, svg);
  hit.addEventListener("pointermove", evt => {
    const box = svg.getBoundingClientRect();
    const px = (evt.clientX - box.left) / box.width * W;
    const idx = Math.max(1, Math.min(pts.length,
      Math.round((px - m.l) / iw * (pts.length - 1)) + 1));
    const p = pts[idx - 1];
    cross.setAttribute("x1", x(p.i)); cross.setAttribute("x2", x(p.i));
    cross.setAttribute("visibility", "visible");
    dot.setAttribute("cx", x(p.i)); dot.setAttribute("cy", y(p.acc));
    dot.setAttribute("visibility", "visible");
    showTip(evt, "after item " + p.i + " (" + p.id + ")", [
      ["cumulative accuracy", fmtPct(p.acc), "var(--series-1)"],
      ["this item", p.correct ? "correct" : "incorrect"],
    ]);
  });
  hit.addEventListener("pointerleave", () => {
    cross.setAttribute("visibility", "hidden");
    dot.setAttribute("visibility", "hidden");
    hideTip();
  });
})();

// ---------- outcome strip ----------
(function strip() {
  const wrap = document.getElementById("strip");
  DATA.forEach((r, i) => {
    const cell = document.createElement("div");
    cell.className = "cell";
    cell.style.background = r.error ? "var(--deemph)"
      : r.correct ? "var(--good)" : "var(--critical)";
    cell.addEventListener("pointermove", evt => {
      showTip(evt, "#" + (i + 1) + " · " + r.item_id, [
        [r.error ? "run error" : (r.correct ? "correct" : "incorrect"),
         r.error ? "!" : (r.answer || "?") + " / key " + r.key,
         r.error ? "var(--deemph)" : (r.correct ? "var(--good)" : "var(--critical)")],
        ["domain", esc(r.domain)],
        ["council", esc(r.state)],
      ]);
    });
    cell.addEventListener("pointerleave", hideTip);
    wrap.appendChild(cell);
  });
})();

// ---------- model comparison (emphasis: chairman highlighted) ----------
(function models() {
  const byModel = {};
  for (const r of graded) {
    for (const m of r.members) {
      const key = m.model || "?";
      (byModel[key] = byModel[key] || []).push(m.correct);
    }
  }
  const rows = Object.keys(byModel).map(k => ({
    label: k.split("/").pop(),
    acc: byModel[k].filter(Boolean).length / byModel[k].length,
    n: byModel[k].length, fill: "var(--deemph)", kind: "council member",
  }));
  const withTop1 = graded.filter(r => r.top1_correct != null);
  rows.push({
    label: "top-voted response",
    acc: withTop1.length ? withTop1.filter(r => r.top1_correct).length / withTop1.length : null,
    n: withTop1.length, fill: "var(--deemph)", kind: "council's #1 pick",
  });
  rows.push({
    label: "chairman (final)", acc: accuracy, n: graded.length,
    fill: "var(--series-1)", kind: "synthesized answer",
  });
  const container = document.getElementById("chart-models");
  const W = 560, rowH = 30, m = { t: 6, r: 56, b: 6, l: 170 };
  const H = m.t + rows.length * rowH + m.b;
  const iw = W - m.l - m.r;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%" });
  container.appendChild(svg);
  el("line", { x1: m.l, x2: m.l, y1: m.t, y2: H - m.b,
               stroke: "var(--baseline)", "stroke-width": 1 }, svg);
  rows.forEach((r, i) => {
    const yMid = m.t + i * rowH + rowH / 2;
    svgText(svg, m.l - 8, yMid + 4, r.label,
            { "text-anchor": "end", fill: "var(--ink-1)",
              "font-weight": r.label.startsWith("chairman") ? 600 : 400 });
    const w = (r.acc || 0) * iw;
    const bar = roundedBar(svg, m.l, yMid - 9, w, 18, r.fill);
    svgText(svg, m.l + w + 6, yMid + 4, fmtPct(r.acc),
            { "font-weight": 600, fill: "var(--ink-1)" });
    const hit = el("rect", { x: 0, y: m.t + i * rowH, width: W, height: rowH,
                             fill: "transparent" }, svg);
    for (const target of [bar, hit]) {
      target.addEventListener("pointermove", evt =>
        showTip(evt, r.label + " — " + r.kind, [
          ["accuracy", fmtPct(r.acc), r.fill],
          ["graded answers", String(r.n)],
        ]));
      target.addEventListener("pointerleave", hideTip);
    }
  });
})();

// ---------- domains ----------
(function domains() {
  const byDomain = {};
  for (const r of graded) (byDomain[r.domain || "?"] = byDomain[r.domain || "?"] || []).push(r);
  const rows = Object.keys(byDomain).sort().map(d => ({
    label: d, acc: acc(byDomain[d]), n: byDomain[d].length,
  }));
  const container = document.getElementById("chart-domains");
  const W = 400, rowH = 24, m = { t: 4, r: 50, b: 4, l: 128 };
  const H = m.t + rows.length * rowH + m.b;
  const iw = W - m.l - m.r;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%" });
  container.appendChild(svg);
  el("line", { x1: m.l, x2: m.l, y1: m.t, y2: H - m.b,
               stroke: "var(--baseline)", "stroke-width": 1 }, svg);
  rows.forEach((r, i) => {
    const yMid = m.t + i * rowH + rowH / 2;
    svgText(svg, m.l - 8, yMid + 4, r.label, { "text-anchor": "end", "font-size": 11 });
    const w = (r.acc || 0) * iw;
    const bar = roundedBar(svg, m.l, yMid - 8, w, 16, "var(--seq-450)");
    const lbl = svgText(svg, m.l + w + 6, yMid + 4, fmtPct(r.acc),
            { fill: "var(--ink-1)", "font-size": 11, "font-weight": 600 });
    const nSpan = document.createElementNS(SVGNS, "tspan");
    nSpan.setAttribute("fill", "var(--ink-3)");
    nSpan.setAttribute("font-weight", "400");
    nSpan.textContent = " ·" + r.n;
    lbl.appendChild(nSpan);
    const hit = el("rect", { x: 0, y: m.t + i * rowH, width: W, height: rowH,
                             fill: "transparent" }, svg);
    for (const target of [bar, hit]) {
      target.addEventListener("pointermove", evt =>
        showTip(evt, r.label, [
          ["accuracy", fmtPct(r.acc), "var(--seq-450)"],
          ["items", String(r.n)],
        ]));
      target.addEventListener("pointerleave", hideTip);
    }
  });
})();

// ---------- table ----------
(function table() {
  const tbl = document.getElementById("items-table");
  const cols = ["#", "item", "domain", "state", "W", "top-1", "answer", "key",
                "result", "top-voted ok", "cost", "time"];
  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  for (const c of cols) {
    const th = document.createElement("th");
    th.textContent = c;
    hr.appendChild(th);
  }
  thead.appendChild(hr);
  tbl.appendChild(thead);
  const tbody = document.createElement("tbody");
  DATA.forEach((r, i) => {
    const tr = document.createElement("tr");
    const cells = r.error
      ? [i + 1, r.item_id, r.domain, "—", "—", "—", "—", "—", "error", "—", "—",
         (r.elapsed || "") + "s"]
      : [i + 1, r.item_id, r.domain, r.state,
         r.w == null ? "–" : r.w.toFixed(2), fmtPct(r.top1),
         r.answer || "?", r.key, r.correct ? "✓ correct" : "✗ wrong",
         r.top1_correct == null ? "–" : (r.top1_correct ? "✓" : "✗"),
         r.cost == null ? "–" : "$" + r.cost.toFixed(3),
         (r.elapsed || "–") + "s"];
    cells.forEach((c, k) => {
      const td = document.createElement("td");
      td.textContent = String(c);
      if (k === 8 && !r.error) td.className = r.correct ? "ok" : "bad";
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  tbl.appendChild(tbody);
})();

// ---------- worked examples ----------
(function examples() {
  const wrap = document.getElementById("examples");
  const LETTERS = "ABCDEFGHIJKLMNOP";
  if (!EXAMPLES.length) {
    wrap.textContent = "Benchmark file not found — regenerate from the repo root to include examples.";
    return;
  }
  for (const ex of EXAMPLES) {
    const card = document.createElement("div");
    card.className = "card";

    const head = document.createElement("div");
    head.className = "ex-head";
    const tag = document.createElement("span");
    tag.className = "ex-tag";
    tag.textContent = ex.label;
    const verdict = document.createElement("span");
    verdict.className = "ex-verdict " + (ex.correct ? "ok" : "bad");
    verdict.textContent = ex.correct
      ? "✓ final answer " + ex.answer + " — correct"
      : "✗ final answer " + (ex.answer || "?") + " — key was " + ex.key;
    head.append(tag, verdict);
    card.appendChild(head);

    const blurb = document.createElement("p");
    blurb.className = "ex-blurb";
    blurb.textContent = ex.blurb;
    card.appendChild(blurb);

    const q = document.createElement("p");
    q.className = "ex-q";
    q.textContent = ex.question;
    card.appendChild(q);

    // options that matter: the key, the chairman's pick, every member pick
    const picked = new Set([ex.key, ex.answer]);
    for (const m of ex.members) if (m.answer) picked.add(m.answer);
    ex.options.forEach((text, i) => {
      const letter = LETTERS[i];
      if (!picked.has(letter)) return;
      const row = document.createElement("div");
      row.className = "opt" + (letter === ex.key ? " key"
        : " wrongpick");
      const l = document.createElement("span");
      l.className = "opt-letter";
      l.textContent = letter + ".";
      const t = document.createElement("span");
      t.textContent = text.length > 150 ? text.slice(0, 150) + "…" : text;
      row.append(l, t);
      if (letter === ex.key) {
        const c = document.createElement("span");
        c.className = "chip keychip";
        c.textContent = "correct answer";
        row.appendChild(c);
      }
      if (letter === ex.answer) {
        const c = document.createElement("span");
        c.className = "chip chair";
        c.textContent = "chairman";
        row.appendChild(c);
      }
      for (const m of ex.members) {
        if (m.answer === letter) {
          const c = document.createElement("span");
          c.className = "chip";
          c.textContent = m.model;
          row.appendChild(c);
        }
      }
      card.appendChild(row);
    });

    const all = document.createElement("details");
    all.className = "ex-all";
    const summary = document.createElement("summary");
    summary.textContent = "all " + ex.options.length + " options";
    all.appendChild(summary);
    const ul = document.createElement("ul");
    ex.options.forEach((text, i) => {
      const li = document.createElement("li");
      li.textContent = LETTERS[i] + ". " + text;
      ul.appendChild(li);
    });
    all.appendChild(ul);
    card.appendChild(all);

    const meta = document.createElement("p");
    meta.className = "ex-meta";
    meta.textContent = ex.item_id + " · " + ex.domain +
      " · Kendall's W " + (ex.w == null ? "–" : ex.w.toFixed(2)) +
      " · top-1 agreement " + fmtPct(ex.top1) +
      " · labeled " + ex.state;
    card.appendChild(meta);
    wrap.appendChild(card);
  }
})();

document.getElementById("footer").textContent =
  "Run directory: " + (CONFIG.run_dir || "") + " · results.jsonl is the source of truth; " +
  "this page is regenerated by benchmarks/make_report.py.";
</script>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--out", type=Path, default=None,
                        help="Output HTML path (default: <run_dir>/report.html)")
    args = parser.parse_args()

    records, config = load_run(args.run_dir)
    config["run_dir"] = str(args.run_dir)
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    benchmark_path = Path(config.get("benchmark") or "")
    if not benchmark_path.exists():
        benchmark_path = args.run_dir / benchmark_path.name
    examples = pick_examples(records, benchmark_path)

    html = (HTML_TEMPLATE
            .replace("__DATA__", json.dumps(slim(records)))
            .replace("__CONFIG__", json.dumps(config))
            .replace("__GENERATED__", json.dumps(generated))
            .replace("__EXAMPLES__", json.dumps(examples)))

    out = args.out or args.run_dir / "report.html"
    out.write_text(html)
    print(f"Report: {out}  ({len(records)} records)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
