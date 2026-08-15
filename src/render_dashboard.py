"""Render the single-file dashboard from the computed payload.

No build step, no external requests, no CDN. Charts are inline SVG drawn by
vanilla JS from an embedded JSON blob, so the file opens by double-clicking
with no network at all. Everything tunable lives in CONFIG at the top of the
generated HTML.
"""

from __future__ import annotations

import json

import build_dashboard
import sec_common as sc

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TICKER__ Nowcast Monitor</title>
<style>
:root {
  --bg: #0d1117; --panel: #161b22; --panel2: #1c2129; --line: #30363d;
  --text: #e6edf3; --muted: #8b949e; --dim: #6e7681;
  --accent: #58a6ff; --good: #3fb950; --warn: #d29922; --bad: #f85149;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  padding: 20px;
}
.wrap { max-width: 1180px; margin: 0 auto; }
header { border-bottom: 1px solid var(--line); padding-bottom: 14px; margin-bottom: 20px; }
h1 { margin: 0 0 4px; font-size: 21px; letter-spacing: -0.01em; }
h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.09em;
     color: var(--muted); margin: 0 0 12px; font-weight: 600; }
.sub { color: var(--muted); font-size: 13px; }
.badges { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.badge { font-size: 11.5px; padding: 3px 9px; border-radius: 20px;
         border: 1px solid var(--line); color: var(--muted); background: var(--panel); }
.badge.warn { border-color: #6b4d16; color: var(--warn); }
.badge.good { border-color: #1c4b26; color: var(--good); }
.grid { display: grid; gap: 16px; }
.cols2 { grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); }
.panel { background: var(--panel); border: 1px solid var(--line);
         border-radius: 10px; padding: 16px 18px; margin-bottom: 16px; }
.big { font-size: 42px; font-weight: 650; letter-spacing: -0.025em;
       font-family: var(--mono); line-height: 1.05; }
.band { color: var(--muted); font-family: var(--mono); font-size: 14px; margin-top: 4px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; color: var(--muted); font-weight: 600; padding: 6px 8px;
     border-bottom: 1px solid var(--line); font-size: 11.5px;
     text-transform: uppercase; letter-spacing: 0.05em; }
td { padding: 6px 8px; border-bottom: 1px solid #21262d; }
td.num, th.num { text-align: right; font-family: var(--mono); }
tr:last-child td { border-bottom: none; }
.tag { font-size: 11px; padding: 2px 7px; border-radius: 4px; font-family: var(--mono); }
.t-good { background: #12261a; color: var(--good); }
.t-warn { background: #2b2113; color: var(--warn); }
.t-bad  { background: #2d1618; color: var(--bad); }
.t-dim  { background: #1c2129; color: var(--muted); }
.note { color: var(--muted); font-size: 12.5px; margin-top: 10px; line-height: 1.5; }
.note strong { color: var(--text); font-weight: 600; }
.callout { border-left: 3px solid var(--accent); padding: 10px 0 10px 14px;
           background: var(--panel2); border-radius: 0 6px 6px 0; margin: 12px 0; }
.callout.bad { border-left-color: var(--bad); }
.kv { display: flex; justify-content: space-between; padding: 5px 0;
      border-bottom: 1px solid #21262d; font-size: 13px; }
.kv:last-child { border-bottom: none; }
.kv span:last-child { font-family: var(--mono); }
svg { display: block; width: 100%; height: auto; }
.legend { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 8px;
          font-size: 11.5px; color: var(--muted); }
.legend i { display: inline-block; width: 14px; height: 2px; margin-right: 5px;
            vertical-align: middle; }
footer { color: var(--dim); font-size: 12px; border-top: 1px solid var(--line);
         padding-top: 14px; margin-top: 8px; }
code { font-family: var(--mono); font-size: 12px; background: var(--panel2);
       padding: 1px 5px; border-radius: 3px; }
@media (max-width: 640px) { body { padding: 12px; } .big { font-size: 32px; } }
</style>
</head>
<body>
<div class="wrap" id="app"></div>

<script>
/* ===================================================================
   CONFIG -- everything ticker-specific lives here.
   Pointing this page at SNOW or MDB means changing this object and
   supplying a payload with the same shape. Nothing below reads a
   Datadog-specific field by name.
   =================================================================== */
const CONFIG = {
  ticker: "__TICKER__",
  headlineMethod: "guidance midpoint x (1 + trailing N-quarter mean beat)",
  // Divergence thresholds, in standard deviations of the signal's own
  // history at the same day-of-quarter. Conventional 1/2 sigma, NOT fitted:
  // fitting a threshold on 8 observations would repeat the error the
  // validation rejected.
  zThresholds: { leaning: 1.0, diverging: 2.0 },
  // A signal is shown as a headline input only if it beat the strongest
  // naive baseline out of sample. None currently qualify.
  requireBaselineBeatForHeadline: true,
  paceUnits: "millions of downloads, cumulative",
};

const DATA = __PAYLOAD__;

/* ------------------------------------------------------------------ utils */
const el = (h) => { const d = document.createElement("div"); d.innerHTML = h.trim(); return d.firstChild; };
const fmt = (v, d = 1) => v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (v, d = 1) => (v >= 0 ? "+" : "") + v.toFixed(d) + "%";
const app = document.getElementById("app");
function panel(title, inner) {
  return `<section class="panel"><h2>${title}</h2>${inner}</section>`;
}
function stateTag(state) {
  const cls = state === "diverging" ? "t-bad" : state === "leaning" ? "t-warn" : "t-good";
  return `<span class="tag ${cls}">${state}</span>`;
}

/* ------------------------------------------------------------------ header */
const M = DATA.meta, H = DATA.headline, IMP = DATA.imputation;
app.appendChild(el(`
<header>
  <h1>${M.ticker} &middot; ${M.live_quarter} nowcast monitor</h1>
  <div class="sub">${M.company} &middot; quarter ends ${M.quarter_end} &middot;
    reports ${M.expected_report} &middot; day ${M.days_elapsed} of ${M.days_in_quarter}</div>
  <div class="badges">
    <span class="badge">generated ${M.generated}</span>
    <span class="badge">signal data through ${M.data_through}</span>
    <span class="badge ${IMP.share_pct > 5 ? "warn" : ""}">
      ${IMP.share_pct}% of quarter-to-date observations imputed
      (${IMP.days} of ${IMP.elapsed} days with published data)</span>
    <span class="badge good">guidance ${H.guidance_verified} vs 8-K ${H.guidance_accession}</span>
  </div>
</header>`));

/* ---------------------------------------------------------------- headline */
const width = H.hi - H.lo;
app.appendChild(el(panel("Headline nowcast &mdash; Q3 2026 revenue", `
  <div class="grid cols2">
    <div>
      <div class="big">$${fmt(H.point)}m</div>
      <div class="band">95% band $${fmt(H.lo)}m &ndash; $${fmt(H.hi)}m &nbsp;(&plusmn;$${fmt(width / 2)}m)</div>
      <div class="note">
        <strong>Method:</strong> ${H.method}.<br>
        Guidance midpoint <code>$${fmt(H.guide_mid, 0)}m</code>
        (range $${fmt(H.guide_low, 0)}m&ndash;$${fmt(H.guide_high, 0)}m),
        trailing ${H.trailing_n}-quarter mean beat
        <code>${pct(H.trailing_beat_mean_pct, 2)}</code>
        (sd ${H.trailing_beat_sd_pp.toFixed(2)}pp).
      </div>
    </div>
    <div>
      <div class="kv"><span>Implied YoY growth</span><span>${pct(H.implied_yoy_pct)}</span></div>
      <div class="kv"><span>Implied QoQ growth</span><span>${pct(H.implied_qoq_pct)}</span></div>
      <div class="kv"><span>Guidance midpoint</span><span>$${fmt(H.guide_mid, 0)}m</span></div>
      <div class="kv"><span>Implied beat vs midpoint</span><span>${pct(H.trailing_beat_mean_pct, 2)}</span></div>
      <div class="kv"><span>Prior-year quarter</span><span>$${fmt(H.prior_year_rev)}m</span></div>
      <div class="kv"><span>Sell-side consensus</span><span style="color:var(--dim)">not sourced</span></div>
    </div>
  </div>
  ${(() => {
    // One shared axis. Both intervals sit on the SAME track at the same height,
    // so the eye compares horizontal position instead of reading two unrelated
    // objects stacked on top of each other.
    const W = 760, HH = 112, PADL = 22, PADR = 22;
    const AXIS = 76, TRACK_Y = 38, TRACK_H = 26;
    const lo = Math.min(H.guide_low, H.lo) - 22, hi = Math.max(H.guide_high, H.hi) + 22;
    const x = v => PADL + (v - lo) / (hi - lo) * (W - PADL - PADR);
    const step = 20;
    const ticks = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) ticks.push(v);
    return `<svg viewBox="0 0 ${W} ${HH}" width="100%" height="${HH}" style="margin:14px 0 2px"
      role="img" aria-label="Nowcast interval and guidance range on a shared revenue axis">
      <line x1="${PADL}" y1="${AXIS}" x2="${W-PADR}" y2="${AXIS}" stroke="var(--line)" stroke-width="1"/>
      ${ticks.map(v => `<line x1="${x(v)}" y1="${AXIS}" x2="${x(v)}" y2="${AXIS+5}" stroke="var(--line)"/>
        <text x="${x(v)}" y="${AXIS+17}" text-anchor="middle" font-size="9.5" fill="var(--dim)"
          font-family="var(--mono)">${fmt(v,0)}</text>`).join("")}
      <line x1="${PADL}" y1="${TRACK_Y + TRACK_H/2}" x2="${W-PADR}" y2="${TRACK_Y + TRACK_H/2}"
        stroke="var(--line)" stroke-dasharray="2 4" opacity="0.7"/>

      <rect x="${x(H.guide_low)}" y="${TRACK_Y}" width="${Math.max(3, x(H.guide_high)-x(H.guide_low))}"
        height="${TRACK_H}" rx="3" fill="var(--dim)" opacity="0.75"/>
      <text x="${x(H.guide_mid)}" y="${TRACK_Y-9}" text-anchor="middle" font-size="10"
        fill="var(--muted)" font-family="var(--mono)">guidance ${fmt(H.guide_low,0)}&ndash;${fmt(H.guide_high,0)}</text>

      <rect x="${x(H.lo)}" y="${TRACK_Y}" width="${x(H.hi)-x(H.lo)}" height="${TRACK_H}"
        rx="3" fill="var(--accent)" opacity="0.34"/>
      <line x1="${x(H.lo)}" y1="${TRACK_Y}" x2="${x(H.lo)}" y2="${TRACK_Y+TRACK_H}" stroke="var(--accent)" stroke-width="1.5"/>
      <line x1="${x(H.hi)}" y1="${TRACK_Y}" x2="${x(H.hi)}" y2="${TRACK_Y+TRACK_H}" stroke="var(--accent)" stroke-width="1.5"/>
      <text x="${x((H.lo+H.hi)/2)}" y="${TRACK_Y-9}" text-anchor="middle" font-size="10"
        fill="var(--accent)" font-family="var(--mono)">95% interval ${fmt(H.lo,0)}&ndash;${fmt(H.hi,0)}</text>

      <line x1="${x(H.point)}" y1="${TRACK_Y-3}" x2="${x(H.point)}" y2="${AXIS}"
        stroke="var(--text)" stroke-width="2"/>
      <circle cx="${x(H.point)}" cy="${TRACK_Y+TRACK_H/2}" r="4.5" fill="var(--text)"
        stroke="var(--panel)" stroke-width="1.5"/>
      <text x="${x(H.point)}" y="${AXIS+31}" text-anchor="middle" font-size="11.5" font-weight="700"
        fill="var(--text)" font-family="var(--mono)">$${fmt(H.point,1)}m</text>

      <line x1="${x(H.guide_high)}" y1="${TRACK_Y+TRACK_H/2}" x2="${x(H.lo)}" y2="${TRACK_Y+TRACK_H/2}"
        stroke="var(--warn)" stroke-width="1.2"/>
      <text x="${x((H.guide_high+H.lo)/2)}" y="${TRACK_Y+TRACK_H/2-6}" text-anchor="middle"
        font-size="9.5" fill="var(--warn)" font-family="var(--mono)">gap ${fmt(H.lo-H.guide_high,0)}m</text>
    </svg>
    <div class="note" style="margin-top:0">Both bars are on the same revenue axis.
      The 95% interval does <strong>not overlap the guidance range at any point</strong> —
      its floor sits $${fmt(H.lo-H.guide_high,0)}m above the top of guidance. That is what
      27 consecutive beats implies, and it is the most consequential assumption on
      this page.</div>`;
  })()}
  ${(() => {
    const B = DATA.beat_history, W = 760, HH = 108, PADL = 34, PADR = 10, TOP = 12, BOT = 26;
    const mx = Math.max(...B.map(b => b.beat_pct)) * 1.12;
    const bw = (W - PADL - PADR) / B.length;
    const y = v => TOP + (1 - v / mx) * (HH - TOP - BOT);
    const mean = H.trailing_beat_mean_pct;
    return `<div class="sub" style="margin:16px 0 4px">Beat vs guidance midpoint, last ${B.length} quarters</div>
    <svg viewBox="0 0 ${W} ${HH}" width="100%" height="${HH}" role="img"
      aria-label="Quarterly beat versus guidance midpoint">
      ${B.map((b, i) => {
        const recent = i >= B.length - H.trailing_n;
        return `<rect x="${PADL + i*bw + 2}" y="${y(b.beat_pct)}" width="${bw-4}"
          height="${Math.max(1, y(0) - y(b.beat_pct))}" rx="2"
          fill="${recent ? 'var(--accent)' : 'var(--dim)'}" opacity="${recent ? 0.9 : 0.5}"/>
        <text x="${PADL + i*bw + bw/2}" y="${y(b.beat_pct)-3}" text-anchor="middle"
          font-size="8" fill="var(--muted)" font-family="var(--mono)">${b.beat_pct.toFixed(1)}</text>`;
      }).join("")}
      <line x1="${PADL}" y1="${y(mean)}" x2="${W-PADR}" y2="${y(mean)}"
        stroke="var(--good)" stroke-width="1.5" stroke-dasharray="4 3"/>
      <rect x="${W-PADR-186}" y="1" width="186" height="14" rx="3" fill="var(--panel)" opacity="0.92"/>
      <line x1="${W-PADR-182}" y1="8" x2="${W-PADR-168}" y2="8" stroke="var(--good)"
        stroke-width="1.5" stroke-dasharray="4 3"/>
      <text x="${W-PADR-4}" y="11.5" text-anchor="end" font-size="9.5"
        fill="var(--good)" font-family="var(--mono)">trailing-${H.trailing_n} mean +${mean.toFixed(2)}%</text>
      <line x1="${PADL}" y1="${y(0)}" x2="${W-PADR}" y2="${y(0)}" stroke="var(--line)"/>
      ${B.map((b, i) => i % 3 === 0 ? `<text x="${PADL + i*bw + bw/2}" y="${HH-10}"
        text-anchor="middle" font-size="8" fill="var(--dim)"
        font-family="var(--mono)">${b.quarter}</text>` : "").join("")}
      <text x="4" y="${y(mx*0.9)}" font-size="8" fill="var(--dim)" font-family="var(--mono)">%</text>
    </svg>
    <div class="note" style="margin-top:0"><strong>Never negative, and flat since 2024.</strong>
      The blue bars are the ${H.trailing_n} quarters feeding the current estimate
      (sd ${H.trailing_beat_sd_pp.toFixed(2)}pp). That stability is what the &plusmn;$${fmt((H.hi-H.lo)/2,1)}m
      interval is made of — and the assumption that breaks first if guidance philosophy changes.</div>`;
  })()}
  <div class="callout">
    <strong>Why the headline is not built from the alternative data.</strong>
    No construction beat the strongest naive baseline out of sample &mdash; 0 of
    ${DATA.diagnostics.grid_cells} grid cells, and 0 again once features are
    orthogonalised against guidance (see Model diagnostics). The scope of that
    claim is narrow and deliberate: what was testable is the Node.js SDK channel,
    roughly a tenth of the observable install volume, while the core agent's
    channel publishes no history at all (see Observability). The signals below run
    as a <em>divergence monitor</em>: they do not set the number, they flag when
    the rule behind it is likely to break.
  </div>
  <div class="note">${H.consensus_note}
  The band reflects only the historical variance of the beat. It is
  <strong>conditional on the beat distribution remaining stationary</strong> &mdash;
  supported over the last 16 quarters (ADF p=0.007, KPSS p=0.100), mildly strained
  over the last 8 (Spearman &rho;=+0.69, p=0.058). It excludes guidance-philosophy
  changes, customer concentration events, and M&amp;A.</div>
`)));

/* ------------------------------------------------------- tracking ahead/behind */
const rows = DATA.divergence.map(d => `
  <tr>
    <td>${d.label}<div style="color:var(--dim);font-size:11px">${d.note}</div></td>
    <td class="num">${d.current.toFixed(3)}</td>
    <td class="num">${d.hist_mean.toFixed(3)}</td>
    <td class="num">${d.hist_sd.toFixed(3)}</td>
    <td class="num">${d.z >= 0 ? "+" : ""}${d.z.toFixed(2)}</td>
    <td>${stateTag(d.state)}</td>
  </tr>`).join("");
app.appendChild(el(panel("Tracking ahead / behind &mdash; divergence monitor", `
  ${(() => {
    const W = 760, HH = 124, PADL = 46, PADR = 46, MID = 68;
    const x = z => PADL + (Math.max(-3, Math.min(3, z)) + 3) / 6 * (W - PADL - PADR);
    const rows = DATA.divergence, cz = DATA.composite.z;
    return `<svg viewBox="0 0 ${W} ${HH}" width="100%" height="${HH}" role="img"
      aria-label="Divergence gauge from minus three to plus three sigma">
      <rect x="${x(-3)}" y="${MID-9}" width="${x(-1)-x(-3)}" height="18" fill="var(--bad)" opacity="0.18"/>
      <rect x="${x(-1)}" y="${MID-9}" width="${x(1)-x(-1)}" height="18" fill="var(--good)" opacity="0.18"/>
      <rect x="${x(1)}" y="${MID-9}" width="${x(3)-x(1)}" height="18" fill="var(--warn)" opacity="0.18"/>
      <line x1="${x(0)}" y1="${MID-13}" x2="${x(0)}" y2="${MID+13}" stroke="var(--line)"/>
      ${[-1,1].map(v => `<line x1="${x(v)}" y1="${MID-12}" x2="${x(v)}" y2="${MID+12}" stroke="var(--muted)" stroke-dasharray="2 2"/>`).join("")}
      <text x="${x(-2)}" y="${MID+31}" text-anchor="middle" font-size="9.5" fill="var(--bad)" font-family="var(--mono)">TRACKING BEHIND</text>
      <text x="${x(0)}" y="${MID+31}" text-anchor="middle" font-size="9.5" fill="var(--good)" font-family="var(--mono)">IN LINE</text>
      <text x="${x(2)}" y="${MID+31}" text-anchor="middle" font-size="9.5" fill="var(--warn)" font-family="var(--mono)">TRACKING AHEAD</text>
      ${[...rows].sort((a,b) => a.z - b.z).map((r, i) => {
        const isPlc = r.note.indexOf("control") >= 0;
        const col = isPlc ? "var(--muted)" : (Math.abs(r.z) >= 2 ? "var(--bad)" : Math.abs(r.z) >= 1 ? "var(--warn)" : "var(--good)");
        // Sorted by z, then staggered across three levels, so neighbouring dots
        // never share a label row -- three of the four cluster inside one sigma.
        const yy = MID - 18 - (i % 3) * 13;
        const short = r.label.replace(" (d30)", "").replace("Datadog ", "");
        return `<line x1="${x(r.z)}" y1="${yy+4}" x2="${x(r.z)}" y2="${MID-9}" stroke="${col}" stroke-width="1" opacity="0.45"/>
          <circle cx="${x(r.z)}" cy="${MID}" r="5" fill="${col}" stroke="var(--panel)" stroke-width="1.5"/>
          <text x="${x(r.z)}" y="${yy}" text-anchor="middle" font-size="9" fill="${col}" font-family="var(--mono)">${short} ${r.z >= 0 ? "+" : ""}${r.z.toFixed(2)}</text>`;
      }).join("")}
      <polygon points="${x(cz)-6},${MID+17} ${x(cz)+6},${MID+17} ${x(cz)},${MID+10}" fill="var(--text)"/>
      <text x="${x(cz)}" y="${MID+46}" text-anchor="middle" font-size="10.5" font-weight="700" fill="var(--text)" font-family="var(--mono)">COMPOSITE ${cz >= 0 ? "+" : ""}${cz.toFixed(2)}</text>
      <text x="${x(-3)}" y="${MID+4}" text-anchor="end" font-size="9" fill="var(--dim)" font-family="var(--mono)">-3&sigma;</text>
      <text x="${x(3)}" y="${MID+4}" text-anchor="start" font-size="9" fill="var(--dim)" font-family="var(--mono)">+3&sigma;</text>
    </svg>
    <div class="note" style="margin-top:0">The grey dot is the <strong>placebo</strong>,
      which cannot contain Datadog information. Compare it with the ecosystem-adjusted
      Datadog measure before reading anything into the absolute one &mdash; when the
      placebo leans as hard as the signal, the ecosystem is what is moving.</div>`;
  })()}
  <table>
    <thead><tr><th>Signal</th><th class="num">Current</th><th class="num">Hist mean</th>
    <th class="num">Hist sd</th><th class="num">z</th><th>State</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>
  <div class="note">
    <strong>How to read this.</strong> Each signal is z-scored against its own value
    at the <em>same day of quarter</em> across the prior ${H.trailing_n} quarters, so
    seasonality and quarter length are held fixed. Thresholds:
    |z| &lt; ${CONFIG.zThresholds.leaning} in line,
    ${CONFIG.zThresholds.leaning} &le; |z| &lt; ${CONFIG.zThresholds.diverging} leaning,
    |z| &ge; ${CONFIG.zThresholds.diverging} diverging. These are conventional
    1&sigma;/2&sigma; cut-offs, deliberately <strong>not fitted</strong> &mdash;
    calibrating a threshold on 8 observations would repeat the overfitting the
    validation just rejected.
    <br><br>
    <strong>What a flag means, and what it does not.</strong> "Diverging" means this
    quarter does not look like the last eight on that measure. It does
    <em>not</em> translate into revenue: the mapping from these signals to revenue
    failed out-of-sample validation. Note the current reading &mdash; the absolute
    Datadog measure is diverging while the ecosystem-adjusted measure is in line and
    the <em>placebo</em> sits at z=+0.93. That pattern says the ecosystem is running
    hot, not that Datadog is.
  </div>
`)));

/* --------------------------------------------- composite tracking indicator */
const C = DATA.composite;
const callNow = C.z >= C.ahead_threshold ? "tracking ahead"
              : C.z <= C.behind_threshold ? "tracking behind" : "in line";
const callCls = callNow === "in line" ? "t-good" : "t-warn";
app.appendChild(el(panel("How the signals combine &mdash; the tracking call", `
  <div class="row">
    <div>
      <div class="label">Composite tracking indicator, day ${M.days_elapsed} (${C.horizon} window)</div>
      <div class="big" style="font-size:38px">${C.z >= 0 ? "+" : ""}${C.z.toFixed(2)}<span class="unit">z</span></div>
      <div><span class="tag ${callCls}" style="font-size:14px">${callNow.toUpperCase()}</span></div>
    </div>
    <div class="kv">
      <div><span>Combines</span><b>${C.parts.join(" + ")}</b></div>
      <div><span>Weighting</span><b>equal</b></div>
      <div><span>Excluded</span><b>${C.excluded}</b></div>
      <div><span>Tracking ahead</span><b>z &ge; +${C.ahead_threshold.toFixed(1)}</b></div>
      <div><span>Tracking behind</span><b>z &le; ${C.behind_threshold.toFixed(1)}</b></div>
    </div>
  </div>
  <div class="note"><strong>Why these two, equally weighted.</strong>
    Both are drift-adjusted. <em>Datadog absolute</em> is excluded from the
    composite because it carries the ecosystem-wide inflation documented below &mdash;
    including it would make the indicator fire on registry activity rather than on
    Datadog. Weights are equal because nothing here survived validation, and fitting
    weights on ${DATA.diagnostics.grid_cells} cells that all failed would be exactly
    the error this project exists to warn about.</div>

  <div class="sub" style="margin:16px 0 6px">What "tracking ahead / behind" has actually meant</div>
  <div class="note" style="margin-top:0">A directional label is decoration until
    someone checks it. For every historical quarter the call is recomputed from
    prior quarters only, then compared with whether that quarter beat guidance by
    <em>more</em> than its own trailing 8-quarter mean beat.</div>
  <table><thead><tr><th>Quarter</th><th class="num">Composite z</th><th>Call</th>
    <th class="num">Beat</th><th class="num">Trailing mean</th><th>Outcome</th><th></th></tr></thead>
    <tbody>${C.examples.map(e => `<tr>
      <td>${e.quarter}</td>
      <td class="num">${e.z >= 0 ? "+" : ""}${e.z.toFixed(2)}</td>
      <td>${e.call}</td>
      <td class="num">${e.beat_pct.toFixed(2)}%</td>
      <td class="num">${e.trailing_pct.toFixed(2)}%</td>
      <td>${e.outcome}</td>
      <td>${e.correct === null ? "" : e.correct
            ? '<span class="tag t-good">correct</span>'
            : '<span class="tag t-bad">wrong</span>'}</td></tr>`).join("")}
    </tbody></table>

  <table style="margin-top:10px"><thead><tr><th>Horizon</th>
    <th class="num">Directional calls</th><th class="num">Correct</th>
    <th class="num">Hit rate</th><th class="num">p vs coin flip</th></tr></thead>
    <tbody>${C.backtest.map(b => `<tr><td>${b.horizon}</td>
      <td class="num">${b.calls}</td><td class="num">${b.correct}</td>
      <td class="num">${(b.hit_rate * 100).toFixed(0)}%</td>
      <td class="num">${b.p.toFixed(3)}</td></tr>`).join("")}</tbody></table>
  <div class="note" style="margin-top:6px"><strong>70% at ten calls is not a
    result.</strong> The binomial p-value against a coin flip is 0.34. The
    indicator is a monitoring aid with a measured and unimpressive reliability,
    stated here rather than hidden &mdash; which is the only defensible way to put a
    directional call on an analyst's screen. It does <em>not</em> feed the headline
    number, and the signals do not combine into a revenue estimate, because no
    construction beat a naive baseline out of sample.</div>
`)));

/* ----------------------------------------------------- observability panel */
app.appendChild(el(panel("Observability &mdash; what the signal can and cannot see", `
  <table>
    <thead><tr><th>Distribution channel</th><th>Carries</th>
      <th class="num">Cumulative</th><th>History</th><th>Testable</th></tr></thead>
    <tbody>${DATA.coverage.map(c => `<tr>
      <td>${c.channel}</td><td style="color:var(--muted);font-size:12px">${c.carries}</td>
      <td class="num">${c.cumulative ? (c.cumulative / 1e9).toFixed(2) + "bn" : "&mdash;"}</td>
      <td style="font-size:12px">${c.history}</td>
      <td>${c.in_model.startsWith("yes")
            ? '<span class="tag t-good">yes</span>'
            : c.in_model === "appendix"
              ? '<span class="tag t-dim">appendix</span>'
              : '<span class="tag t-bad">no</span>'}</td></tr>`).join("")}
    </tbody>
  </table>
  <div class="note"><strong>This is the project's binding constraint.</strong>
    Datadog's core billable unit is the Go agent, shipped through Docker Hub,
    APT/YUM, Helm and cloud marketplaces. That channel carries about
    <strong>10x</strong> the volume of the npm channel this dashboard measures, and
    Docker Hub exposes only a lifetime cumulative counter &mdash; no time series, no
    per-tag split &mdash; so it cannot be backfilled for the 27 quarters already
    elapsed. A daily snapshot of that counter yields a usable delta series
    <em>from the day collection starts</em>, which is the correct forward fix and
    the single highest-value addition to this pipeline.</div>
`)));

/* ------------------------------------------------------------- pace chart */
(function () {
  const W = 1000, Hh = 380, P = { l: 56, r: 130, t: 16, b: 34 };
  const quarters = Object.keys(DATA.pace);
  const live = M.live_quarter;
  let maxY = 0, maxX = 0;
  quarters.forEach(q => {
    const s = DATA.pace[q];
    maxY = Math.max(maxY, ...s.cum); maxX = Math.max(maxX, ...s.day);
  });
  const x = d => P.l + (d / maxX) * (W - P.l - P.r);
  const y = v => Hh - P.b - (v / maxY) * (Hh - P.t - P.b);
  let paths = "", labels = "", legend = "";
  quarters.forEach((q, i) => {
    const s = DATA.pace[q];
    const isLive = q === live;
    const shade = 20 + Math.round((i / quarters.length) * 45);
    const col = isLive ? "#58a6ff" : `hsl(215 12% ${shade + 22}%)`;
    const w = isLive ? 2.6 : 1.2;
    const pts = s.day.map((d, k) => `${x(d).toFixed(1)},${y(s.cum[k]).toFixed(1)}`).join(" ");
    paths += `<polyline points="${pts}" fill="none" stroke="${col}" stroke-width="${w}"/>`;
    const lastD = s.day[s.day.length - 1], lastV = s.cum[s.cum.length - 1];
    if (isLive || i % 2 === 0) {
      labels += `<text x="${x(lastD) + 6}" y="${y(lastV) + 3.5}" fill="${col}"
        font-size="11" font-family="ui-monospace,monospace">${q}</text>`;
    }
    if (isLive) legend += `<span><i style="background:${col}"></i>${q} (live)</span>`;
  });
  let gridlines = "";
  for (let i = 0; i <= 4; i++) {
    const v = (maxY / 4) * i;
    gridlines += `<line x1="${P.l}" y1="${y(v)}" x2="${W - P.r}" y2="${y(v)}"
      stroke="#21262d" stroke-width="1"/>
      <text x="${P.l - 8}" y="${y(v) + 4}" fill="#6e7681" font-size="11"
      text-anchor="end" font-family="ui-monospace,monospace">${v.toFixed(0)}</text>`;
  }
  let xticks = "";
  [1, 15, 30, 45, 60, 75, 92].forEach(d => {
    if (d > maxX) return;
    xticks += `<text x="${x(d)}" y="${Hh - 12}" fill="#6e7681" font-size="11"
      text-anchor="middle" font-family="ui-monospace,monospace">d${d}</text>`;
  });
  const today = x(M.days_elapsed - 1);
  app.appendChild(el(panel("Quarter-to-date pace &mdash; cumulative Datadog basket downloads", `
    <svg viewBox="0 0 ${W} ${Hh}" role="img" aria-label="cumulative downloads by day of quarter">
      ${gridlines}${xticks}
      <line x1="${today}" y1="${P.t}" x2="${today}" y2="${Hh - P.b}"
        stroke="#d29922" stroke-width="1" stroke-dasharray="3 3"/>
      <text x="${today + 5}" y="${P.t + 12}" fill="#d29922" font-size="11"
        font-family="ui-monospace,monospace">day ${M.days_elapsed}</text>
      ${paths}${labels}
    </svg>
    <div class="legend">${legend}
      <span><i style="background:hsl(215 12% 50%)"></i>prior quarters</span>
      <span><i style="background:#d29922"></i>today</span>
      <span>${CONFIG.paceUnits}</span></div>
    <div class="note">Constant-composition basket (<code>dd-trace</code> +
      <code>datadog-metrics</code>) &mdash; packages that did not exist at the start
      of the sample are excluded, because a package entering the basket creates a
      permanent artificial jump. Outage days are filled with a
      <strong>backward-only</strong> estimate (same weekday, prior 42 days), so every
      point on this chart was computable on the day it sits.</div>
  `)));
})();

/* ------------------------------------------------ imputation treatment spread */
const tr = DATA.treatments.map(t => `
  <tr><td>${t.name}</td>
    <td class="num">${t.dd_rel_plc.toFixed(4)}</td>
    <td class="num">${t.dd_rel.toFixed(4)}</td>
    <td class="num">${t.dd_abs.toFixed(4)}</td></tr>`).join("");
app.appendChild(el(panel("Outage-treatment sensitivity", `
  <table>
    <thead><tr><th>Treatment</th><th class="num">vs ecosystem</th>
    <th class="num">vs competitors</th><th class="num">absolute</th></tr></thead>
    <tbody>${tr}</tbody>
  </table>
  <div class="note">The npm API returned registry-wide zeros on
    <strong>${IMP.days} of the ${IMP.elapsed}</strong> days of published data this quarter
    (${IMP.share_pct}%). All three treatments are shown because the choice is a real
    source of uncertainty: the causal-imputed row is the point estimate, dropped-and-rescaled
    and raw-with-zeros bound it. The relative constructions are an order of magnitude
    less sensitive to the treatment than the absolute one &mdash; an outage suppresses
    every basket at once, so it largely cancels in a difference.</div>
`)));

/* ------------------------------------------------------------- risk flags */
const flags = [
  { name: "Ecosystem-wide download inflation", state: "diverging",
    detail: "Control and placebo baskets grew +102% / +184% YoY in 2026. Absolute Datadog download growth is not Datadog-specific." },
  { name: "Download-to-revenue decoupling", state: "diverging",
    detail: `Downloads per $m of revenue rose from ${DATA.decoupling.first4.toLocaleString()} to ${DATA.decoupling.last4.toLocaleString()} (Spearman &rho;=${DATA.decoupling.rho}, p${DATA.decoupling.p}). Normalising by disclosed $100k+ customers: revenue per customer +${DATA.decoupling.rev_per_cust_pct}% but downloads per customer +${DATA.decoupling.dl_per_cust_pct}% &mdash; cross-sell and tiering are real but explain a minority of the gap.` },
  { name: "Hyperscaler divergence", state: "leaning",
    detail: "AI-capex-driven cloud growth (Google Cloud +82%, AWS +37% in 2026Q2) correlates weakly with the application-monitoring workloads DDOG bills for." },
  { name: "Beat distribution drift", state: "leaning",
    detail: "Trailing-8 beat shows a mild widening tendency (Spearman &rho;=+0.69, p=0.058), not significant but not nothing. Trend-extrapolated call would be $1,195m vs $1,188m flat." },
  { name: "Model residual drift", state: "in line",
    detail: "Headline-rule residuals turned from -1.96pp (pre-2025) to +0.53pp (2025 onward); the 2026Q2 residual was +0.18pp despite the largest acceleration in the sample. Guidance absorbs the regime change." },
  { name: "Signal-set validity", state: "diverging",
    detail: `0 of ${DATA.diagnostics.grid_cells} alternative-data cells beat the strongest naive baseline. Treat every signal on this page as monitoring, not forecasting.` },
];
app.appendChild(el(panel("Risk flags", `
  <table><tbody>${flags.map(f => `
    <tr><td style="width:34%">${f.name}</td><td>${stateTag(f.state)}</td>
    <td style="color:var(--muted);font-size:12.5px">${f.detail}</td></tr>`).join("")}
  </tbody></table>
`)));

/* ------------------------------------------------------- model diagnostics */
(function () {
  const D = DATA.diagnostics;
  const byTarget = {};
  D.grid.forEach(g => { (byTarget[g.target] = byTarget[g.target] || []).push(g); });
  // Heatmap rather than a table of numbers: the point of this panel is that the
  // whole grid is red, and a reader should get that in one glance rather than by
  // scanning 24 cells. Numbers stay on the tiles so nothing is lost.
  const hCol = r => r < 1.0 ? "var(--good)" : r < 1.3 ? "var(--warn)" : "var(--bad)";
  const hOp  = r => r < 1.0 ? 0.85 : r < 1.3 ? 0.45 : Math.min(0.88, 0.34 + (r - 1.3) * 0.34);
  let gridHtml = "";
  Object.keys(byTarget).forEach(tg => {
    const cands = [...new Set(byTarget[tg].map(g => g.candidate))];
    const wins  = [...new Set(byTarget[tg].map(g => g.window))];
    const CW = 88, CH = 38, LEFT = 132, TOPH = 22;
    const W = LEFT + CW * wins.length + 6, HT = TOPH + CH * cands.length + 4;
    const tiles = cands.map((c, i) =>
      `<text x="${LEFT - 10}" y="${TOPH + i*CH + CH/2 + 4}" text-anchor="end" font-size="10.5"
         fill="var(--muted)" font-family="var(--mono)">${c}</text>` +
      wins.map((w, j) => {
        const cell = byTarget[tg].find(g => g.candidate === c && g.window === w);
        if (!cell) return "";
        return `<rect x="${LEFT + j*CW + 3}" y="${TOPH + i*CH + 3}" width="${CW-6}" height="${CH-6}"
            rx="3" fill="${hCol(cell.ratio)}" opacity="${hOp(cell.ratio)}"/>
          <text x="${LEFT + j*CW + CW/2}" y="${TOPH + i*CH + CH/2 + 4}" text-anchor="middle"
            font-size="11.5" font-weight="700" fill="#0d1117"
            font-family="var(--mono)">${cell.ratio.toFixed(3)}</text>`;
      }).join("")).join("");
    gridHtml += `<div style="margin-bottom:12px"><div class="sub" style="margin-bottom:4px">
      target: <code>${tg}</code> &mdash; RMSE ratio vs strongest baseline (&lt;1 would beat it)</div>
      <svg viewBox="0 0 ${W} ${HT}" width="100%" style="max-width:${W}px" role="img"
        aria-label="Heatmap of RMSE ratios for ${tg}; no cell is below one">
        ${wins.map((w, j) => `<text x="${LEFT + j*CW + CW/2}" y="15" text-anchor="middle"
          font-size="10.5" fill="var(--muted)" font-family="var(--mono)">${w}</text>`).join("")}
        ${tiles}
      </svg></div>`;
  });
  gridHtml += `<div class="note" style="margin-top:0">Green would be a win (&lt;1.0).
    <strong>There is no green.</strong> Amber is 1.0&ndash;1.3, red is worse, and the
    deeper the red the further from parity.</div>`;

  const bl = DATA.baselines.map(b => `<tr><td>${b.target}</td><td>${b.baseline}</td>
    <td class="num">${b.rmse.toFixed(4)}</td><td class="num">${b.mape.toFixed(2)}</td>
    <td class="num">${b.baseline === "random walk" ? "n/a" : b.hit.toFixed(3)}</td></tr>`).join("");

  const hy = D.hyperscaler.map(h => `<tr><td>${h.target}</td><td>${h.feature}
    <span class="tag ${h.role === "control" ? "t-dim" : "t-warn"}">${h.role}</span></td>
    <td class="num">${h.ratio.toFixed(3)}</td>
    <td class="num">[${h.ci[0].toFixed(2)}, ${h.ci[1].toFixed(2)}]</td>
    <td class="num">${h.dm_p.toFixed(3)}</td></tr>`).join("");

  app.appendChild(el(panel("Model diagnostics &mdash; how much to trust the headline", `
    <div class="callout bad"><strong>${D.cells_beating_best} of ${D.grid_cells}</strong>
      alternative-data cells beat the strongest naive baseline. Best cell:
      ${D.best_cell_ratio}. Against the weaker AR(1) benchmark
      ${D.cells_below_09_vs_ar1} of ${D.grid_cells} cells scored below 0.9 &mdash;
      a permutation null produces ${D.perm_mean_vs_ar1} such cells on average
      (p=0.002), so the features do carry information AR(1) lacks. That information
      is drift, which a correctly specified naive baseline already supplies:
      against the strongest baseline the same null produces
      ${D.perm_mean_vs_best} cells and the observed count is ${D.cells_beating_best}.</div>
    ${gridHtml}
    <div class="sub" style="margin:16px 0 6px">Baselines, expanding walk-forward, no alternative data</div>
    <table><thead><tr><th>Target</th><th>Baseline</th><th class="num">RMSE</th>
      <th class="num">MAPE %</th><th class="num">Hit</th></tr></thead><tbody>${bl}</tbody></table>
    <div class="sub" style="margin:16px 0 6px">Guidance-orthogonalised features &mdash; incremental content over guidance</div>
    <div class="note" style="margin-top:0">Re-running every cell with the feature
      residualised against guidance-implied growth (train-only coefficients), which
      is how a quantamental desk would use it: predict the surprise, not the level.
      Result: <strong>${D.cells_beating_best_orth} of ${D.grid_cells}</strong> cells
      beat the baseline, best ${D.best_cell_ratio_orth}. Stripping out what guidance
      already implies leaves <em>less</em>, not more.</div>
    <div class="sub" style="margin:16px 0 6px">Other target metrics from the brief</div>
    <table><thead><tr><th>Target</th><th class="num">n OOS</th>
      <th class="num">Cells beating baseline</th><th class="num">Best cell</th></tr></thead>
      <tbody>${DATA.extended.map(e => `<tr><td>${e.target}</td>
        <td class="num">${e.n_oos}</td>
        <td class="num">${e.beating} of ${e.cells}</td>
        <td class="num">${e.best.toFixed(3)}</td></tr>`).join("")}</tbody></table>
    <div class="note" style="margin-top:6px">Downloads are an unweighted count while
      revenue is dollar-weighted, so a count-type target should match better. It does:
      against $100k+ customer growth the best cell is <strong>${(DATA.extended.find(e => e.target === "cust_yoy") || {best:0}).best.toFixed(3)}</strong>, the
      closest any signal came to a baseline here, versus ${DATA.diagnostics.best_cell_ratio.toFixed(3)} against revenue growth.
      Still a loss, at n=11. RPO has insufficient history; NRR is not disclosed as a
      number in the 8-K exhibits and is excluded rather than approximated.</div>
    <div class="sub" style="margin:16px 0 6px">Unstructured signal &mdash; management tone, and its in-document placebo</div>
    <table><thead><tr><th>Text measured</th>
      <th class="num">corr with next beat</th><th class="num">Best cell</th></tr></thead>
      <tbody>
        <tr><td>management-authored body</td>
          <td class="num">${DATA.tone.mgmt_corr >= 0 ? "+" : ""}${DATA.tone.mgmt_corr.toFixed(3)}</td>
          <td class="num">${DATA.tone.mgmt_best.toFixed(3)}</td></tr>
        <tr><td><strong>counsel's forward-looking-statements boilerplate</strong></td>
          <td class="num"><strong>${DATA.tone.boilerplate_corr.toFixed(3)}</strong></td>
          <td class="num"><strong>${DATA.tone.boilerplate_best.toFixed(3)}</strong></td></tr>
      </tbody></table>
    <div class="note" style="margin-top:6px">The 8-K press release is the one
      qualitative source that is cleanly backfillable &mdash; free, official, and
      timestamped at the guidance-issuance moment. <strong>The legal disclaimer
      beats management's own words on every comparison</strong>, and against AR(1)
      it is "significant" (CI [${DATA.tone.plc_ci_lo.toFixed(3)}, ${DATA.tone.plc_ci_hi.toFixed(3)}], DM p=${DATA.tone.plc_dm_p.toFixed(3)}) &mdash; from text written
      to convey no information. Boilerplate drifts as counsel updates the template,
      so it proxies time. Unstructured features are <em>more</em> exposed to
      spurious trend-fitting than structured ones, so in an LLM extraction pipeline
      the control discipline matters more than the extraction quality.</div>
    <div class="sub" style="margin:16px 0 6px">Statistical power &mdash; what this sample could have detected</div>
    <table><thead><tr><th>Target</th><th class="num">n</th>
      <th class="num">detect r=0.95</th><th class="num">r=0.90</th>
      <th class="num">r=0.80</th></tr></thead>
      <tbody>${DATA.power.map(p => `<tr><td>${p.target}</td><td class="num">${p.n}</td>
        <td class="num">${p.p95}</td><td class="num">${p.p90}</td>
        <td class="num">${p.p80}</td></tr>`).join("")}</tbody></table>
    <div class="note" style="margin-top:6px"><strong>A genuine 5&ndash;10% edge would
      have gone undetected roughly 85&ndash;90% of the time.</strong> "0 of 24"
      therefore <em>bounds</em> the effect size rather than showing it is zero. What
      is <em>not</em> a power problem: the observed cells sit at ratios of 1.05 to
      2.65 &mdash; consistent, large degradation on the wrong side of parity.</div>
    <div class="sub" style="margin:16px 0 6px">Signal 2 &mdash; hyperscaler cloud growth, identical pipeline</div>
    <div class="note" style="margin-top:0">Scored on revenue growth against the same
      strongest baseline the headline uses. Matched non-cloud controls come from the
      <em>same filing</em>, so issuer, quarter and extraction method are held fixed.</div>
    <table><thead><tr><th>Series</th><th>Role</th><th class="num">n OOS</th>
      <th class="num">Ratio</th><th class="num">Boot 95% CI</th>
      <th class="num">DM p</th><th class="num">Hit</th></tr></thead>
      <tbody>${(DATA.diagnostics.hyperscaler_rev || []).map(h => `<tr>
        <td>${h.role === "control" ? "<em>" + h.feature + "</em>" : "<strong>" + h.feature + "</strong>"}</td>
        <td>${h.role}</td><td class="num">${h.n_oos}</td>
        <td class="num ${h.ratio < 1 ? "good" : "bad"}">${h.ratio.toFixed(3)}</td>
        <td class="num">[${h.ci[0].toFixed(2)}, ${h.ci[1].toFixed(2)}]</td>
        <td class="num">${h.dm_p.toFixed(3)}</td>
        <td class="num">${(h.hit * 100).toFixed(0)}%</td></tr>`).join("")}</tbody></table>
    <div class="note" style="margin-top:6px"><strong>An 84.6% directional hit rate with
      over 3&times; the baseline error is the trap.</strong> Intelligent Cloud is
      significantly <em>worse</em> than the baseline &mdash; its CI excludes 1.0 on the
      wrong side &mdash; and its matched control from the same filing fails too. AWS has
      only 4 out-of-sample points and is reported as untestable rather than as the one
      cell that nearly worked.</div>
    <table><thead><tr><th>Target</th><th>Feature</th><th class="num">Ratio</th>
      <th class="num">Boot 95% CI</th><th class="num">DM p</th></tr></thead><tbody>${hy}</tbody></table>
    <div class="note">Intelligent Cloud growth is <strong>significantly worse</strong> than
      the naive baseline &mdash; the confidence interval excludes 1.0 on the wrong side.
      It does achieve an 0.846 directional hit rate on revenue growth while carrying
      ~3x the baseline error, which is a clean illustration of why hit rate alone is a
      poor metric: right direction, badly wrong magnitude.</div>
  `)));
})();

/* --------------------------------------------------------- update cadence */
app.appendChild(el(panel("Update cadence", `
  <table><thead><tr><th>Signal</th><th>Frequency</th><th>Latency</th><th>Role</th></tr></thead>
  <tbody>${DATA.cadence.map(c => `<tr><td>${c.signal}</td><td>${c.freq}</td>
    <td>${c.latency}</td><td>${c.role === "HEADLINE INPUT"
      ? `<span class="tag t-good">${c.role}</span>` : c.role}</td></tr>`).join("")}
  </tbody></table>
`)));

/* ------------------------------------------------------------- templating */
app.appendChild(el(panel("Pointing this at another ticker", `
  <div class="note">
  Everything ticker-specific is in the <code>CONFIG</code> object at the top of this
  file plus the <code>DATA</code> payload. Repointing at SNOW or MDB requires:
  (1) the CIK and the XBRL revenue tag &mdash; the SEC fetcher is generic;
  (2) a signal basket, its substitute control basket, and an economically unrelated
  placebo basket &mdash; the constant-composition rule and the outage detector apply
  unchanged; (3) the guidance extractor re-pointed at that issuer's 8-K outlook
  wording. The as-of vintage layer, the baseline set, the walk-forward, the
  permutation null and the placebo pipeline are ticker-agnostic and need no changes.
  <br><br>
  The part that does <em>not</em> transfer is the conclusion. This dashboard shows a
  headline built from guidance because that is what survived validation for
  ${CONFIG.ticker}. For a company that guides less reliably, the same pipeline could
  well promote a different input &mdash; which is the point of running the baselines
  and the placebo before choosing.</div>
`)));

app.appendChild(el(`<footer>
  Sources: SEC EDGAR XBRL company facts and Item 2.02 8-K exhibits; npm registry
  downloads API; pypistats.org. All figures trace to a cached raw response or a
  cited filing accession number. Guidance figures independently re-parsed from the
  primary document (${H.guidance_verified}). No material non-public information.
  Generated ${M.generated} from commit-tracked code; every number on this page is
  reproducible with <code>python src/build_dashboard.py</code>.
</footer>`));
</script>
</body>
</html>
"""


def main() -> None:
    payload = build_dashboard.main()
    html = TEMPLATE.replace("__PAYLOAD__", json.dumps(payload)).replace(
        "__TICKER__", payload["meta"]["ticker"]
    )
    out = sc.REPO / "dashboard" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html)
    print(f"Wrote {out.relative_to(sc.REPO)}  ({out.stat().st_size / 1024:.0f} KB)")
    print("Single file, no external requests, opens by double-clicking.")


if __name__ == "__main__":
    main()
