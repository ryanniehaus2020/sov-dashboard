# Degreed Marketing Intelligence dashboard

A single, self-contained HTML dashboard with four tabs — **Share of Voice**,
**SEO**, **AEO**, and **Lead Capture**. Built from source: the layout/logic
live in `template.html`, the numbers live in `data/`, and `build.py` stitches
them into one file you can open in any browser (no server, no build chain, no
dependencies).

## Build

```bash
python3 build.py
```

Writes `dist/degreed-marketing-intelligence.html`. Open that file directly in a
browser. Python 3.8+ standard library only — nothing to install.

## Layout

```
sov-dashboard/
├── build.py            # python3 build.py  → dist/…html
├── template.html       # layout + CSS + JS; data injected at `const DATA = __DATA__`
├── data/
│   ├── snapshots.json  # SOV monthly data (LinkedIn + web share, per-brand context)
│   └── sections.json   # SEO / AEO / Lead Capture / PR notes / config
└── dist/
    └── degreed-marketing-intelligence.html   # built output (generated)
```

## Editing the data

Change the JSON in `data/`, then re-run `python3 build.py`. You never hand-edit
`dist/`.

- **`data/snapshots.json`** — one block per month (`2026-01` … `2026-06`). Each
  holds the four SOV `readings` (Skills / Learning / AI / Overall) plus a
  `context` map of per-brand LinkedIn followers, new followers, engagements, and
  web organic traffic.
- **`data/sections.json`** — the Degreed-only trend tabs and settings:
  - `seo` — GA organic sessions, GSC queries/clicks, SEMrush authority, branded/
    non-branded keyword tables.
  - `aeo` — Share of Authority, mentions/citations/cited pages, and
    `ai_sessions` (sessions from AI sources: ChatGPT, Gemini, Perplexity).
  - `leadcapture` — monthly HubSpot form submissions/views and top forms.
  - `prnotes` — qualitative PR notes (not part of the SOV score).
  - `config` — scoring weights, brand groups, brand-name map.

`build.py` drops a few upstream-only fields and rounds long decimals on the way
through, so the shipped file stays ~76 KB. Display precision is unaffected
(shares render to one decimal, SOV to one decimal).

## Methodology (as shipped)

- **Group SOV** = 0.5 × LinkedIn share + 0.5 × web share.
- **Overall SOV** = 0.4 × LinkedIn + 0.4 × web + 0.2 × AEO Share of Authority.
- **LinkedIn share** blends engagement-per-follower and new-followers-per-follower 50/50.
- **Web share** = share of organic search traffic (Degreed from Google Analytics
  Organic Search; competitors from SEMrush Compare Domains).
- SEO, AEO, and Lead Capture are Degreed-only trend tabs and never feed the SOV score.

## Data sources

| Tab | Source |
|-----|--------|
| SOV — social | LinkedIn Competitor Analytics Report |
| SOV — web | Degreed: GA Organic Search · competitors: SEMrush Compare Domains |
| SEO | GA (organic sessions) · Google Search Console (queries/clicks) · SEMrush (authority) |
| AEO | Microsoft Clarity (Share of Authority) · SEMrush AI Visibility · GA (AI sessions, per the WEB OKR metrics report) |
| Lead Capture | HubSpot Form Performance exports |

## Notes

- **AI sessions** come from a single consistent GA metric — sessions from AI
  sources (ChatGPT, Gemini, Perplexity) — for all six months, per the WEB OKR
  metrics report. Jan–Jun 2026: 296 / 260 / 298 / 348 / 346 / 608.
- SEMrush figures are estimated/rounded. Degreed's SEMrush contract ends
  **September 2026**; replacement tooling is being evaluated.

## Optional: headless smoke test

`build.py` already runs structural self-checks. If you want a runtime check
(clicks every tab, exercises the filters, asserts zero JS errors), run the built
file through jsdom:

```bash
npm i jsdom
node -e '
const fs=require("fs"),{JSDOM}=require("jsdom");
const dom=new JSDOM(fs.readFileSync("dist/degreed-marketing-intelligence.html","utf8"),
  {runScripts:"dangerously",pretendToBeVisual:true});
const w=dom.window,errs=[];w.onerror=m=>errs.push(""+m);
setTimeout(()=>{const d=w.document;
  ["sov","seo","aeo","leadcap"].forEach(t=>[...d.querySelectorAll("#tabbar button")]
    .find(b=>b.dataset.tab===t).click());
  console.log(errs.length?["FAIL",...errs]:"OK: no runtime errors");
},400);'
```
