"""Render both slide decks into one reviewable HTML page.

The decks live as Markdown so they stay diffable and are the source the PDF is
generated from. That makes them awkward to *check*, which is what this page is
for: both languages side by side under a toggle, presenter notes visually
separated from slide content (they are not part of the printed deck), and a word
count per slide so density problems are visible rather than discovered on stage.

Not a deliverable -- a review surface. The submitted artefacts remain
report/slides.md (via the generated deck) and dashboard/index.html.

    python src/render_slide_review.py   ->  report/slide-review.html
"""

from __future__ import annotations

import html
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
DECKS = [
    ("en", "English", REPO / "report" / "slides.md", r"^## Slide "),
    ("zh", "中文", REPO / "report-zh" / "slides.md", r"^## 第 "),
]


def emphasis(s: str) -> str:
    """Scan for * and ** rather than pattern-matching them.

    The decks contain `**-0.808 *(p<0.001)***` -- italic nested inside bold,
    closing as a run of three stars. A `\\*\\*(...)\\*\\*` regex cannot parse that:
    it either stops at the inner star or swallows the closing pair, and the
    figure renders with literal asterisks around it.
    """
    out, i, strong, em = [], 0, False, False
    while i < len(s):
        if s.startswith("***", i):
            if strong and em:
                out.append("</em></strong>")
            elif not strong and not em:
                out.append("<strong><em>")
            else:  # one of the two is open -- close it, open the other
                out.append("</strong><em>" if strong else "</em><strong>")
            strong, em = not strong, not em
            i += 3
        elif s.startswith("**", i):
            out.append("</strong>" if strong else "<strong>")
            strong = not strong
            i += 2
        elif s[i] == "*":
            out.append("</em>" if em else "<em>")
            em = not em
            i += 1
        else:
            out.append(s[i])
            i += 1
    if em:
        out.append("</em>")
    if strong:
        out.append("</strong>")
    return "".join(out)


def inline(s: str) -> str:
    """Bold / italic / code / links. Escape first, then re-introduce markup."""
    s = html.escape(s, quote=False)
    codes: list[str] = []

    def stash(m: re.Match) -> str:
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    s = re.sub(r"`([^`]+)`", stash, s)  # protect code spans from the * scanner
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    s = emphasis(s)
    return re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{codes[int(m.group(1))]}</code>", s)


def table(rows: list[str]) -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    head, body = cells[0], cells[2:]
    th = "".join(f"<th>{inline(c)}</th>" for c in head)
    tb = "".join(
        "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body
    )
    return f'<div class="tw"><table><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table></div>'


def block(md: str) -> str:
    """Markdown subset: tables, blockquotes, lists, paragraphs, rules."""
    out, lines, i = [], md.split("\n"), 0
    while i < len(lines):
        ln = lines[i]
        if ln.strip().startswith("|"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                buf.append(lines[i])
                i += 1
            if len(buf) >= 2:
                out.append(table(buf))
            continue
        if ln.strip().startswith(">"):
            buf = []
            while i < len(lines) and (
                lines[i].strip().startswith(">") or (buf and lines[i].strip())
            ):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            text = "\n".join(buf).strip()
            paras = "".join(
                f"<p>{inline(p.strip())}</p>" for p in text.split("\n\n") if p.strip()
            )
            out.append(f'<aside class="notes"><span class="notes-tag">notes</span>{paras}</aside>')
            continue
        if re.match(r"^\s*[-*]\s+", ln):
            buf = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                buf.append(re.sub(r"^\s*[-*]\s+", "", lines[i]))
                i += 1
            out.append("<ul>" + "".join(f"<li>{inline(b)}</li>" for b in buf) + "</ul>")
            continue
        if ln.strip() in ("---", "***"):
            i += 1
            continue
        if ln.strip():
            buf = []
            while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith(("|", ">", "-", "#")):
                buf.append(lines[i].strip())
                i += 1
            if buf:
                out.append(f"<p>{inline(' '.join(buf))}</p>")
                continue
        i += 1
    return "".join(out)


def deck(path: pathlib.Path, split: str) -> tuple[str, str, list[str]]:
    raw = path.read_text()
    parts = re.split(f"({split})", raw, flags=re.M)
    intro = parts[0]
    title = next((l.lstrip("# ").strip() for l in intro.split("\n") if l.startswith("# ")), "")
    sub = next((l.lstrip("# ").strip() for l in intro.split("\n") if l.startswith("### ")), "")
    chunks, warnings = [], []
    for k in range(1, len(parts), 2):
        body = parts[k] + parts[k + 1]
        head, _, rest = body.partition("\n")
        head = head.lstrip("# ").strip()
        num = re.search(r"(\d+)", head)
        num = num.group(1) if num else str(k // 2 + 1)
        name = re.sub(r"^(Slide|第)\s*\d+\s*(張)?\s*[—-]\s*", "", head)
        words = len(re.findall(r"\S+", re.sub(r"(?m)^>.*$", "", rest)))
        if words > 300:
            warnings.append(f"{num}: {words}w")
        chunks.append(
            f'<section class="slide" id="{path.parent.name}-{num}">'
            f'<div class="rail"><span class="num">{num}</span>'
            f'<span class="wc{" over" if words > 300 else ""}">{words}w</span></div>'
            f'<div class="body"><h2>{inline(name)}</h2>{block(rest)}</div></section>'
        )
    return f"<header class=\"deck-head\"><h1>{inline(title)}</h1><p>{inline(sub)}</p></header>" + "".join(
        chunks
    ), title, warnings


panes, meta = [], []
for key, label, path, split in DECKS:
    body, title, warn = deck(path, split)
    panes.append(f'<div class="pane" data-lang="{key}">{body}</div>')
    meta.append((key, label, len(re.findall(split, path.read_text(), re.M)), warn))

CSS = """
:root{
  --ground:#F6F8F7; --surface:#FFFFFF; --sunk:#EDF1EF;
  --ink:#141D1B; --body:#2C3A37; --muted:#5E6E6A; --faint:#8A9995;
  --rule:#D6DEDB; --hair:#E6ECEA;
  --accent:#15665A; --accent-soft:#DCEBE6; --signal:#A6421C;
  --shadow:0 1px 2px rgba(20,29,27,.05),0 8px 24px -16px rgba(20,29,27,.22);
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ground:#0C1211; --surface:#131B19; --sunk:#0F1716;
    --ink:#E6EDEA; --body:#C4D0CC; --muted:#8DA09B; --faint:#6B7C78;
    --rule:#243130; --hair:#1C2725;
    --accent:#5FC0A6; --accent-soft:#16302B; --signal:#E28158;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px -16px rgba(0,0,0,.7);
  }
}
:root[data-theme="dark"]{
  --ground:#0C1211; --surface:#131B19; --sunk:#0F1716;
  --ink:#E6EDEA; --body:#C4D0CC; --muted:#8DA09B; --faint:#6B7C78;
  --rule:#243130; --hair:#1C2725;
  --accent:#5FC0A6; --accent-soft:#16302B; --signal:#E28158;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px -16px rgba(0,0,0,.7);
}
*{box-sizing:border-box;}
body{
  margin:0;background:var(--ground);color:var(--body);
  font:16px/1.62 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang TC",
       "Hiragino Sans TC","Microsoft JhengHei",sans-serif;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1000px;margin:0 auto;padding:0 24px 96px;}

.bar{
  position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--ground) 88%,transparent);
  backdrop-filter:blur(10px);border-bottom:1px solid var(--hair);
}
.bar-in{max-width:1000px;margin:0 auto;padding:11px 24px;display:flex;
  align-items:center;gap:16px;flex-wrap:wrap;}
.brand{font-weight:650;color:var(--ink);letter-spacing:-.01em;}
.brand span{color:var(--faint);font-weight:450;}
.spacer{flex:1;}
.toggle{display:flex;background:var(--sunk);border:1px solid var(--rule);
  border-radius:7px;padding:2px;gap:2px;}
.toggle button{
  font:inherit;font-size:13px;font-weight:550;padding:5px 13px;border:0;border-radius:5px;
  background:transparent;color:var(--muted);cursor:pointer;transition:background .12s,color .12s;
}
.toggle button[aria-pressed="true"]{background:var(--surface);color:var(--ink);box-shadow:var(--shadow);}
.toggle button:focus-visible{outline:2px solid var(--accent);outline-offset:1px;}

.deck-head{padding:56px 0 20px;border-bottom:1px solid var(--rule);margin-bottom:8px;}
.deck-head h1{
  font-family:Georgia,"Songti TC","Noto Serif CJK TC",serif;
  font-size:clamp(28px,4.2vw,40px);line-height:1.15;margin:0 0 10px;
  color:var(--ink);font-weight:600;letter-spacing:-.02em;text-wrap:balance;
}
.deck-head p{margin:0;color:var(--muted);font-size:14.5px;}

.pane[hidden]{display:none;}

.slide{
  display:grid;grid-template-columns:60px 1fr;gap:22px;
  padding:30px 0;border-bottom:1px solid var(--hair);
}
.rail{display:flex;flex-direction:column;align-items:flex-end;gap:6px;
  position:sticky;top:64px;align-self:start;}
.num{
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:26px;font-weight:600;color:var(--faint);
  font-variant-numeric:tabular-nums;line-height:1;
}
.wc{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:10.5px;
  color:var(--faint);letter-spacing:.03em;}
.wc.over{color:var(--signal);font-weight:600;}

.body h2{
  font-family:Georgia,"Songti TC","Noto Serif CJK TC",serif;
  font-size:22px;line-height:1.3;margin:2px 0 16px;color:var(--ink);
  font-weight:600;letter-spacing:-.012em;text-wrap:balance;
}
.body p{margin:0 0 13px;max-width:66ch;}
.body strong{color:var(--ink);font-weight:640;}
.body em{color:var(--body);}
.body code{
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.87em;
  background:var(--sunk);border:1px solid var(--hair);border-radius:4px;padding:1px 5px;
}
.body ul{margin:0 0 13px;padding-left:19px;max-width:66ch;}
.body li{margin-bottom:5px;}

.tw{overflow-x:auto;margin:0 0 16px;border:1px solid var(--rule);border-radius:8px;
  background:var(--surface);box-shadow:var(--shadow);}
table{border-collapse:collapse;width:100%;font-size:13.5px;}
th{
  text-align:left;padding:9px 13px;background:var(--sunk);color:var(--muted);
  font-weight:600;font-size:11px;letter-spacing:.055em;text-transform:uppercase;
  border-bottom:1px solid var(--rule);white-space:nowrap;
}
td{padding:10px 13px;border-bottom:1px solid var(--hair);vertical-align:top;
  font-variant-numeric:tabular-nums;line-height:1.5;}
tbody tr:last-child td{border-bottom:0;}
td strong{color:var(--ink);}

.notes{
  margin:6px 0 13px;padding:13px 15px 13px 17px;background:var(--sunk);
  border-left:2px solid var(--accent);border-radius:0 7px 7px 0;max-width:66ch;
}
.notes-tag{
  display:block;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:10px;letter-spacing:.13em;text-transform:uppercase;
  color:var(--accent);margin-bottom:6px;font-weight:600;
}
.notes p{margin:0 0 8px;font-size:14px;color:var(--muted);}
.notes p:last-child{margin-bottom:0;}

.foot{margin-top:32px;padding-top:20px;border-top:1px solid var(--rule);
  font-size:13px;color:var(--faint);max-width:66ch;}
.foot code{font-family:ui-monospace,Menlo,monospace;font-size:.9em;}

@media (max-width:640px){
  .slide{grid-template-columns:1fr;gap:8px;}
  .rail{flex-direction:row;align-items:baseline;gap:10px;position:static;}
  .num{font-size:19px;}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important;}}
"""

tabs = "".join(
    f'<button data-target="{k}" aria-pressed="{"true" if k == "en" else "false"}">{lab}'
    f' <span style="opacity:.55">{n}</span></button>'
    for k, lab, n, _ in meta
)
warn_line = "; ".join(
    f"{lab} " + (", ".join(w) if w else "none") for _, lab, _, w in meta
)

DOC = f"""<title>DDOG Nowcast Deck</title>
<style>{CSS}</style>
<div class="bar"><div class="bar-in">
  <span class="brand">DDOG Nowcast Deck <span>&middot; review copy</span></span>
  <span class="spacer"></span>
  <div class="toggle" role="group" aria-label="Language">{tabs}</div>
</div></div>
<div class="wrap">
  {"".join(panes)}
  <p class="foot">Rendered from <code>report/slides.md</code> and
  <code>report-zh/slides.md</code>. Grey blocks are presenter notes and are not
  part of the printed deck. Word counts exclude notes; slides over 300 words are
  flagged &mdash; currently {warn_line}. The dashboard is a separate artefact
  (<code>dashboard/index.html</code>).</p>
</div>
<script>
const panes = [...document.querySelectorAll(".pane")];
const btns  = [...document.querySelectorAll(".toggle button")];
function show(key) {{
  panes.forEach(p => p.hidden = p.dataset.lang !== key);
  btns.forEach(b => b.setAttribute("aria-pressed", String(b.dataset.target === key)));
}}
btns.forEach(b => b.addEventListener("click", () => show(b.dataset.target)));
show("en");
</script>
"""

out = REPO / "report" / "slide-review.html"
out.write_text(DOC)
print(f"Wrote {out.relative_to(REPO)}  ({out.stat().st_size / 1024:.0f} KB)")
for _, lab, n, w in meta:
    print(f"  {lab}: {n} slides, over-300w: {', '.join(w) if w else 'none'}")
