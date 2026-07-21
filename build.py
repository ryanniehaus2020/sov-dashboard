#!/usr/bin/env python3
"""
Build the Degreed Marketing Intelligence dashboard.

    python3 build.py

Reads:   template.html, data/snapshots.json, data/sections.json
Writes:  dist/degreed-marketing-intelligence.html  (single self-contained file)

No third-party dependencies — Python 3.8+ standard library only.

What it does:
  1. Loads the layout (template.html) and the data (data/*.json).
  2. Prunes DATA fields the dashboard never reads and rounds long decimals,
     so the shipped file stays small.
  3. Injects the data as a JSON literal into the template's `const DATA = ...`.
  4. Conservatively minifies (strips comments + indentation; keeps newlines so
     JavaScript automatic-semicolon-insertion never breaks).
  5. Runs structural self-checks, then writes dist/.

Edit the data in data/snapshots.json and data/sections.json, then re-run.
The layout/logic lives in template.html.
"""
import json
import re
import datetime
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
TEMPLATE = ROOT / "template.html"
SNAPSHOTS = ROOT / "data" / "snapshots.json"
SECTIONS = ROOT / "data" / "sections.json"
OUT = ROOT / "dist" / "degreed-marketing-intelligence.html"

# Reading-level fields computed upstream but never read by the dashboard JS.
DROP_READING = {"raw", "members", "linkedin_members", "web_members"}
# Context columns the per-brand table actually renders.
KEEP_CTX_LINKEDIN = ("total_followers", "new_followers", "engagements")
KEEP_CTX_WEB = ("organic_traffic",)


def prune_snapshots(snapshots: dict) -> None:
    """Drop unused fields and round long floats in place."""
    for snap in snapshots.values():
        for rd in snap.get("readings", []):
            for k in list(rd.keys()):
                if k in DROP_READING:
                    del rd[k]
            for k in ("linkedin_share", "web_share", "aeo_share"):
                if isinstance(rd.get(k), float):
                    rd[k] = round(rd[k], 6)
            if isinstance(rd.get("sov"), float):
                rd["sov"] = round(rd["sov"], 4)
        for info in snap.get("context", {}).values():
            li = info.get("linkedin", {})
            info["linkedin"] = {k: li[k] for k in KEEP_CTX_LINKEDIN if k in li}
            web = info.get("web", {})
            info["web"] = {k: web[k] for k in KEEP_CTX_WEB if k in web}


def minify_html_css(s: str) -> str:
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)   # CSS comments
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)  # HTML comments
    lines = [re.sub(r"^\s+", "", ln.rstrip()) for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln != "")


def minify_js(s: str) -> str:
    # Conservative: strip block comments and whole-line // comments, strip
    # leading indentation, drop blank lines. Newlines are preserved so ASI
    # never changes behaviour.
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    out = []
    for ln in s.split("\n"):
        st = ln.strip()
        if st == "" or st.startswith("//"):
            continue
        out.append(st)
    return "\n".join(out)


def build() -> None:
    snapshots = json.loads(SNAPSHOTS.read_text(encoding="utf-8"))
    sections = json.loads(SECTIONS.read_text(encoding="utf-8"))

    prune_snapshots(snapshots)

    data = {
        "snapshots": snapshots,
        "prnotes": sections["prnotes"],
        "config": sections["config"],
        "seo": sections["seo"],
        "aeo": sections["aeo"],
        "leadcapture": sections["leadcapture"],
        "provenance": sections["provenance"],
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }

    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    assert json.loads(data_json) == data, "DATA round-trip failed"
    assert "__DATA__" not in data_json, "data unexpectedly contains __DATA__"

    tmpl = TEMPLATE.read_text(encoding="utf-8")
    assert tmpl.count("__DATA__") == 1, f"expected 1 __DATA__ placeholder, found {tmpl.count('__DATA__')}"
    html = tmpl.replace("__DATA__", data_json)

    # Minify: split out <script> so HTML/CSS get aggressive treatment and JS
    # gets the conservative treatment.
    m = re.search(r"(<script>)(.*)(</script>)", html, re.S)
    assert m, "could not locate <script> block"
    pre, scr_open, js, scr_close, post = (
        html[: m.start(1)], m.group(1), m.group(2), m.group(3), html[m.end(3):],
    )
    html = minify_html_css(pre) + scr_open + "\n" + minify_js(js) + "\n" + scr_close + minify_html_css(post)

    # ---- self-checks ----
    assert "__DATA__" not in html
    assert html.count("<script>") == 1 and html.count("</script>") == 1
    m2 = re.search(r"const DATA = (\{.*?\});", html, re.S)
    assert m2, "could not re-extract DATA after minify"
    json.loads(m2.group(1))  # raises if the injected literal is not valid JSON
    for p in ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]:
        assert f'"{p}"' in html, f"missing period {p}"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    kb = len(html.encode("utf-8")) / 1024
    ai = [x["sessions"] for x in sections["aeo"]["ai_sessions"]]
    print(f"OK  wrote {OUT.relative_to(ROOT)}  ({kb:.1f} KB)")
    print(f"    periods : {', '.join(sorted(snapshots))}")
    print(f"    AI sessions Jan-Jun : {ai}")


if __name__ == "__main__":
    try:
        build()
    except AssertionError as e:
        print(f"BUILD FAILED: {e}", file=sys.stderr)
        sys.exit(1)
