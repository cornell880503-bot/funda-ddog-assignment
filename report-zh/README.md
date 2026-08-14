# 中文版交付物

英文版為正式交付版本，本資料夾是逐份對照的中文譯本。**兩版所有數字完全一致**，中文版不重新計算任何數值。

| 檔案 | 對應英文版 | 內容 |
|---|---|---|
| `report.md` | `report/report.md` | 主報告，4.8 頁 |
| `slides.md` | `report/slides.md` | 8 張投影片，含講稿註記 |
| `qa_appendix.md` | `report/qa_appendix.md` | Q&A 附錄，15 題 |
| `dashboard.html` | `dashboard/index.html` | Dashboard 原型，單檔、零外部依賴，雙擊即開 |

## 中文版 dashboard 怎麼產生的

不維護兩套模板。`src/render_dashboard_zh.py` 對英文模板套用一組**帶斷言的翻譯映射**：

- 69 條模板字串 + 48 條 payload 字串
- 任何一條來源字串找不到就**直接報錯**，不會默默留下英文
- 產出後再做一次殘留英文掃描

重新產生：

```bash
python src/render_dashboard_zh.py
```

## 術語對照

| 英文 | 中文 |
|---|---|
| guidance | 指引 |
| beat (vs guidance) | 超額 |
| baseline | 基準 |
| walk-forward | 逐步前推驗證（保留原詞） |
| out-of-sample | 樣本外 |
| placebo | 安慰劑 |
| negative control | 負對照組 |
| as-of / vintage | 時點／vintage |
| non-stationary | 非定態 |
| permutation null | 置換虛無分布 |
| hit rate | 命中率 |
| RMSE ratio | 誤差比 |
| decoupling | 脫鉤 |
| divergence monitor | 背離監控器 |
| outage | 資料中斷（保留原詞） |
| imputation | 插補 |
| look-ahead bias | 前視偏誤 |
