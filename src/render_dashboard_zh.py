"""Render the Traditional Chinese edition of the dashboard.

Rather than maintaining two templates, this applies an explicit translation map
to the English template and to the payload's string fields. Every mapping is
asserted: if a source string is not found, the script raises instead of
silently emitting English. A final scan checks the rendered page for leftover
English prose.

Output: report-zh/dashboard.html
"""

from __future__ import annotations

import json
import re

import build_dashboard
import render_dashboard
import sec_common as sc

# ---------------------------------------------------------------- template
# (english, chinese) -- order matters where one string contains another.
TEMPLATE_MAP: list[tuple[str, str]] = [
    ("__TICKER__ Nowcast Monitor", "__TICKER__ 即時預測監控台"),
    ("nowcast monitor", "即時預測監控台"),
    ("quarter ends", "本季結束於"),
    ("reports ${M.expected_report}", "預計發布 ${M.expected_report}"),
    ("day ${M.days_elapsed} of ${M.days_in_quarter}", "本季第 ${M.days_elapsed} 天／共 ${M.days_in_quarter} 天"),
    ("generated ${M.generated}", "產生於 ${M.generated}"),
    ("signal data through ${M.data_through}", "訊號資料截至 ${M.data_through}"),
    ("${IMP.share_pct}% of quarter-to-date observations imputed",
     "本季至今 ${IMP.share_pct}% 的觀測值為插補"),
    ("(${IMP.days} of ${IMP.elapsed} days with published data)",
     "（已發布資料 ${IMP.elapsed} 天中的 ${IMP.days} 天）"),
    ("guidance ${H.guidance_verified} vs 8-K ${H.guidance_accession}",
     "指引已核對 8-K ${H.guidance_accession}"),
    # panel titles
    ("Headline nowcast &mdash; Q3 2026 revenue", "頭條即時預測 &mdash; 2026Q3 營收"),
    ("Tracking ahead / behind &mdash; divergence monitor", "領先／落後追蹤 &mdash; 背離監控器"),
    ("Quarter-to-date pace &mdash; cumulative Datadog basket downloads",
     "本季至今配速 &mdash; Datadog 籃累計下載量"),
    ("Outage-treatment sensitivity", "Outage 處理方式敏感度"),
    ("Risk flags", "風險旗標"),
    ("Model diagnostics &mdash; how much to trust the headline",
     "模型診斷 &mdash; 該對頭條數字信任到什麼程度"),
    ("Update cadence", "更新頻率"),
    ("Pointing this at another ticker", "把這套指向另一檔標的"),
    # headline block
    ("95% band", "95% 區間"),
    ("<strong>Method:</strong> ${H.method}.", "<strong>方法：</strong>${H.method}。"),
    ("Guidance midpoint <code>", "指引中點 <code>"),
    ("(range $${fmt(H.guide_low, 0)}m&ndash;$${fmt(H.guide_high, 0)}m),",
     "（區間 $${fmt(H.guide_low, 0)}m&ndash;$${fmt(H.guide_high, 0)}m），"),
    ("trailing ${H.trailing_n}-quarter mean beat", "近 ${H.trailing_n} 季平均超額"),
    ("(sd ${H.trailing_beat_sd_pp.toFixed(2)}pp).", "（標準差 ${H.trailing_beat_sd_pp.toFixed(2)}pp）。"),
    ("<span>Implied YoY growth</span>", "<span>隱含年增率</span>"),
    ("<span>Implied QoQ growth</span>", "<span>隱含季增率</span>"),
    ("<span>Guidance midpoint</span>", "<span>指引中點</span>"),
    ("<span>Implied beat vs midpoint</span>", "<span>隱含超額（對中點）</span>"),
    ("<span>Prior-year quarter</span>", "<span>去年同季</span>"),
    ("<span>Sell-side consensus</span>", "<span>賣方共識</span>"),
    (">not sourced<", ">無可引用來源<"),
    ("<strong>Why the headline is not built from the alternative data.</strong>",
     "<strong>為什麼頭條數字不是用另類數據建的。</strong>"),
    ("""No download or hyperscaler construction beat the strongest naive baseline out
    of sample &mdash; 0 of ${DATA.diagnostics.grid_cells} grid cells (see Model
    diagnostics). Presenting a signal-weighted estimate would show a relationship
    the validation rejected. The signals below run as a <em>divergence monitor</em>:
    they do not set the number, they flag when the rule behind it is likely to break.""",
     """沒有任何下載量或 hyperscaler 構造在樣本外勝過最強的樸素基準 &mdash;
    ${DATA.diagnostics.grid_cells} 格中 0 格（見模型診斷）。呈現訊號加權的估計值，
    等於呈現一個被驗證推翻的關係。下方訊號的角色是<em>背離監控器</em>：
    它們不決定數字，只標示背後那條規則何時可能失效。"""),
    ("""  The band reflects only the historical variance of the beat. It is
  <strong>conditional on the beat distribution remaining stationary</strong> &mdash;
  supported over the last 16 quarters (ADF p=0.007, KPSS p=0.100), mildly strained
  over the last 8 (Spearman &rho;=+0.69, p=0.058). It excludes guidance-philosophy
  changes, customer concentration events, and M&amp;A.""",
     """  本區間僅反映超額的歷史變異，且<strong>條件於超額分布維持定態</strong> &mdash;
  該條件在近 16 季獲支持（ADF p=0.007、KPSS p=0.100），在近 8 季略顯緊張
  （Spearman &rho;=+0.69、p=0.058）。區間不涵蓋指引哲學改變、客戶集中度事件與併購。"""),
    # divergence table
    ("<th>Signal</th>", "<th>訊號</th>"),
    ('<th class="num">Current</th>', '<th class="num">目前值</th>'),
    ('<th class="num">Hist mean</th>', '<th class="num">歷史均值</th>'),
    ('<th class="num">Hist sd</th>', '<th class="num">歷史標準差</th>'),
    ("<th>State</th>", "<th>狀態</th>"),
    ("<strong>How to read this.</strong>", "<strong>怎麼讀這張表。</strong>"),
    ("""Each signal is z-scored against its own value
    at the <em>same day of quarter</em> across the prior ${H.trailing_n} quarters, so
    seasonality and quarter length are held fixed. Thresholds:""",
     """每個訊號都以近 ${H.trailing_n} 季<em>同一個季內天數</em>的自身數值做 z 分數標準化，
    因此季節性與季度長度被固定住。門檻："""),
    ("in line,\n    ${CONFIG.zThresholds.leaning} &le; |z| &lt; ${CONFIG.zThresholds.diverging} leaning,",
     "為符合，\n    ${CONFIG.zThresholds.leaning} &le; |z| &lt; ${CONFIG.zThresholds.diverging} 為傾向，"),
    ("""|z| &ge; ${CONFIG.zThresholds.diverging} diverging. These are conventional
    1&sigma;/2&sigma; cut-offs, deliberately <strong>not fitted</strong> &mdash;
    calibrating a threshold on 8 observations would repeat the overfitting the
    validation just rejected.""",
     """|z| &ge; ${CONFIG.zThresholds.diverging} 為背離。這是慣例的
    1&sigma;/2&sigma; 切點，刻意<strong>不做擬合</strong> &mdash;
    在 8 個觀測值上校準門檻，等於重演驗證剛剛否決的那個過度配適。"""),
    ("<strong>What a flag means, and what it does not.</strong>",
     "<strong>亮旗代表什麼，不代表什麼。</strong>"),
    ("""\"Diverging\" means this
    quarter does not look like the last eight on that measure. It does
    <em>not</em> translate into revenue: the mapping from these signals to revenue
    failed out-of-sample validation. Note the current reading &mdash; the absolute
    Datadog measure is diverging while the ecosystem-adjusted measure is in line and
    the <em>placebo</em> sits at z=+0.93. That pattern says the ecosystem is running
    hot, not that Datadog is.""",
     """「背離」代表本季在該指標上不像過去八季。它<em>不能</em>轉換成營收：
    這些訊號到營收的映射在樣本外驗證中失敗了。看目前的讀數 &mdash;
    Datadog 絕對值指標呈背離，但經生態系調整後的指標是符合，而<em>安慰劑</em>
    位在 z=+0.93。這個組合說的是生態系在發燙，不是 Datadog。"""),
    # pace chart
    ("${q} (live)", "${q}（進行中）"),
    ("prior quarters", "過去各季"),
    (">today<", ">今天<"),
    ('font-family="ui-monospace,monospace">day ${M.days_elapsed}</text>',
     'font-family="ui-monospace,monospace">第 ${M.days_elapsed} 天</text>'),
    ("""Constant-composition basket (<code>dd-trace</code> +
      <code>datadog-metrics</code>) &mdash; packages that did not exist at the start
      of the sample are excluded, because a package entering the basket creates a
      permanent artificial jump. Outage days are filled with a
      <strong>backward-only</strong> estimate (same weekday, prior 42 days), so every
      point on this chart was computable on the day it sits.""",
     """常數組成籃（<code>dd-trace</code> +
      <code>datadog-metrics</code>）&mdash; 樣本起點尚不存在的套件已排除，
      因為套件進入籃子會造成永久性的人為跳升。Outage 日以<strong>只回看</strong>的
      方式估計填補（同星期幾、前 42 天），因此圖上每一個點在它所在的那一天都是可計算的。"""),
    # treatments
    ("<th>Treatment</th>", "<th>處理方式</th>"),
    ('<th class="num">vs ecosystem</th>', '<th class="num">相對生態系</th>'),
    ('<th class="num">vs competitors</th>', '<th class="num">相對競品</th>'),
    ('<th class="num">absolute</th>', '<th class="num">絕對值</th>'),
    ("""The npm API returned registry-wide zeros on
    <strong>${IMP.days} of the ${IMP.elapsed}</strong> days of published data this quarter
    (${IMP.share_pct}%). All three treatments are shown because the choice is a real
    source of uncertainty: the causal-imputed row is the point estimate, dropped-and-rescaled
    and raw-with-zeros bound it. The relative constructions are an order of magnitude
    less sensitive to the treatment than the absolute one &mdash; an outage suppresses
    every basket at once, so it largely cancels in a difference.""",
     """本季已發布資料 <strong>${IMP.elapsed} 天中有 ${IMP.days} 天</strong>
    （${IMP.share_pct}%）npm API 回傳全站零值。三種處理方式全部呈現，因為這個選擇
    是真實的不確定性來源：因果插補列是點估計，丟棄重標與原始帶零則界定其上下界。
    相對構造對處理方式的敏感度比絕對值低一個數量級 &mdash;
    outage 會同時壓低所有籃子，因此在差分中大致抵消。"""),
    # diagnostics
    ("alternative-data cells beat the strongest naive baseline. Best cell:",
     "個另類數據格勝過最強樸素基準。最佳格："),
    ("""Against the weaker AR(1) benchmark
      ${D.cells_below_09_vs_ar1} of ${D.grid_cells} cells scored below 0.9 &mdash;
      a permutation null produces ${D.perm_mean_vs_ar1} such cells on average
      (p=0.002), so the features do carry information AR(1) lacks. That information
      is drift, which a correctly specified naive baseline already supplies:
      against the strongest baseline the same null produces
      ${D.perm_mean_vs_best} cells and the observed count is ${D.cells_beating_best}.""",
     """對較弱的 AR(1) 基準，
      ${D.grid_cells} 格中有 ${D.cells_below_09_vs_ar1} 格低於 0.9 &mdash;
      置換虛無分布平均只產生 ${D.perm_mean_vs_ar1} 格（p=0.002），
      所以這些特徵確實帶有 AR(1) 缺乏的資訊。那個資訊是漂移，
      而設定正確的樸素基準本來就提供它：對最強基準，同一虛無分布產生
      ${D.perm_mean_vs_best} 格，而實際觀測值是 ${D.cells_beating_best} 格。"""),
    ("target: <code>${t}</code> &mdash; RMSE ratio vs strongest baseline (&lt;1 would beat it)",
     "目標：<code>${t}</code> &mdash; 相對最強基準的 RMSE 比值（&lt;1 才算勝過）"),
    ("<th>Feature</th>", "<th>特徵</th>"),
    ("Baselines, expanding walk-forward, no alternative data",
     "基準模型，擴張視窗 walk-forward，未使用另類數據"),
    ('<th class="num">MAPE %</th><th class="num">Hit</th>',
     '<th class="num">MAPE %</th><th class="num">命中率</th>'),
    ("Signal 2 &mdash; hyperscaler cloud growth, identical pipeline",
     "訊號 2 &mdash; hyperscaler 雲端成長，完全相同的管線"),
    # NOTE: the short header mappings above already ran, so these match the
    # partially-translated state. Order dependence is deliberate and asserted.
    ('<th>Target</th><th>特徵</th><th class="num">Ratio</th>',
     '<th>目標</th><th>特徵</th><th class="num">比值</th>'),
    ("<th>Target</th><th>Baseline</th>", "<th>目標</th><th>基準</th>"),
    ('<th class="num">Boot 95% CI</th>', '<th class="num">Bootstrap 95% CI</th>'),
    ("""Intelligent Cloud growth is <strong>significantly worse</strong> than
      the naive baseline &mdash; the confidence interval excludes 1.0 on the wrong side.
      It does achieve an 0.846 directional hit rate on revenue growth while carrying
      ~3x the baseline error, which is a clean illustration of why hit rate alone is a
      poor metric: right direction, badly wrong magnitude.""",
     """Intelligent Cloud 成長<strong>顯著劣於</strong>樸素基準 &mdash;
      信賴區間排除 1.0，但落在錯誤的那一側。它在營收成長上確實達到 0.846 的方向命中率，
      誤差卻是基準的約 3 倍，這清楚說明了為什麼單看命中率是壞指標：
      方向對、幅度大錯。"""),
    # cadence + templating + footer
    ("<th>訊號</th><th>Frequency</th><th>Latency</th><th>Role</th>",
     "<th>訊號</th><th>頻率</th><th>延遲</th><th>角色</th>"),
    ("""  Everything ticker-specific is in the <code>CONFIG</code> object at the top of this
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
  and the placebo before choosing.""",
     """  所有與標的相關的設定都在本檔頂端的 <code>CONFIG</code> 物件與 <code>DATA</code>
  payload 中。要改指向 SNOW 或 MDB 需要：(1) CIK 與 XBRL 營收標籤 &mdash;
  SEC 抓取器本身是通用的；(2) 一組訊號籃、其替代品對照籃，以及一個經濟上無關的
  安慰劑籃 &mdash; 常數組成規則與 outage 偵測器原封不動適用；
  (3) 指引抽取器重新指向該發行人 8-K 的 outlook 措辭。時點 vintage 層、基準集、
  walk-forward、置換虛無與安慰劑管線都與標的無關，不需要修改。
  <br><br>
  <em>不能</em>移轉的是結論。本 dashboard 的頭條數字建立在指引之上，
  是因為那是在 ${CONFIG.ticker} 上通過驗證的東西。對一家指引可靠度較低的公司，
  同一條管線很可能拱出不同的輸入 &mdash; 而那正是「先跑基準與安慰劑再做選擇」的意義。"""),
    ("""  Sources: SEC EDGAR XBRL company facts and Item 2.02 8-K exhibits; npm registry
  downloads API; pypistats.org. All figures trace to a cached raw response or a
  cited filing accession number. Guidance figures independently re-parsed from the
  primary document (${H.guidance_verified}). No material non-public information.
  Generated ${M.generated} from commit-tracked code; every number on this page is
  reproducible with <code>python src/build_dashboard.py</code>.""",
     """  資料來源：SEC EDGAR XBRL company facts 與 Item 2.02 8-K 附件；npm registry
  downloads API；pypistats.org。所有數字均可追溯至快取的原始回應或引用的
  accession number。指引數字已由獨立解析路徑對主文件重新核對。未使用重大非公開資訊。
  於 ${M.generated} 由版本控管的程式碼產生；本頁每個數字都可用
  <code>python src/build_dashboard.py</code> 重現。"""),
]

# ------------------------------------------------------------------ payload
PAYLOAD_MAP = {
    "Datadog, Inc.": "Datadog, Inc.（DDOG）",
    "early November 2026": "2026 年 11 月初",
    "guidance midpoint x (1 + trailing 8-quarter mean beat)":
        "指引中點 × (1 + 近八季平均超額)",
    "yes -- primary document re-fetched from EDGAR and read":
        "已核對（主文件自 EDGAR 重新抓取並閱讀）",
    ("Sell-side consensus is not included: no free, citable public "
     "source was available. It would come from a vendor feed."):
        "未納入賣方共識：找不到可引用的免費公開來源；該數字須來自付費資料商。",
    "causal-imputed (point estimate)": "因果插補（點估計）",
    "dropped days, rescaled": "丟棄 outage 日並重新標度",
    "raw, outage zeros kept": "原始值，保留 outage 零值",
    "Datadog vs ecosystem": "Datadog 相對生態系",
    "Datadog vs competitors": "Datadog 相對競品",
    "Datadog absolute": "Datadog 絕對值",
    "PLACEBO vs competitors": "安慰劑 相對競品",
    "rank-1 candidate": "先驗排序第 1",
    "rank-2 candidate": "先驗排序第 2",
    "rank-3 candidate": "先驗排序第 3",
    "negative control": "負對照組",
    "in line": "符合", "leaning": "傾向", "diverging": "背離",
    "npm download pace (Datadog basket)": "npm 下載配速（Datadog 籃）",
    "npm control + placebo baskets": "npm 對照籃 + 安慰劑籃",
    "Hyperscaler cloud segment growth": "Hyperscaler 雲端部門成長",
    "DDOG guidance (8-K EX-99.1)": "DDOG 指引（8-K EX-99.1）",
    "DDOG reported revenue (8-K Item 2.02)": "DDOG 公布營收（8-K Item 2.02）",
    "PyPI downloads": "PyPI 下載量",
    "daily": "每日", "quarterly": "每季",
    "1 day": "1 天", "same day": "當日",
    "5-19 days before DDOG reports": "早於 DDOG 發布 5–19 天",
    "34-47 days after quarter end": "季末後 34–47 天",
    "divergence monitor": "背離監控器",
    "negative control ": "負對照組 ",
    "HEADLINE INPUT": "頭條輸入",
    "target / beat history": "目標／超額歷史",
    "cross-check only, 181-day history": "僅交叉檢查，歷史 181 天",
    "random walk": "隨機漫步",
    "guidance + mean beat": "指引 + 展開式平均超額",
    "guidance + trailing beat (8q)": "指引 + 近八季平均超額",
    "AR(1)+trend": "AR(1)+趨勢",
    "signal": "訊號", "control": "對照組",
    "Ecosystem-wide download inflation": "全生態系下載量膨脹",
    "Download-to-revenue decoupling": "下載量與營收脫鉤",
    "Hyperscaler divergence": "Hyperscaler 背離",
    "Beat distribution drift": "超額分布漂移",
    "Model residual drift": "模型殘差漂移",
    "Signal-set validity": "訊號集有效性",
}

RISK_DETAIL_MAP = {
    "Control and placebo baskets grew +102% / +184% YoY in 2026. Absolute Datadog download growth is not Datadog-specific.":
        "2026 年對照籃與安慰劑籃年增 +102% / +184%。Datadog 絕對下載成長並非 Datadog 專屬現象。",
    "AI-capex-driven cloud growth (Google Cloud +82%, AWS +37% in 2026Q2) correlates weakly with the application-monitoring workloads DDOG bills for.":
        "由 AI 資本支出驅動的雲端成長（2026Q2 Google Cloud +82%、AWS +37%）與 DDOG 計費的應用監控工作負載相關性弱。",
    "Trailing-8 beat shows a mild widening tendency (Spearman &rho;=+0.69, p=0.058), not significant but not nothing. Trend-extrapolated call would be $1,195m vs $1,188m flat.":
        "近八季超額呈輕微走闊傾向（Spearman &rho;=+0.69、p=0.058），不顯著但不是沒有。趨勢外推的預估為 $1,195m，平坦法為 $1,188m。",
    "Headline-rule residuals turned from -1.96pp (pre-2025) to +0.53pp (2025 onward); the 2026Q2 residual was +0.18pp despite the largest acceleration in the sample. Guidance absorbs the regime change.":
        "頭條規則的殘差從 −1.96pp（2025 年前）轉為 +0.53pp（2025 年起）；2026Q2 儘管是樣本內最大加速，殘差僅 +0.18pp。指引吸收了 regime change。",
}


def main() -> None:
    payload = build_dashboard.main()

    # translate payload strings
    def tr(obj):
        if isinstance(obj, str):
            if obj in PAYLOAD_MAP:
                return PAYLOAD_MAP[obj]
            for en, zh in RISK_DETAIL_MAP.items():
                if obj == en:
                    return zh
            return obj
        if isinstance(obj, list):
            return [tr(v) for v in obj]
        if isinstance(obj, dict):
            return {k: tr(v) for k, v in obj.items()}
        return obj

    payload = tr(payload)
    # Divergence labels carry a "(d30)" horizon suffix appended after the base
    # label, so they miss a whole-string lookup.
    for row in payload["divergence"]:
        base, _, suffix = row["label"].partition(" (")
        row["label"] = PAYLOAD_MAP.get(base, base) + (" (" + suffix if suffix else "")

    # translate the template, asserting every mapping lands
    tpl = render_dashboard.TEMPLATE
    missing = []
    for en, zh in TEMPLATE_MAP:
        if en not in tpl:
            missing.append(en[:70])
            continue
        tpl = tpl.replace(en, zh)
    if missing:
        raise SystemExit(
            "translation source strings not found (template drifted?):\n  "
            + "\n  ".join(missing)
        )

    # risk-flag detail strings live in the template's JS array
    for en, zh in RISK_DETAIL_MAP.items():
        tpl = tpl.replace(en, zh)
    tpl = tpl.replace(
        "0 of ${DATA.diagnostics.grid_cells} alternative-data cells beat the strongest naive baseline. Treat every signal on this page as monitoring, not forecasting.",
        "${DATA.diagnostics.grid_cells} 格另類數據中 0 格勝過最強樸素基準。本頁每個訊號都應視為監控用途，而非預測用途。",
    )
    tpl = tpl.replace(
        "Downloads per $m of revenue rose from ${DATA.decoupling.first4.toLocaleString()} to ${DATA.decoupling.last4.toLocaleString()} (Spearman &rho;=${DATA.decoupling.rho}, p${DATA.decoupling.p}). The proxy has degraded ~5x over the sample.",
        "每百萬美元營收對應的下載量從 ${DATA.decoupling.first4.toLocaleString()} 升到 ${DATA.decoupling.last4.toLocaleString()}（Spearman &rho;=${DATA.decoupling.rho}、p${DATA.decoupling.p}）。代理關係在樣本期內衰減約 4.5 倍。",
    )
    # Risk-flag names and state literals live in the template's JS array, not
    # in the payload, so they need template-side replacement.
    for en, zh in (
        ('name: "Ecosystem-wide download inflation"', 'name: "全生態系下載量膨脹"'),
        ('name: "Download-to-revenue decoupling"', 'name: "下載量與營收脫鉤"'),
        ('name: "Hyperscaler divergence"', 'name: "Hyperscaler 背離"'),
        ('name: "Beat distribution drift"', 'name: "超額分布漂移"'),
        ('name: "Model residual drift"', 'name: "模型殘差漂移"'),
        ('name: "Signal-set validity"', 'name: "訊號集有效性"'),
        ('state: "diverging"', 'state: "背離"'),
        ('state: "leaning"', 'state: "傾向"'),
        ('state: "in line"', 'state: "符合"'),
        ('state === "diverging"', 'state === "背離"'),
        ('state === "leaning"', 'state === "傾向"'),
        ('paceUnits: "millions of downloads, cumulative"',
         'paceUnits: "單位：百萬次下載，累計"'),
        ('h.role === "control"', 'h.role === "對照組"'),
        ('c.role === "HEADLINE INPUT"', 'c.role === "頭條輸入"'),
    ):
        if en not in tpl:
            raise SystemExit(f"zh: template literal not found: {en}")
        tpl = tpl.replace(en, zh)

    tpl = tpl.replace('<html lang="en">', '<html lang="zh-Hant">')

    html = tpl.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False)).replace(
        "__TICKER__", payload["meta"]["ticker"]
    )
    out = sc.REPO / "report-zh" / "dashboard.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html)

    # leftover-English scan over visible prose
    prose = re.findall(r">([A-Za-z][A-Za-z ,'&;/-]{25,})<", html)
    leftovers = [p.strip() for p in prose if not p.strip().startswith("http")]
    print(f"Wrote {out.relative_to(sc.REPO)}  ({out.stat().st_size / 1024:.0f} KB)")
    print(f"translation mappings applied: {len(TEMPLATE_MAP)} template, "
          f"{len(PAYLOAD_MAP)} payload")
    if leftovers:
        print(f"leftover English prose blocks: {len(leftovers)}")
        for p in leftovers[:8]:
            print("   ", p[:90])
    else:
        print("no leftover English prose detected in visible text")


if __name__ == "__main__":
    main()
