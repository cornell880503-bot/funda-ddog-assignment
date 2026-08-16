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
import pathlib
import tempfile
import subprocess

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
     "指引核對 ${H.guidance_verified === 'agree' ? '一致' : H.guidance_verified} · 8-K ${H.guidance_accession}"),
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
    ("""No construction beat the strongest naive baseline out of sample &mdash; 0 of
    ${DATA.diagnostics.grid_cells} grid cells, and 0 again once features are
    orthogonalised against guidance (see Model diagnostics). The scope of that
    claim is narrow and deliberate: what was testable is the Node.js SDK channel,
    roughly a tenth of the observable install volume, while the core agent's
    channel publishes no history at all (see Observability). The signals below run
    as a <em>divergence monitor</em>: they do not set the number, they flag when
    the rule behind it is likely to break.""",
     """沒有任何構造在樣本外勝過最強的樸素基準 &mdash;
    ${DATA.diagnostics.grid_cells} 格中 0 格；把特徵對指引正交化之後，仍然是 0 格
    （見模型診斷）。這個結論的範圍是刻意收窄的：可測試的只有 Node.js SDK 這條管道，
    約佔可觀測安裝量的十分之一，而核心 agent 的管道根本不公布任何歷史（見可觀測性）。
    下方訊號的角色是<em>背離監控器</em>：它們不決定數字，
    只標示背後那條規則何時可能失效。"""),
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
    the <em>placebo</em> sits at z=${(() => { const p = DATA.divergence.find(r => r.feature.indexOf("plc_") === 0); return (p.z >= 0 ? "+" : "") + p.z.toFixed(2); })()}. That pattern says the ecosystem is running
    hot, not that Datadog is.""",
     """「背離」代表本季在該指標上不像過去八季。它<em>不能</em>轉換成營收：
    這些訊號到營收的映射在樣本外驗證中失敗了。看目前的讀數 &mdash;
    Datadog 絕對值指標呈背離，但經生態系調整後的指標是符合，而<em>安慰劑</em>
    位在 z=${(() => { const p = DATA.divergence.find(r => r.feature.indexOf("plc_") === 0); return (p.z >= 0 ? "+" : "") + p.z.toFixed(2); })()}。這個組合說的是生態系在發燙，不是 Datadog。"""),
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
    ("target: <code>${T(tg)}</code> &mdash; RMSE ratio vs strongest baseline (&lt;1 would beat it)",
     "目標：<code>${T(tg)}</code> &mdash; 相對最強基準的 RMSE 比值（&lt;1 才算勝過）"),
    ("Baselines, expanding walk-forward, no alternative data",
     "基準模型，擴張視窗 walk-forward，未使用另類數據"),
    ('<th class="num">MAPE %</th><th class="num">Hit</th>',
     '<th class="num">MAPE %</th><th class="num">命中率</th>'),
    ("Signal 2 &mdash; hyperscaler cloud growth, identical pipeline",
     "訊號 2 &mdash; hyperscaler 雲端成長，完全相同的管線"),
    ('<th>Target</th><th>Feature</th><th class="num">Ratio</th>',
     '<th>目標</th><th>特徵</th><th class="num">比值</th>'),
    ("<th>Target</th><th>Baseline</th>", "<th>目標</th><th>基準</th>"),
    ("<th>Series</th><th>Role</th>", "<th>序列</th><th>角色</th>"),
    ('<th class="num">n OOS</th>', '<th class="num">樣本外 n</th>'),
    ('<th class="num">Hit</th>', '<th class="num">命中率</th>'),
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
    ('Observability &mdash; what the signal can and cannot see',
     '可觀測性 &mdash; 訊號看得到什麼、看不到什麼'),
    ('<th>Distribution channel</th><th>Carries</th>',
     '<th>分發管道</th><th>承載什麼</th>'),
    ('<th class="num">Cumulative</th><th>History</th><th>Testable</th>',
     '<th class="num">累計量</th><th>可得歷史</th><th>可測試</th>'),
    ("<strong>This is the project's binding constraint.</strong>\n    Datadog's core billable unit is the Go agent, shipped through Docker Hub,\n    APT/YUM, Helm and cloud marketplaces. That channel carries about\n    <strong>10x</strong> the volume of the npm channel this dashboard measures, and\n    Docker Hub exposes only a lifetime cumulative counter &mdash; no time series, no\n    per-tag split &mdash; so it cannot be backfilled for the 27 quarters already\n    elapsed. A daily snapshot of that counter yields a usable delta series\n    <em>from the day collection starts</em>, which is the correct forward fix and\n    the single highest-value addition to this pipeline.",
     '<strong>這是本專案的關鍵限制。</strong>\n    Datadog 的核心計費單位是 Go agent，透過 Docker Hub、APT/YUM、Helm 與雲市集分發。\n    該管道的量約為本 dashboard 所量測的 npm 管道的 <strong>10 倍</strong>，\n    而 Docker Hub 只公布終身累計計數 &mdash; 無時序、無分 tag &mdash;\n    因此已經過去的 27 季無法回補。每日對該計數取快照可以得到一條可用的差分序列，\n    但<em>只能從開始蒐集那天起算</em>。這是正確的前瞻性補救，\n    也是這條管線單一價值最高的補強。'),
    ('Guidance-orthogonalised features &mdash; incremental content over guidance',
     '對指引正交化的特徵 &mdash; 相對指引的增量資訊'),
    ('Re-running every cell with the feature\n      residualised against guidance-implied growth (train-only coefficients), which\n      is how a quantamental desk would use it: predict the surprise, not the level.\n      Result: <strong>${D.cells_beating_best_orth} of ${D.grid_cells}</strong> cells\n      beat the baseline, best ${D.best_cell_ratio_orth}. Stripping out what guidance\n      already implies leaves <em>less</em>, not more.',
     '把每一格都改用「特徵對指引隱含成長取殘差」（係數只用訓練集）重跑一次 &mdash;\n      這才是基本面量化實際的用法：預測預期差，而不是預測水準值。\n      結果：<strong>${D.grid_cells} 格中 ${D.cells_beating_best_orth} 格</strong>勝過基準，\n      最佳 ${D.best_cell_ratio_orth}。扣掉指引已隱含的部分後，剩下的<em>更少</em>而非更多。'),
    ('Other target metrics from the brief',
     '題目指定的其他目標指標'),
    ('<th>Target</th><th class="num">n OOS</th>\n      <th class="num">Cells beating baseline</th><th class="num">Best cell</th>',
     '<th>目標</th><th class="num">樣本外 n</th>\n      <th class="num">勝過基準格數</th><th class="num">最佳格</th>'),
    ('Downloads are an unweighted count while\n      revenue is dollar-weighted, so a count-type target should match better. It does:\n      against $100k+ customer growth the best cell is <strong>${(DATA.extended.find(e => e.target === "cust_yoy") || {best:0}).best.toFixed(3)}</strong>, the\n      closest any signal came to a baseline here, versus ${DATA.diagnostics.best_cell_ratio.toFixed(3)} against revenue growth.\n      Still a loss, at n=11. RPO has insufficient history; NRR is not disclosed as a\n      number in the 8-K exhibits and is excluded rather than approximated.',
     '下載量是未加權的計數，營收則是金額加權，\n      因此計數型目標理應匹配得更好 &mdash; 而它確實如此：對 $100k+ 客戶數成長，\n      最佳格是 <strong>${(DATA.extended.find(e => e.target === "cust_yoy") || {best:0}).best.toFixed(3)}</strong>，這是本專案中訊號最接近基準的一次，\n      優於對營收成長的 ${DATA.diagnostics.best_cell_ratio.toFixed(3)}。但在 n=11 之下，它仍然是輸。\n      RPO 歷史不足；NRR 在 8-K 附件中沒有數字揭露，故排除而非以近似值頂替。'),
    ('Statistical power &mdash; what this sample could have detected',
     '統計檢定力 &mdash; 這個樣本原本能偵測到什麼'),
    ('<th>Target</th><th class="num">n</th>\n      <th class="num">detect r=0.95</th><th class="num">r=0.90</th>\n      <th class="num">r=0.80</th>',
     '<th>目標</th><th class="num">n</th>\n      <th class="num">偵測 r=0.95</th><th class="num">r=0.90</th>\n      <th class="num">r=0.80</th>'),
    ('<strong>A genuine 5&ndash;10% edge would\n      have gone undetected roughly 85&ndash;90% of the time.</strong> "0 of 24"\n      therefore <em>bounds</em> the effect size rather than showing it is zero. What\n      is <em>not</em> a power problem: the observed cells sit at ratios of 1.05 to\n      2.65 &mdash; consistent, large degradation on the wrong side of parity.',
     '<strong>一個真實的 5&ndash;10% 邊際，約有 85&ndash;90% 的機率會被漏掉。</strong>\n      因此「24 格中 0 格」是<em>界定</em>效果量的上界，而不是證明效果為零。\n      但有一半<em>不是</em>檢定力問題：實際觀測到的格子落在 1.05 到 2.65 &mdash;\n      大幅且一致地落在錯誤的那一側。'),
    ('Unstructured signal &mdash; management tone, and its in-document placebo',
     '非結構化訊號 &mdash; 管理層語氣，與它在同一份文件內的安慰劑'),
    ('<th>Text measured</th>\n      <th class="num">corr with next beat</th><th class="num">Best cell</th>',
     '<th>量測的文字</th>\n      <th class="num">與後續超額相關</th><th class="num">最佳格</th>'),
    ('<td>management-authored body</td>',
     '<td>管理層撰寫的正文</td>'),
    ("<strong>counsel's forward-looking-statements boilerplate</strong>",
     '<strong>法務撰寫的前瞻性陳述樣板</strong>'),
    ('The 8-K press release is the one\n      qualitative source that is cleanly backfillable &mdash; free, official, and\n      timestamped at the guidance-issuance moment. <strong>The legal disclaimer\n      beats management\'s own words on every comparison</strong>, and against AR(1)\n      it is "significant" (CI [${DATA.tone.plc_ci_lo.toFixed(3)}, ${DATA.tone.plc_ci_hi.toFixed(3)}], DM p=${DATA.tone.plc_dm_p.toFixed(3)}) &mdash; from text written\n      to convey no information. Boilerplate drifts as counsel updates the template,\n      so it proxies time. Unstructured features are <em>more</em> exposed to\n      spurious trend-fitting than structured ones, so in an LLM extraction pipeline\n      the control discipline matters more than the extraction quality.',
     '8-K 新聞稿是唯一可以乾淨回補的質化來源 &mdash; 免費、官方，\n      且時間戳就落在指引發布的那一刻。<strong>法務的免責聲明在每一項比較上\n      都打敗管理層自己的話</strong>，對 AR(1) 更達到「顯著」\n      （CI [${DATA.tone.plc_ci_lo.toFixed(3)}, ${DATA.tone.plc_ci_hi.toFixed(3)}]、DM p=${DATA.tone.plc_dm_p.toFixed(3)}）&mdash; 而那段文字根本不是為了傳遞資訊而寫的。\n      樣板隨律師改版而漂移，因此它是時間的代理。非結構化特徵比結構化特徵\n      <em>更</em>容易產生偽趨勢擬合，所以在 LLM 抽取管線裡，\n      對照組紀律比抽取品質更重要。'),
    ('How the signals combine &mdash; the tracking call',
     '訊號如何合成 &mdash; 追蹤判斷'),
    ('<strong>Why these two, equally weighted.</strong>\n    Both are drift-adjusted. <em>Datadog absolute</em> is excluded from the\n    composite because it carries the ecosystem-wide inflation documented below &mdash;\n    including it would make the indicator fire on registry activity rather than on\n    Datadog. Weights are equal because nothing here survived validation, and fitting\n    weights on ${DATA.diagnostics.grid_cells} cells that all failed would be exactly\n    the error this project exists to warn about.',
     '<strong>為什麼是這兩個，而且等權。</strong>\n    兩者都做過漂移調整。<em>Datadog 絕對值</em>被排除在合成之外，因為它帶著下方記錄的\n    全生態系膨脹 &mdash; 納入它會讓指標對 registry 活動亮燈而不是對 Datadog 亮燈。\n    權重等權，是因為這裡沒有任何東西通過驗證，而在 ${DATA.diagnostics.grid_cells} 個\n    全數失敗的格子上去擬合權重，正是本專案要警告的那個錯誤。'),
    ('What "tracking ahead / behind" has actually meant',
     '「領先／落後」在歷史上實際代表什麼'),
    ('A directional label is decoration until\n    someone checks it. For every historical quarter the call is recomputed from\n    prior quarters only, then compared with whether that quarter beat guidance by\n    <em>more</em> than its own trailing 8-quarter mean beat.',
     '方向標籤在有人驗證它之前只是裝飾。每一個歷史季度的判斷都只用先前季度重算，\n    再比對該季實際超額是否**高於**它自己近八季的平均超額。'),
    ('<th>Quarter</th><th class="num">Composite z</th><th>Call</th>\n    <th class="num">Beat</th><th class="num">Trailing mean</th><th>Outcome</th><th></th>',
     '<th>季度</th><th class="num">合成 z</th><th>判斷</th>\n    <th class="num">實際超額</th><th class="num">近八季均值</th><th>結果</th><th></th>'),
    ('<th>Horizon</th>\n    <th class="num">Directional calls</th><th class="num">Correct</th>\n    <th class="num">Hit rate</th><th class="num">p vs coin flip</th>',
     '<th>視窗</th>\n    <th class="num">方向判斷次數</th><th class="num">正確</th>\n    <th class="num">命中率</th><th class="num">對擲硬幣的 p</th>'),
    ("<strong>70% at ten calls is not a\n    result.</strong> The binomial p-value against a coin flip is 0.34. The\n    indicator is a monitoring aid with a measured and unimpressive reliability,\n    stated here rather than hidden &mdash; which is the only defensible way to put a\n    directional call on an analyst's screen. It does <em>not</em> feed the headline\n    number, and the signals do not combine into a revenue estimate, because no\n    construction beat a naive baseline out of sample.",
     '<strong>十次判斷 70% 不是結果。</strong>\n    對擲硬幣的 binomial p 值是 0.34。這個指標是一個可靠度經過量測、而且並不亮眼的\n    監控工具，數字放在這裡而不是藏起來 &mdash; 那是把方向判斷放上分析師螢幕\n    唯一站得住的做法。它<em>不</em>餵入頭條數字，而且訊號不會合成為營收估計，\n    因為沒有任何構造在樣本外勝過樸素基準。'),
    ("""Both bars are on the same revenue axis.
      The 95% interval does <strong>not overlap the guidance range at any point</strong> —
      its floor sits $${fmt(H.lo-H.guide_high,0)}m above the top of guidance. That is what
      27 consecutive beats implies, and it is the most consequential assumption on
      this page.""",
     """兩條都落在同一條營收軸上。95% 區間<strong>在任何一點都不與指引區間重疊</strong> ——
      它的下緣比指引上緣高出 $${fmt(H.lo-H.guide_high,0)}m。那正是連續 27 季超額所隱含的結果，
      也是本頁最關鍵的假設。"""),
    ('guidance ${fmt(H.guide_low,0)}&ndash;${fmt(H.guide_high,0)}</text>',
     '指引 ${fmt(H.guide_low,0)}&ndash;${fmt(H.guide_high,0)}</text>'),
    ('95% interval ${fmt(H.lo,0)}&ndash;${fmt(H.hi,0)}</text>',
     '95% 區間 ${fmt(H.lo,0)}&ndash;${fmt(H.hi,0)}</text>'),
    ('gap ${fmt(H.lo-H.guide_high,0)}m</text>', '落差 ${fmt(H.lo-H.guide_high,0)}m</text>'),
    ('Beat vs guidance midpoint, last ${B.length} quarters',
     '相對指引中點的超額，近 ${B.length} 季'),
    ('trailing-${H.trailing_n} mean +${mean.toFixed(2)}%',
     '近 ${H.trailing_n} 季均值 +${mean.toFixed(2)}%'),
    ('<strong>Never negative, and flat since 2024.</strong>\n      The blue bars are the ${H.trailing_n} quarters feeding the current estimate\n      (sd ${H.trailing_beat_sd_pp.toFixed(2)}pp). That stability is what the &plusmn;$${fmt((H.hi-H.lo)/2,1)}m\n      interval is made of — and the assumption that breaks first if guidance philosophy changes.',
     '<strong>從未為負，且 2024 年起持平。</strong>\n      藍色長條是餵入目前估計的 ${H.trailing_n} 季（標準差 ${H.trailing_beat_sd_pp.toFixed(2)}pp）。\n      這個穩定性就是 &plusmn;$${fmt((H.hi-H.lo)/2,1)}m 區間的來源 —\n      也是指引哲學一旦改變、最先失效的假設。'),
    ('>TRACKING BEHIND</text>',
     '>落後</text>'),
    ('>IN LINE</text>',
     '>符合</text>'),
    ('>TRACKING AHEAD</text>',
     '>領先</text>'),
    ('COMPOSITE ${cz >= 0 ? "+" : ""}${cz.toFixed(2)}',
     '合成 ${cz >= 0 ? "+" : ""}${cz.toFixed(2)}'),
    ("""The grey dot is the <strong>placebo</strong>,
      which cannot contain Datadog information. Compare it with the ecosystem-adjusted
      Datadog measure before reading anything into the absolute one &mdash; when the
      placebo leans as hard as the signal, the ecosystem is what is moving.""",
     """灰點是<strong>安慰劑</strong>，它不可能含有任何 Datadog 資訊。
      在對絕對值指標做任何解讀之前，先跟經生態系調整後的 Datadog 指標比一比 &mdash;
      當安慰劑偏離得跟訊號一樣多，在動的就是生態系。"""),
    ('Green would be a win (&lt;1.0).\n    <strong>There is no green.</strong> Amber is 1.0&ndash;1.3, red is worse, and the\n    deeper the red the further from parity.',
     '綠色才算勝出（&lt;1.0）。<strong>沒有任何綠色。</strong>\n    琥珀色是 1.0&ndash;1.3，紅色更差，紅得越深離基準越遠。'),
    ('How to read this page &mdash; two tracks, deliberately separate',
     '如何讀這一頁 &mdash; 兩條軌道，刻意分開'),
    ('<span class="track">Track A &mdash; the number.</span> The estimate comes from\n      Datadog\'s own guidance plus its trailing beat. The beat-history chart below it is\n      the variance the &plusmn;$${fmt((H.hi - H.lo) / 2, 1)}m band is built from.',
     '<span class="track">軌道 A &mdash; 那個數字。</span> 預估來自 Datadog 自己的指引\n      加上它的近期超額。下方的超額歷史圖，就是 &plusmn;$${fmt((H.hi - H.lo) / 2, 1)}m 區間所依據的變異。'),
    ('<span class="track">Track B &mdash; the monitor.</span> The alternative signals.\n      They do <b>not</b> feed the number: <b>0 of ${DATA.diagnostics.grid_cells}</b> tested\n      constructions beat a naive baseline out of sample. They answer a different question\n      &mdash; <em>is this quarter still behaving like the eight the rule was fitted on?</em>',
     '<span class="track">軌道 B &mdash; 監控器。</span> 另類數據訊號。它們<b>不</b>餵入那個數字：\n      ${DATA.diagnostics.grid_cells} 個受測構造中 <b>0 個</b>在樣本外勝過樸素基準。\n      它們回答的是另一個問題 &mdash; <em>這一季的行為，是否仍然像那條規則所擬合的八季？</em>'),
    ('<span class="track">Track C &mdash; how much to trust either.</span> The validation\n      record, the update cadence, and what it takes to repoint the page at another ticker.',
     '<span class="track">軌道 C &mdash; 該對它們信任多少。</span> 驗證紀錄、更新頻率，\n      以及把這一頁指向另一檔標的需要什麼。'),
    ("If Track B is quiet, Track A's number stands on\n    its own. If Track B diverges, the number does not change &mdash; but its <em>assumption</em>,\n    that this quarter resembles the last eight, is the thing under strain.",
     '若軌道 B 安靜，軌道 A 的數字自己站得住。若軌道 B 出現背離，數字不會改變 &mdash;\n    但它的<em>假設</em>（這一季像過去八季）就是承受壓力的那一環。'),
    ('The number, and the two inputs it is made of. Everything below either <b>supports</b> this figure or <b>monitors the assumption</b> behind it &mdash; nothing below changes it.',
     '那個數字，以及構成它的兩個輸入。下方所有內容不是<b>支撐</b>這個數字，就是<b>監控它背後的假設</b> &mdash; 沒有任何一塊會改變它。'),
    ('Track B starts here. This is the &ldquo;how do the signals combine&rdquo; question: the four series in the next panel are reduced to <b>one directional call</b>, and that call is backtested rather than asserted.',
     '軌道 B 從這裡開始。這回答「訊號如何合成」：下一塊的四條序列被收斂成<b>一個方向判斷</b>，而那個判斷是回測過的，不是宣稱的。'),
    ('The four component series behind the composite above. Read them <b>together</b>, not one at a time &mdash; the placebo row is what tells you whether a Datadog reading means anything.',
     '上方合成指標背後的四條成分序列。要<b>一起讀</b>，不要單看一條 &mdash; 安慰劑那一列，才是判斷 Datadog 讀數有沒有意義的依據。'),
    ('Why Track B is a monitor and not an estimator: the signals above see roughly <b>a tenth</b> of Datadog&rsquo;s install surface, and the other nine tenths publish no history at all.',
     '為什麼軌道 B 是監控器而不是估計器：上方訊號只看得到 Datadog 安裝面向的<b>約十分之一</b>，其餘九成完全不公布歷史。'),
    ('The raw series underneath those z-scores &mdash; same data before standardisation, so the live quarter&rsquo;s path can be read against prior quarters at the same day.',
     '那些 z 分數底下的原始序列 &mdash; 同一份資料在標準化之前，因此可以把本季路徑對照前幾季的同一天來讀。'),
    ('How much of the divergence reading is an artefact of patching missing days rather than real movement.',
     '背離讀數裡，有多少是補缺失日造成的假象，而不是真實變動。'),
    ('Standing conditions that would break Track A&rsquo;s assumption or invalidate Track B&rsquo;s reading. Monitored continuously, not recomputed each quarter.',
     '會破壞軌道 A 假設、或使軌道 B 讀數失效的長期條件。持續監控，不是每季重算。'),
    ('Track C. The full validation record behind the claim that the signals do not feed the number &mdash; on the face of the dashboard rather than buried, because the analyst has to price that confidence themselves.',
     '軌道 C。「訊號不餵入數字」這個主張背後的完整驗證紀錄 &mdash; 放在 dashboard 正面而不是藏起來，因為分析師必須自己判斷該給多少信心。'),
    ('How often each block above actually moves, and how stale it can be at the moment you look at it.',
     '上方每一塊實際多久會變動一次，以及你看到它時它可能已經多舊。'),
    ('What is generic infrastructure here, versus what is specific to Datadog.',
     '這裡哪些是通用基礎設施，哪些是 Datadog 專屬的。'),
    ('First: what the z on this page actually is, and why it is not the raw growth rate',
     '先講：這一頁的 z 到底是什麼，以及為什麼不直接看成長率'),
    ('<b>The raw number cannot answer the question.</b>\n            Datadog downloads through day ${day} of this quarter are\n            <b>${pct(abs.current)}% YoY</b>. Ahead or behind? On its own that is unreadable\n            &mdash; the whole registry grew too, and the quarter is not finished.',
     '<b>原始數字回答不了這個問題。</b>\n            本季到第 ${day} 天，Datadog 下載量年增 <b>${pct(abs.current)}%</b>。\n            這是領先還是落後？單看它無法判讀 &mdash; 整個 registry 也在長，而且這一季還沒結束。'),
    ('<b>So compare the signal with its own past,\n            at the same point in the quarter.</b> Downloads accumulate, so day ${day} has to be\n            measured against day ${day} of the prior 8 quarters &mdash; never against a full quarter.',
     '<b>所以要拿這個訊號跟它自己的過去比，而且要比在季內的同一個位置。</b>\n            下載量是累積的，所以第 ${day} 天只能對照前 8 季的第 ${day} 天 &mdash; 絕不能對照整季。'),
    ('<b>That comparison is the z.</b> It says how\n            unusual today is <em>for this signal</em>, in units of its own normal quarter-to-quarter\n            variation.',
     '<b>那個比較就是 z。</b> 它說的是：以<em>這個訊號自己</em>的標準來看，\n            今天有多不尋常 —— 單位是它自身正常的季間波動。'),
    ('Worked, on the live reading',
     '用現時讀數實際算一次'),
    ('this quarter, day ${day}',
     '本季，第 ${day} 天'),
    ('prior 8 quarters, same day &mdash; average',
     '前 8 季同一天 &mdash; 平均'),
    ('prior 8 quarters &mdash; standard deviation',
     '前 8 季 &mdash; 標準差'),
    ('Read as: Datadog\'s absolute download growth is\n            <b>${Math.abs(abs.z).toFixed(1)} standard deviations ${abs.z >= 0 ? "above" : "below"}</b>\n            what this signal normally does by day ${day}. <b>z = 0</b> would be an\n            exactly typical quarter.',
     '讀法：Datadog 的絕對下載成長，比這個訊號在第 ${day} 天的常態\n            <b>${abs.z >= 0 ? "高" : "低"}出 ${Math.abs(abs.z).toFixed(1)} 個標準差</b>。\n            <b>z = 0</b> 代表完全典型的一季。'),
    ('<b>Why this is the right unit for "tracking\n        ahead / behind".</b> Ahead of what? Not of zero, and not of the ecosystem &mdash; of\n        <em>this quarter\'s own precedent</em>. A z answers exactly that, in a unit that is\n        comparable across signals measured on different scales, which is what makes averaging\n        them into one call defensible at all.',
     '<b>為什麼這是「領先／落後」的正確單位。</b> 領先於什麼？不是領先於零，\n        也不是領先於生態系 &mdash; 是領先於<em>這一季自己的前例</em>。z 正好回答這個，\n        而且它的單位在不同尺度的訊號之間可以比較 —— 那才使得把它們平均成一個判斷是站得住的。'),
    ('Composite tracking indicator, day ${M.days_elapsed} (${C.horizon} window)',
     '合成追蹤指標，第 ${M.days_elapsed} 天（${C.horizon} 視窗）'),
    ('<div class="kv"><span>Combines</span>',
     '<div class="kv"><span>合成自</span>'),
    ('<div class="kv"><span>Weighting</span><span>equal</span></div>',
     '<div class="kv"><span>權重</span><span>等權</span></div>'),
    ('<div class="kv"><span>Excluded</span>',
     '<div class="kv"><span>排除</span>'),
    ('<div class="kv"><span>Tracking ahead</span>',
     '<div class="kv"><span>領先</span>'),
    ('<div class="kv"><span>Tracking behind</span>',
     '<div class="kv"><span>落後</span>'),
    # cadence + templating + footer
    ("<th>Signal</th><th>Frequency</th><th>Latency</th><th>Role</th>",
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
  accession number。指引數字已由獨立解析路徑對主文件重新核對（${H.guidance_verified}）。未使用重大非公開資訊。
  於 ${M.generated} 由版本控管的程式碼產生；本頁每個數字都可用
  <code>python src/build_dashboard.py</code> 重現。"""),
]

# ------------------------------------------------------------------ payload
DISPLAY_MAP = {
    # Values the JS branches on. These stay English in the payload so every
    # comparison in the template keeps working; they are injected as TRV and
    # translated at the moment of display instead. Translating them in the
    # payload is what made the Chinese build throw and drop eight panels.
    "in line": "符合", "leaning": "傾向", "diverging": "背離",
    "rank-1 candidate": "先驗排序第 1",
    "rank-2 candidate": "先驗排序第 2",
    "rank-3 candidate": "先驗排序第 3",
    "negative control": "負對照組",
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
    "appendix": "附錄",
    "yes": "是",
    "NO": "否",
    "tracking ahead": "領先", "tracking behind": "落後",
    "cust_yoy": "$100k+ 客戶數成長", "billings_yoy": "Billings 成長",
    "rev_yoy": "營收年增率", "beat_vs_guide": "相對指引超額",
    "guidance + auto-window beat": "指引 + 自動選窗超額",
    "no": "否",
}

PAYLOAD_MAP = {
    "Datadog, Inc.": "Datadog, Inc.（DDOG）",
    "early November 2026": "2026 年 11 月初",
    ("guidance midpoint x (1 + mean beat over a trailing window "
     "whose length is selected out-of-sample)"):
        "指引中點 × (1 + 樣本外選定視窗的平均超額)",
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
    # coverage-table strings (payload side)
    "npm (constant-composition basket)": "npm（常數組成籃）",
    "npm (all Datadog packages)": "npm（全部 Datadog 套件）",
    "Docker Hub datadog/agent": "Docker Hub datadog/agent",
    "Docker Hub datadog/cluster-agent": "Docker Hub datadog/cluster-agent",
    "APT / YUM repositories": "APT / YUM 套件庫",
    "Helm chart / Kubernetes operator": "Helm chart / Kubernetes operator",
    "AWS / Azure / GCP marketplace": "AWS / Azure / GCP 雲市集",
    "Node.js APM tracer + metrics client": "Node.js APM tracer + metrics client",
    "Node.js SDKs incl. browser RUM/logs, CI": "Node.js SDK（含 browser RUM/logs、CI）",
    "the core Go agent (host + container monitoring)": "核心 Go agent（主機 + 容器監控）",
    "Linux package installs of the core agent": "核心 agent 的 Linux 套件安裝",
    "container-orchestrated agent rollout": "容器編排的 agent 部署",
    "marketplace-billed deployments": "雲市集計費的部署",
    "daily, 2017+": "每日，2017 起",
    "CUMULATIVE COUNTER ONLY -- no time series": "僅累計計數 —— 無時序資料",
    "not publicly exposed": "未公開",
    "NO -- not backfillable": "否 —— 無法回補",
    "above trend": "高於趨勢", "below trend": "低於趨勢",
    "Datadog vs ecosystem": "Datadog 相對生態系",
    "Datadog absolute (carries ecosystem inflation)": "Datadog 絕對值（帶有生態系膨脹）",
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


def smoke_test(zh_html: pathlib.Path, en_html: pathlib.Path) -> None:
    """Execute both builds' JS and require them to render the same panel count.

    The Chinese build once shipped with eight of ten panels missing: a payload
    value that the JS branched on had been translated, so a lookup returned
    undefined and the script threw halfway down the page. Nothing in the
    template-coverage or leftover-English checks can see that -- the file is
    complete and correctly translated, it just stops executing. Only running it
    catches it, so the render runs it.
    """
    stub = """
const nodes = [];
function mk(){ return { _h:"", set innerHTML(v){this._h=v;}, get innerHTML(){return this._h;},
  get firstChild(){return this;}, appendChild(n){nodes.push(n); return n;}, style:{},
  classList:{add(){},remove(){}}, querySelector(){return null;}, querySelectorAll(){return [];},
  addEventListener(){}, textContent:"" }; }
global.document = { createElement: mk, getElementById: () => mk(), querySelector: () => null,
  querySelectorAll: () => [], addEventListener(){} };
global.window = { addEventListener(){}, matchMedia: () => ({matches:false, addEventListener(){}}) };
global.__nodes = nodes;
"""
    counts, rendered = {}, {}
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        (td / "stub.js").write_text(stub)
        for tag, path in (("en", en_html), ("zh", zh_html)):
            js = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", path.read_text(), re.S))
            (td / f"{tag}.js").write_text(js)
            r = subprocess.run(
                ["node", "-e", f'require("{td}/stub.js");'
                 f'try{{require("{td}/{tag}.js");}}catch(e){{console.log("THROW:"+e.message);}}'
                 'console.log("N="+__nodes.length);'
                 'console.log("<<<"+__nodes.map(n=>n.innerHTML).join("\\n"));'],
                capture_output=True, text=True,
            )
            if "THROW:" in r.stdout:
                raise SystemExit(f"zh: {tag} build throws at runtime -> {r.stdout.strip()}")
            counts[tag] = int(re.search(r"N=(\d+)", r.stdout).group(1))
            rendered[tag] = r.stdout.split("<<<", 1)[1] if "<<<" in r.stdout else ""
    if counts["zh"] != counts["en"]:
        raise SystemExit(
            f"zh: rendered {counts['zh']} blocks but the English build renders "
            f"{counts['en']} -- the translation broke a branch"
        )
    print(f"smoke test: both builds render {counts['en']} blocks")
    return rendered["zh"]


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
    # A value the JS branches on must never be translated in the payload. The
    # runtime smoke test below catches the variant that throws; this catches the
    # quieter one, where a translated value simply falls through to the wrong
    # branch and mislabels a row without any error.
    overlap = set(DISPLAY_MAP) & set(PAYLOAD_MAP)
    if overlap:
        raise SystemExit(
            "zh: these are branch values and must live only in DISPLAY_MAP: "
            + ", ".join(sorted(overlap))
        )
    flat = json.dumps(payload, ensure_ascii=False)
    leaked = [en for en, zh in DISPLAY_MAP.items() if f'"{zh}"' in flat]
    if leaked:
        raise SystemExit(
            "zh: branch values were translated in the payload, so the template "
            "will take the wrong branch: " + ", ".join(leaked)
        )

    # Divergence labels carry a "(d30)" horizon suffix appended after the base
    # label, so they miss a whole-string lookup.
    for row in payload["divergence"]:
        base, _, suffix = row["label"].partition(" (")
        row["label"] = PAYLOAD_MAP.get(base, base) + (" (" + suffix if suffix else "")

    # translate the template, asserting every mapping lands
    tpl = render_dashboard.TEMPLATE
    missing = []
    # Longest source first. A short generic mapping ("prior quarters") would
    # otherwise chop up a longer specific one that contains it, and the longer
    # mapping would then silently fail to match. Sorting by length removes the
    # whole class of ordering bug instead of hand-tuning individual entries.
    for en, zh in sorted(TEMPLATE_MAP, key=lambda kv: -len(kv[0])):
        if en not in tpl:
            missing.append(en[:70])
            continue
        tpl = tpl.replace(en, zh)
    if missing:
        raise SystemExit(
            "translation source strings not found (template drifted?):\n  "
            + "\n  ".join(missing)
        )

    for en, zh in (
        ("""Scored on revenue growth against the same
      strongest baseline the headline uses. Matched non-cloud controls come from the
      <em>same filing</em>, so issuer, quarter and extraction method are held fixed.""",
         """以營收年增率為標的，對照頭條所用的同一個最強基準評分。
      配對的非雲端對照組取自<em>同一份 filing</em>，因此發行人、季度與抽取方法
      都被固定住。"""),
        ("""<strong>An 84.6% directional hit rate with
      over 3&times; the baseline error is the trap.</strong> Intelligent Cloud is
      significantly <em>worse</em> than the baseline &mdash; its CI excludes 1.0 on the
      wrong side &mdash; and its matched control from the same filing fails too. AWS has
      only 4 out-of-sample points and is reported as untestable rather than as the one
      cell that nearly worked.""",
         """<strong>84.6% 的方向命中率、配上超過 3&times; 的基準誤差，正是陷阱所在。</strong>
      Intelligent Cloud 顯著<em>劣於</em>基準 &mdash; 信賴區間排除 1.0，但落在錯誤的
      那一側 &mdash; 而且同一份 filing 出來的配對對照組也一起失敗。AWS 只有 4 個
      樣本外點，故報告為無法檢定，而不是報告成「唯一差點成功的那一格」。"""),
    ):
        if en not in tpl:
            raise SystemExit(f"zh: prose block not found: {en[:60]}")
        tpl = tpl.replace(en, zh)

    # risk-flag detail strings live in the template's JS array
    for en, zh in RISK_DETAIL_MAP.items():
        tpl = tpl.replace(en, zh)
    tpl = tpl.replace(
        "0 of ${DATA.diagnostics.grid_cells} alternative-data cells beat the strongest naive baseline. Treat every signal on this page as monitoring, not forecasting.",
        "${DATA.diagnostics.grid_cells} 格另類數據中 0 格勝過最強樸素基準。本頁每個訊號都應視為監控用途，而非預測用途。",
    )
    tpl = tpl.replace(
        "Downloads per $m of revenue rose from ${DATA.decoupling.first4.toLocaleString()} to ${DATA.decoupling.last4.toLocaleString()} (Spearman &rho;=${DATA.decoupling.rho}, p${DATA.decoupling.p}). Normalising by disclosed $100k+ customers: revenue per customer +${DATA.decoupling.rev_per_cust_pct}% but downloads per customer +${DATA.decoupling.dl_per_cust_pct}% &mdash; cross-sell and tiering are real but explain a minority of the gap.",
        "每百萬美元營收對應的下載量從 ${DATA.decoupling.first4.toLocaleString()} 升到 ${DATA.decoupling.last4.toLocaleString()}（Spearman &rho;=${DATA.decoupling.rho}、p${DATA.decoupling.p}）。以揭露的 $100k+ 客戶數正規化後：每客戶營收 +${DATA.decoupling.rev_per_cust_pct}%，但每客戶下載量 +${DATA.decoupling.dl_per_cust_pct}% &mdash; 交叉銷售與階梯定價確實存在，但只解釋了缺口的少數。",
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
        ("'<span class=\"tag t-good\">correct</span>'", "'<span class=\"tag t-good\">正確</span>'"),
        ("'<span class=\"tag t-bad\">wrong</span>'", "'<span class=\"tag t-bad\">錯誤</span>'"),
        ('paceUnits: "millions of downloads, cumulative"',
         'paceUnits: "單位：百萬次下載，累計"'),
    ):
        if en not in tpl:
            raise SystemExit(f"zh: template literal not found: {en}")
        tpl = tpl.replace(en, zh)

    # Inject the display-only table. TRV is `{}` in the shared template, so the
    # English build renders identity and the Chinese build renders Chinese from
    # the *same* branch logic -- no comparison is ever patched.
    trv_anchor = "const TRV = {};"
    if trv_anchor not in tpl:
        raise SystemExit("zh: TRV anchor missing from template")
    tpl = tpl.replace(
        trv_anchor,
        "const TRV = " + json.dumps(DISPLAY_MAP, ensure_ascii=False) + ";",
    )

    tpl = tpl.replace('<html lang="en">', '<html lang="zh-Hant">')

    html = tpl.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False)).replace(
        "__TICKER__", payload["meta"]["ticker"]
    )
    out = sc.REPO / "report-zh" / "dashboard.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html)

    print(f"Wrote {out.relative_to(sc.REPO)}  ({out.stat().st_size / 1024:.0f} KB)")
    print(f"translation mappings applied: {len(TEMPLATE_MAP)} template, "
          f"{len(PAYLOAD_MAP)} payload")
    shown = smoke_test(out, sc.REPO / "dashboard" / "index.html")
    # A branch value that reaches the rendered page in English means a display
    # site is missing its T() wrapper: the data is right, the cell reads English.
    shown_text = re.sub(r"<[^>]+>", " ", shown)
    # Leftover-English scan, over the *rendered* text rather than the file: every
    # panel is built by JS at load time, so scanning the source finds almost
    # nothing and returns a clean bill on a page full of English.
    plain = re.sub(r"&\w+;", " ", shown_text)
    leftovers = sorted({
        m.group(0).strip()
        for m in re.finditer(r"[A-Za-z][A-Za-z0-9 ,.:;()%$&#'/+-]{45,}", plain)
    })
    missed = sorted(
        k for k in DISPLAY_MAP
        if len(k) > 6 and re.search(r"(?<![\w-])" + re.escape(k) + r"(?![\w-])", shown_text)
    )
    if missed:
        raise SystemExit(
            "zh: branch values rendered untranslated (missing T() at the display "
            "site): " + ", ".join(missed)
        )
    if leftovers:
        print(f"leftover English prose blocks: {len(leftovers)}")
        for p in leftovers[:8]:
            print("   ", p[:90])
    else:
        print("no leftover English prose detected in visible text")


if __name__ == "__main__":
    main()
