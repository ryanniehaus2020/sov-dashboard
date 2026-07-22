"""
The Share of Voice math.

Share is computed WITHIN each channel first, then the channels are blended.
See section 4 of the build instructions for the definitions.

  efficiency(brand)  = engagements / total_followers
  growth_rate(brand) = new_followers / total_followers
  linkedin_share     = 0.5 * efficiency_share + 0.5 * growth_share
  web_share          = unique_visitors(brand) / sum(unique_visitors of included members)

Group readings (Skills, Learning platforms, AI learning) blend two channels:
  SOV_group   = (0.5 * linkedin_share + 0.5 * web_share) * 100

The Overall reading blends three channels, adding AEO:
  SOV_overall = (0.4 * linkedin_share + 0.4 * web_share + 0.2 * aeo_share) * 100

  aeo_share = Share of Authority from the AEO sheet, used directly (already a
  percentage). It enters the Overall reading ONLY, never a group reading.

Rules honored here:
  - Eightfold (and anything in web_excluded_brands) is dropped from the web
    channel only.
  - A member missing from a source is excluded from that channel and flagged,
    never treated as zero.
  - Whenever a channel has no valid data for a reading (e.g. every member
    excluded from web, or AEO not yet available), that channel is dropped and
    the remaining channel weights are renormalized to sum to 1, with a flag.
    So a group with no web falls back to LinkedIn alone; Overall with no AEO
    falls back to LinkedIn/Web renormalized to 0.5 / 0.5.
"""


def _rate(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def compute_reading(name, member_brands, linkedin, web, config,
                    weights, aeo_share=None):
    """
    member_brands: list of internal brand keys in this reading, INCLUDING the
                   target brand (Degreed).
    linkedin / web: rows_by_brand dicts from parse.py.
    weights:        the channel-weight dict for this reading, e.g.
                    {"linkedin": 0.5, "web": 0.5} for a group or
                    {"linkedin": 0.4, "web": 0.4, "aeo": 0.2} for Overall.
    aeo_share:      Degreed Share of Authority as a fraction (Overall only),
                    or None when AEO is not part of this reading / not available.
    Returns a dict with shares, the composite SOV, the raw inputs, and flags.
    """
    brand = config["brand"]
    blend = config.get("linkedin_blend", {"efficiency": 0.5, "growth_rate": 0.5})
    excluded_web = set(config.get("web_excluded_brands", []))
    uses_aeo = "aeo" in weights

    flags = []

    # ---------------- LinkedIn channel ----------------
    efficiency = {}
    growth = {}
    li_missing = []
    for b in member_brands:
        row = linkedin.get(b)
        foll = row.get("total_followers") if row else None
        if not row or not foll:
            li_missing.append(b)
            continue
        eff = _rate(row.get("engagements"), foll)
        grw = _rate(row.get("new_followers"), foll)
        if eff is None or grw is None:
            li_missing.append(b)
            continue
        efficiency[b] = eff
        growth[b] = grw

    sum_eff = sum(efficiency.values())
    sum_growth = sum(growth.values())
    eff_share = _rate(efficiency.get(brand), sum_eff)
    growth_share = _rate(growth.get(brand), sum_growth)

    if eff_share is None or growth_share is None:
        linkedin_share = None
        flags.append("linkedin: target brand missing valid data")
    else:
        linkedin_share = (blend["efficiency"] * eff_share
                          + blend["growth_rate"] * growth_share)

    if li_missing:
        flags.append("linkedin: excluded (no data) -> " + ", ".join(li_missing))

    # ---------------- Web channel ----------------
    web_uv = {}
    web_missing = []
    web_excluded_here = []
    for b in member_brands:
        if b in excluded_web:
            web_excluded_here.append(b)
            continue
        row = web.get(b)
        uv = row.get("unique_visitors") if row else None
        if not row or not uv:
            web_missing.append(b)
            continue
        web_uv[b] = uv

    sum_uv = sum(web_uv.values())
    web_share = _rate(web_uv.get(brand), sum_uv)

    if web_excluded_here:
        flags.append("web: excluded by config -> " + ", ".join(web_excluded_here))
    if web_missing:
        flags.append("web: excluded (no data) -> " + ", ".join(web_missing))

    # ---------------- AEO channel (Overall only) ----------------
    aeo_val = aeo_share if uses_aeo else None
    if uses_aeo and aeo_val is None:
        flags.append("aeo: no Share of Authority for this period; Overall "
                     "computed from LinkedIn + Web only (weights renormalized "
                     "to 0.5 / 0.5)")

    # ---------------- Composite (renormalize over available channels) -------
    parts = {"linkedin": linkedin_share, "web": web_share}
    if uses_aeo:
        parts["aeo"] = aeo_val

    web_fallback = web_share is None
    if web_fallback:
        flags.append("web: no valid data for this reading; SOV falls back to "
                     "the remaining channel(s)")

    num = 0.0
    wsum = 0.0
    for ch, share in parts.items():
        if share is None:
            continue
        w = weights.get(ch, 0.0)
        num += w * share
        wsum += w
    sov = (num / wsum) * 100 if wsum > 0 else None

    return {
        "name": name,
        "members": list(member_brands),
        "linkedin_share": linkedin_share,
        "web_share": web_share,
        "aeo_share": aeo_val,
        "sov": sov,
        "weights_used": dict(weights),
        "web_fallback": web_fallback,
        "linkedin_members": [b for b in member_brands if b in efficiency],
        "web_members": list(web_uv.keys()),
        "flags": flags,
        # raw inputs so any past week can be audited / recomputed
        "raw": {
            "efficiency": efficiency,
            "growth_rate": growth,
            "efficiency_share": eff_share,
            "growth_share": growth_share,
            "web_unique_visitors": web_uv,
        },
    }


def _weights(config, key):
    """
    Read channel weights for 'groups' or 'overall'. Falls back to the old flat
    {"linkedin":..,"web":..} shape if a config predates the split.
    """
    cw = config["channel_weights"]
    if key in cw and isinstance(cw[key], dict):
        return cw[key]
    return {"linkedin": cw.get("linkedin", 0.5), "web": cw.get("web", 0.5)}


def compute_all(config, linkedin, web, aeo_share=None):
    """
    Compute the three group readings plus Overall.
    aeo_share: Degreed Share of Authority (fraction) for the Overall reading's
               period, or None if not available.
    Returns an ordered list of reading dicts (groups first, Overall last).
    """
    brand = config["brand"]
    group_w = _weights(config, "groups")
    overall_w = _weights(config, "overall")
    readings = []

    for group_name, members in config["groups"].items():
        member_set = [brand] + [m for m in members if m != brand]
        # Groups never include AEO.
        readings.append(compute_reading(group_name, member_set,
                                         linkedin, web, config, group_w,
                                         aeo_share=None))

    if config.get("overall_includes_all", True):
        all_brands = []
        for members in config["groups"].values():
            for m in members:
                if m != brand and m not in all_brands:
                    all_brands.append(m)
        member_set = [brand] + all_brands
        readings.append(compute_reading("Overall", member_set,
                                         linkedin, web, config, overall_w,
                                         aeo_share=aeo_share))

    return readings
