#!/usr/bin/env python3
"""
Driver script that reads the COMBINED (Jan-Jun 2026, one-sheet-per-source)
Google Drive exports directly and feeds calc.py, regenerating
data/snapshots.json and data/sections.json.

This replaces the one-file-per-month assumption baked into parse.py's
original parse_linkedin()/parse_semrush() functions (those still work fine
for their historical single-file-per-month inputs; they are simply not used
here since the current source files bundle all 6 months in one sheet).
parse_aeo() IS reused unchanged since the AI Visibility export's indented
grid layout didn't change shape.

Run:
    python3 data/generate.py
Then:
    python3 build.py
"""
import csv
import json
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))          # .../data
REPO = os.path.dirname(ROOT)                                # repo root
RAW = os.path.join(ROOT, "raw")

SECTIONS_PATH = os.path.join(ROOT, "sections.json")
SNAPSHOTS_PATH = os.path.join(ROOT, "snapshots.json")

import sys
sys.path.insert(0, ROOT)
import calc          # noqa: E402  (repo module, do not modify)
import parse         # noqa: E402  (repo module; only parse_aeo() reused)

PERIODS = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
MONTH_LABEL = {"01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr",
               "05": "May", "06": "Jun"}

# Degreed's own organic-search traffic comes from Google Analytics (not
# Semrush -- the SEMrush export's degreed.com row has no Organic Traffic
# column populated). These are the existing, previously-verified GA figures
# already on file in sections.json; carried forward here since the raw
# GA export itself isn't one of the combined Drive files we were handed.
GA_ORGANIC_BY_YM = {
    "2026-01": 10813, "2026-02": 10195, "2026-03": 10248,
    "2026-04": 8692, "2026-05": 8001, "2026-06": 8817,
}


def _clean_num(text):
    if text is None:
        return None
    text = str(text).strip().replace(",", "").replace("%", "").replace("$", "")
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(text):
    n = _clean_num(text)
    return int(round(n)) if n is not None else None


def _mdY_to_ym(text):
    """'01/01/2026' or '01/31/2026' -> '2026-01'."""
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", text.strip())
    if not m:
        return None
    mm, _dd, yyyy = m.groups()
    return "%s-%02d" % (yyyy, int(mm))


def _Ymd_to_ym(text):
    """'2026-01-01' -> '2026-01'."""
    m = re.match(r"^(\d{4})-(\d{2})-\d{2}$", text.strip())
    if not m:
        return None
    return "%s-%s" % m.groups()


def _any_date_to_ym(text):
    ym = _mdY_to_ym(text)
    if ym:
        return ym
    return _Ymd_to_ym(text)


# --------------------------------------------------------------------------
# LinkedIn combined -> per-period rows_by_brand
# --------------------------------------------------------------------------
def parse_linkedin_combined(path, config):
    label_map = {}
    for brand, labels in config["brand_name_map"].items():
        label = labels.get("linkedin")
        if label:
            label_map[label.strip().lower()] = brand

    by_period = {p: {} for p in PERIODS}
    period_bounds = {}  # ym -> (start_label, end_label)
    extras_skipped = set()

    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ym = _any_date_to_ym(row["Reporting Start Date"])
            if ym is None or ym not in by_period:
                continue
            company = (row.get("Company") or "").strip()
            key = label_map.get(company.lower())
            if key is None:
                if company:
                    extras_skipped.add(company)
                continue
            by_period[ym][key] = {
                "total_followers": _to_int(row.get("Total Followers")),
                "new_followers": _to_int(row.get("New Followers")),
                "engagements": _to_int(row.get("Total post engagements")),
                "total_posts": _to_int(row.get("Total posts")),
            }
            if ym not in period_bounds:
                y, mo = ym.split("-")
                label = "%s %s" % (MONTH_LABEL[mo], y)
                period_bounds[ym] = (label, label)

    return by_period, period_bounds, sorted(extras_skipped)


# --------------------------------------------------------------------------
# Semrush combined -> per-period rows_by_brand (web channel)
# --------------------------------------------------------------------------
def parse_semrush_combined(path, config):
    label_map = {}
    for brand, labels in config["brand_name_map"].items():
        label = labels.get("web")
        if label:
            label_map[label.strip().lower()] = brand

    degreed_brand = config["brand"]

    by_period = {p: {} for p in PERIODS}
    authority_latest = {}   # brand -> (ym, score)  keep latest

    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ym = _any_date_to_ym(row["Reporting Start Date"])
            if ym is None or ym not in by_period:
                continue
            domain = (row.get("Domain") or "").strip()
            key = label_map.get(domain.lower())
            if key is None:
                continue

            organic_traffic = _to_int(row.get("Organic Traffic"))
            authority = _to_int(row.get("Authority Score"))

            if key == degreed_brand:
                # degreed.com's Organic Traffic column is blank in this
                # export; unique_visitors for the web-share math comes from
                # GA organic traffic instead (per parse.py's original design
                # of GA-for-Degreed / SEMrush-for-competitors).
                uv = GA_ORGANIC_BY_YM.get(ym)
                organic_source = "Google Analytics (Organic Search)"
            else:
                uv = organic_traffic
                organic_source = "SEMrush"

            by_period[ym][key] = {
                "domain": domain,
                "period": "%s %s" % (MONTH_LABEL[ym.split("-")[1]], ym.split("-")[0]),
                "unique_visitors": uv,
                "organic_traffic": uv,
                "organic_source": organic_source,
                "authority_score": authority,
            }
            if authority is not None:
                prev = authority_latest.get(key)
                if prev is None or ym >= prev[0]:
                    authority_latest[key] = (ym, authority)

    return by_period, authority_latest


# --------------------------------------------------------------------------
# GSC queries/clicks (one row per month) -> seo.gsc
# --------------------------------------------------------------------------
def parse_gsc_queries_clicks(path):
    out = {}
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ym = _any_date_to_ym(row["Reporting Start Date"])
            if ym is None:
                continue
            y, mo = ym.split("-")
            out[ym] = {
                "ym": ym,
                "month_label": "%s %s" % (MONTH_LABEL[mo], y),
                "queries": _to_int(row.get("# of Queries")),
                "clicks": _to_int(row.get("# of Clicks")),
            }
    return out


# --------------------------------------------------------------------------
# GA LLM traffic -> aeo.ai_sessions (sum Sessions per month)
# --------------------------------------------------------------------------
def parse_ga_llm_traffic(path):
    totals = {}  # ym -> sessions sum
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            month_num = row.get("Month")
            try:
                mo = int(month_num)
            except (TypeError, ValueError):
                continue
            ym = "2026-%02d" % mo
            sess = _to_int(row.get("Sessions")) or 0
            totals[ym] = totals.get(ym, 0) + sess
    return totals


# --------------------------------------------------------------------------
# GSC branded / non-branded keyword CSVs (June 2026 only) -> top-N by clicks
# --------------------------------------------------------------------------
def parse_gsc_branded(path, top_n=15):
    rows = []
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            clicks = _to_int(row.get("Clicks"))
            if clicks is None:
                continue
            rows.append({
                "q": (row.get("Queries (last month)") or "").strip(),
                "clicks": clicks,
                "impr": _to_int(row.get("Impressions")),
                "pos": round(_clean_num(row.get("Average Position")), 2)
                if _clean_num(row.get("Average Position")) is not None else None,
                "ctr": round(_clean_num(row.get("Site CTR")) * 100, 2)
                if _clean_num(row.get("Site CTR")) is not None else None,
            })
    rows.sort(key=lambda r: r["clicks"], reverse=True)
    return rows[:top_n]


def parse_gsc_nonbranded(path, top_n=15):
    rows = []
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            clicks = _to_int(row.get("Url Clicks"))
            if clicks is None:
                continue
            rows.append({
                "q": (row.get("Queries (last month)") or "").strip(),
                "clicks": clicks,
                "impr": _to_int(row.get("Impressions")),
                "pos": round(_clean_num(row.get("Avg Position")), 2)
                if _clean_num(row.get("Avg Position")) is not None else None,
                "ctr": round(_clean_num(row.get("URL CTR")) * 100, 2)
                if _clean_num(row.get("URL CTR")) is not None else None,
            })
    rows.sort(key=lambda r: r["clicks"], reverse=True)
    return rows[:top_n]


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main():
    with open(SECTIONS_PATH, "r", encoding="utf-8") as f:
        old_sections = json.load(f)
    config = old_sections["config"]
    degreed_brand = config["brand"]

    # ---- Step 2/3: parse combined sources -------------------------------
    li_by_period, li_bounds, li_extras = parse_linkedin_combined(
        os.path.join(RAW, "linkedin_competitor_combined_2026.csv"), config)
    web_by_period, authority_latest = parse_semrush_combined(
        os.path.join(RAW, "semrush_domain_comparison_combined_2026.csv"), config)
    aeo = parse.parse_aeo(os.path.join(RAW, "ai_visibility_semrush.csv"))
    gsc_by_ym = parse_gsc_queries_clicks(
        os.path.join(RAW, "gsc_queries_clicks_2026.csv"))
    ai_sessions_by_ym = parse_ga_llm_traffic(
        os.path.join(RAW, "ga_llm_traffic_2026.csv"))
    branded = parse_gsc_branded(
        os.path.join(RAW, "gsc_branded_keywords_2026_06.csv"), top_n=15)
    nonbranded = parse_gsc_nonbranded(
        os.path.join(RAW, "gsc_nonbranded_keywords_2026_06.csv"), top_n=15)

    flags_report = []
    if li_extras:
        flags_report.append("LinkedIn: pages not in brand_name_map, skipped -> %s"
                             % ", ".join(li_extras))

    # ---- Step 4: build snapshots ------------------------------------------
    snapshots = {}
    for ym in PERIODS:
        li_rows = li_by_period.get(ym, {})
        web_rows = web_by_period.get(ym, {})

        missing_li = [b for b in config["brand_name_map"] if b not in li_rows]
        missing_web = [b for b in config["brand_name_map"]
                       if config["brand_name_map"][b].get("web") and b not in web_rows]
        if missing_li:
            flags_report.append("%s: LinkedIn missing brand(s) -> %s"
                                 % (ym, ", ".join(missing_li)))
        if missing_web:
            flags_report.append("%s: Web missing brand(s) -> %s"
                                 % (ym, ", ".join(missing_web)))

        aeo_share = aeo["soa_by_ym"].get(ym)
        readings = calc.compute_all(config, li_rows, web_rows, aeo_share=aeo_share)

        label = li_bounds.get(ym, ("%s %s" % (MONTH_LABEL[ym.split("-")[1]],
                                               ym.split("-")[0]),) * 2)
        month_label = "%s %s" % (MONTH_LABEL[ym.split("-")[1]], ym.split("-")[0])

        context = {}
        all_brands = set(li_rows) | set(web_rows)
        for b in all_brands:
            li = li_rows.get(b, {})
            web = web_rows.get(b, {})
            context[b] = {
                "linkedin": {
                    "total_followers": li.get("total_followers"),
                    "new_followers": li.get("new_followers"),
                    "engagements": li.get("engagements"),
                    "total_posts": li.get("total_posts"),
                },
                "web": {
                    "domain": web.get("domain"),
                    "period": web.get("period"),
                    "organic_traffic": web.get("organic_traffic"),
                    "organic_source": web.get("organic_source"),
                },
            }

        snapshots[ym] = {
            "period": ym,
            "linkedin": {
                "start": month_label,
                "end": month_label,
                "source": "LinkedIn Competitor Analytics Report",
            },
            "web": {
                "period_label": month_label,
                "carried_forward": False,
                "source_period": ym,
            },
            "aeo": {
                "share_of_authority": aeo_share,
                "included_in_overall": aeo_share is not None,
            },
            "readings": readings,
            "context": context,
        }

    # ---- Step 5: seo block --------------------------------------------
    seo_months = []
    for ym in PERIODS:
        seo_months.append({
            "ym": ym,
            "month_label": "%s %s" % (MONTH_LABEL[ym.split("-")[1]], ym.split("-")[0]),
            "ga_organic": GA_ORGANIC_BY_YM[ym],
            "authority": authority_latest.get(degreed_brand, (None, 38))[1]
            if degreed_brand in authority_latest else 38,
        })

    gsc_list = []
    for ym in PERIODS:
        row = gsc_by_ym.get(ym)
        if row:
            gsc_list.append(row)
        else:
            flags_report.append("%s: GSC queries/clicks missing" % ym)

    competitor_authority = []
    for brand in config["brand_name_map"]:
        if brand in authority_latest:
            competitor_authority.append({"brand": brand, "score": authority_latest[brand][1]})
    competitor_authority.sort(key=lambda r: r["score"], reverse=True)

    seo = {
        "domain": config["brand_name_map"][degreed_brand]["web"],
        "latest_ym": PERIODS[-1],
        "gsc_latest_label": "Jun 2026",
        "months": seo_months,
        "gsc": gsc_list,
        "competitor_authority": competitor_authority,
        "branded": branded,
        "nonbranded": nonbranded,
    }

    # ---- Step 6: aeo block --------------------------------------------
    ai_sessions = []
    for ym in PERIODS:
        sess = ai_sessions_by_ym.get(ym)
        if sess is None:
            flags_report.append("%s: GA LLM traffic missing, ai_sessions omitted" % ym)
            continue
        ai_sessions.append({
            "ym": ym,
            "month_label": "%s %s" % (MONTH_LABEL[ym.split("-")[1]], ym.split("-")[0]),
            "sessions": sess,
            "official": True,
        })

    aeo_block = {
        "months": aeo["months"],
        "soa_by_ym": aeo["soa_by_ym"],
        "ai_sessions": ai_sessions,
        "latest_ym": aeo["latest_ym"],
    }

    # ---- Step 7: prnotes come from data/pr-notes.json, hand-maintained -----
    # (kept as its own small file so non-engineers can edit it directly on
    # GitHub without touching the generated sections.json). Falls back to
    # whatever was already in sections.json if the file isn't there yet.
    pr_notes_path = os.path.join(ROOT, "pr-notes.json")
    if os.path.exists(pr_notes_path):
        with open(pr_notes_path, "r", encoding="utf-8-sig") as f:
            pr_notes_raw = json.load(f)
        prnotes = {k: v for k, v in pr_notes_raw.items() if not k.startswith("_")}
    else:
        prnotes = old_sections["prnotes"]

    # ---- Step 8: provenance -------------------------------------------
    provenance = [
        {
            "tab": "Lead Capture",
            "source": "HubSpot Form Performance (combined)",
            "file": "data/raw/hubspot_form_report_combined_2026.csv",
            "drive_file_id": "14f9_bPXv6kfqf1l91-e5ExCGaO1baQep4mAzGYjsD2E",
            "drive_folder_id": "1p1-v6sq-x0yweVWctfmrRmsI8lIrKGUP",
            "latest": "2026-06",
        },
        {
            "tab": "AEO",
            "source": "SEMrush AI Visibility + Microsoft Clarity SoA",
            "file": "data/raw/ai_visibility_semrush.csv",
            "drive_file_id": "1ydetL7b7u5oudofQcq1K8w2hEhYsa-Z1uDkOInB8Vw8",
            "drive_folder_id": "1IoYyEVT-SEEc7WUSz52CzHIeiEwzzDni",
            "latest": "2026-06",
        },
        {
            "tab": "SEO, Share of Voice",
            "source": "SEMrush Domain Comparison (combined)",
            "file": "data/raw/semrush_domain_comparison_combined_2026.csv",
            "drive_file_id": "1hFLxcp3gOMUE6BzlUwy9cb1oCALhFFrTUNRbYm5UE0I",
            "drive_folder_id": "1oz6gwcGNpEVDQREQhSDx88yR0-2RitGh",
            "latest": "2026-06",
        },
        {
            "tab": "Share of Voice",
            "source": "LinkedIn Competitor Analytics (combined)",
            "file": "data/raw/linkedin_competitor_combined_2026.csv",
            "drive_file_id": "13Cp5704x_8jEiBLyTD-6Y3VlUA0WYkNQUGg3IdGiBhI",
            "drive_folder_id": "1jw_9Zp730SMphZPtqv2T4j0ELZnSk2l1",
            "latest": "2026-06",
        },
        {
            "tab": "SEO",
            "source": "Google Search Console -- Queries & Clicks",
            "file": "data/raw/gsc_queries_clicks_2026.csv",
            "drive_file_id": "1J5WEy4RUWbyoLMfs4K4FZ48bNMQr7XIJV9qibSxLo8A",
            "drive_folder_id": "1vYV_476BRKE8A0NsmDbaIoTpXQczgie2",
            "latest": "2026-06",
        },
        {
            "tab": "AEO",
            "source": "Google Analytics -- LLM/AI Referral Traffic",
            "file": "data/raw/ga_llm_traffic_2026.csv",
            "drive_file_id": "1c-3L6Z0HdwJBcX54Au2VvzoJn3IfrNVt9VVJWww7VHU",
            "drive_folder_id": "1d7_NGFK0MU5jYTnDM6aiRUutazA_7SLq",
            "latest": "2026-06",
        },
        {
            "tab": "SEO",
            "source": "Google Search Console -- Branded Keywords (Jun 2026)",
            "file": "data/raw/gsc_branded_keywords_2026_06.csv",
            "drive_file_id": "1jXy2-SEnRFVUFndzyqvJO6HxyLFLvYC6Jh-64Vnaslc",
            "drive_folder_id": "1vYV_476BRKE8A0NsmDbaIoTpXQczgie2",
            "latest": "2026-06",
        },
        {
            "tab": "SEO",
            "source": "Google Search Console -- Non-Branded Keywords (Jun 2026)",
            "file": "data/raw/gsc_nonbranded_keywords_2026_06.csv",
            "drive_file_id": "1xDi56gcU1ZX07aW1fUpk3riKJTcNzhR9Y34qC5lWdQQ",
            "drive_folder_id": "1vYV_476BRKE8A0NsmDbaIoTpXQczgie2",
            "latest": "2026-06",
        },
    ]

    sections = {
        "config": config,
        "prnotes": prnotes,
        "seo": seo,
        "aeo": aeo_block,
        "leadcapture": old_sections["leadcapture"],
        "provenance": provenance,
    }

    # ---- Step 9: write ---------------------------------------------------
    with open(SNAPSHOTS_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshots, f, ensure_ascii=False, indent=2)
        f.write("\n")
    with open(SECTIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(sections, f, ensure_ascii=False, indent=2)
        f.write("\n")

    # ---- Step 10: self-check ----------------------------------------------
    with open(SNAPSHOTS_PATH, "r", encoding="utf-8") as f:
        raw = f.read()
        assert not raw.startswith("﻿"), "snapshots.json has a BOM"
        snap_check = json.loads(raw)
    with open(SECTIONS_PATH, "r", encoding="utf-8") as f:
        raw = f.read()
        assert not raw.startswith("﻿"), "sections.json has a BOM"
        sec_check = json.loads(raw)

    for p in PERIODS:
        assert p in snap_check, "missing period %s in snapshots.json" % p
    for key in ("seo", "aeo", "leadcapture", "provenance", "config", "prnotes"):
        assert key in sec_check, "missing section %s in sections.json" % key

    print("Self-check OK.")
    print("Periods:", sorted(snap_check.keys()))
    print("AI sessions Jan-Jun:", [x["sessions"] for x in sec_check["aeo"]["ai_sessions"]])
    if flags_report:
        print("\nFlags raised during parsing:")
        for msg in flags_report:
            print(" -", msg)
    else:
        print("\nNo missing-data flags raised.")


if __name__ == "__main__":
    main()
