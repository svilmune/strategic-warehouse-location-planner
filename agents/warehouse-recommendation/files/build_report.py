#!/usr/bin/env python3
"""
build_report.py (v2) -- builds the recommendation Excel workbook.

Inputs in /mnt/data (found by name fragment; upload prefixes ignored):
  tier1_result.json   written by scoring.py --out-json  (computed, verbatim)
  research.json       written by the agent               (research + reasoning)
  demand / network / candidate_sites / geo_postal_cache  (.csv/.txt, optional)
                      copied into input sheets for audit

research.json keys:
  recommendation  required  {recommended_site_id, summary, trade_off,
                             divergence_from_rank1}
  research        required  list of findings
  limitations     required  list of strings
  location_check  optional  list of {site_id, recorded_state,
                             returned_state, result}
  run_log         optional  list of strings, one per step
  overrides       optional  list of strings

The ranking, confidence and assumption figures are copied from
tier1_result.json by this script. The agent never retypes them.

Refused (exit 1) if:
  - the recommended site is not in the ranking or was not researched
  - a researched site_id is not in the ranking
  - a factor or finding_type is invalid
  - a non-ABSENT finding has no source_url
  - the recommendation differs from rank 1 without an explanation

Usage:
  python build_report.py --ou "Vision Operations" --start 01-FEB-2002
         --end 01-OCT-2010 [--region ALL] [--country US]
"""
import argparse, json, os, re, sys
from datetime import datetime
import pandas as pd

DATA_DIR = os.environ.get("WLA_DATA_DIR", "/mnt/data")
FACTORS = {"INDUSTRIAL_RENT", "LABOUR", "INFRASTRUCTURE", "RISK"}
TYPES = {"FAVOURABLE", "ADVERSE", "NEUTRAL", "ABSENT"}
DATA_EXT = (".csv", ".txt", ".tsv", ".dat")


def find(stem, exts):
    try:
        entries = os.listdir(DATA_DIR)
    except FileNotFoundError:
        return None
    hits = [f for f in entries
            if stem in f.lower() and os.path.splitext(f)[1].lower() in exts]
    if not hits:
        return None
    hits.sort(key=len)
    return os.path.join(DATA_DIR, hits[0])


def load_json(stem):
    p = find(stem, (".json",))
    if p is None:
        print("REPORT REFUSED")
        print(f"  - no file matching '{stem}*.json' found in {DATA_DIR}")
        sys.exit(1)
    with open(p) as f:
        return json.load(f)


def load_input(stem):
    p = find(stem, DATA_EXT)
    if p is None:
        return pd.DataFrame({"note": [f"{stem} file not found in session"]})
    try:
        return pd.read_csv(p, sep=None, engine="python", dtype=str)
    except Exception as e:
        return pd.DataFrame({"note": [f"could not read {os.path.basename(p)}: {e}"]})


def fail(errors):
    print("REPORT REFUSED")
    for e in errors:
        print(f"  - {e}")
    print("Correct research.json and rerun. Do not edit tier1_result.json.")
    sys.exit(1)


def as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ou", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--region", default="ALL")
    ap.add_argument("--country", default="US")
    a = ap.parse_args()

    t1 = load_json("tier1_result")
    rs = load_json("research")
    ranking = pd.DataFrame(t1["shortlist"])
    meta = t1["meta"]
    ids = set(ranking["site_id"].astype(int))
    names = dict(zip(ranking["site_id"].astype(int), ranking["site_name"]))

    # ---- Validation ------------------------------------------------------
    errors = []
    rec = rs.get("recommendation", {}) or {}
    rid = as_int(rec.get("recommended_site_id"))
    if rid is None or rid not in ids:
        errors.append(f"recommended_site_id {rec.get('recommended_site_id')} "
                      f"is not in the Tier 1 ranking")
    for k in ("summary", "trade_off"):
        if not str(rec.get(k) or "").strip():
            errors.append(f"recommendation.{k} is empty")

    research = pd.DataFrame(rs.get("research", []) or [])
    if research.empty:
        errors.append("research list is empty")
        researched = set()
    else:
        for i, r in research.iterrows():
            n = i + 1
            sid = as_int(r.get("site_id"))
            if sid not in ids:
                errors.append(f"research row {n}: site_id {r.get('site_id')} "
                              f"is not in the Tier 1 ranking")
            if str(r.get("factor", "")).upper() not in FACTORS:
                errors.append(f"research row {n}: factor '{r.get('factor')}' "
                              f"not one of {sorted(FACTORS)}")
            ftype = str(r.get("finding_type", "")).upper()
            if ftype not in TYPES:
                errors.append(f"research row {n}: finding_type "
                              f"'{r.get('finding_type')}' not one of {sorted(TYPES)}")
            if ftype != "ABSENT" and not str(r.get("source_url") or "").strip():
                errors.append(f"research row {n}: {ftype} finding has no source_url")
        researched = {as_int(s) for s in research["site_id"]}
    if rid is not None and rid in ids and rid not in researched:
        errors.append(f"recommended site {rid} has no research rows")
    if errors:
        fail(errors)

    rank1 = ranking.sort_values("rank").iloc[0]
    diverges = rid != int(rank1["site_id"])
    if diverges and not str(rec.get("divergence_from_rank1") or "").strip():
        fail(["recommendation differs from computed rank 1 but "
              "divergence_from_rank1 is empty"])

    provisional = meta["geocoded_units_pct"] < 80
    status = "PROVISIONAL (geocoded units below 80%)" if provisional else "FINAL"
    overrides = [str(o) for o in (rs.get("overrides") or [])]

    # ---- Sheet 1: Recommendation ----------------------------------------
    rec_rank = int(ranking.loc[ranking["site_id"].astype(int) == rid, "rank"].iloc[0])
    rows = [
        ("Operating unit", a.ou),
        ("Country", a.country),
        ("Period", f"{a.start} to {a.end}"),
        ("Region", a.region),
        ("Generated", datetime.now().strftime("%d-%b-%Y %H:%M").upper()),
        ("Ranking status", status),
        ("Overrides applied", "; ".join(overrides) if overrides else "None"),
        ("", ""),
        ("Recommended site", names[rid]),
        ("Computed rank of recommended site", rec_rank),
        ("Computed rank 1", rank1["site_name"]),
        ("Differs from computed rank 1", "YES" if diverges else "NO"),
        ("", ""),
        ("Summary", rec.get("summary", "")),
        ("Trade-off", rec.get("trade_off", "")),
        ("Divergence explanation", rec.get("divergence_from_rank1") or ""),
        ("", ""),
        ("What was NOT considered", ""),
    ] + [("", str(l)) for l in (rs.get("limitations") or [])]
    df_rec = pd.DataFrame(rows, columns=["Item", "Detail"])

    # ---- Sheet 2: Ranking (all candidates, verbatim) --------------------
    df_rank = ranking.copy()
    df_rank.insert(3, "researched",
                   df_rank["site_id"].astype(int).map(
                       lambda s: "Y" if s in researched else "N"))

    # ---- Sheet 3: Comparison matrix (researched sites x factors) --------
    res = research.copy()
    res["site_id"] = res["site_id"].astype(int)
    res["factor"] = res["factor"].str.upper()
    res["finding_type"] = res["finding_type"].str.upper()
    matrix = res.pivot_table(index="site_id", columns="factor",
                             values="finding_type", aggfunc="first")
    for f in sorted(FACTORS):
        if f not in matrix.columns:
            matrix[f] = "NOT RESEARCHED"
    matrix = matrix[sorted(FACTORS)].fillna("NOT RESEARCHED").reset_index()
    keep = ["site_id", "rank", "site_name", "composite_score",
            "coverage_pct", "demand_weighted_km", "overlap_pct"]
    df_cmp = ranking[[c for c in keep if c in ranking.columns]].copy()
    df_cmp["site_id"] = df_cmp["site_id"].astype(int)
    df_cmp = df_cmp.merge(matrix, on="site_id", how="inner").sort_values("rank")
    df_cmp["absent_count"] = (df_cmp[sorted(FACTORS)] == "ABSENT").sum(axis=1)
    df_cmp["recommended"] = df_cmp["site_id"].map(lambda s: "Y" if s == rid else "")

    # ---- Sheet 4: Market research ----------------------------------------
    cols = ["site_id", "site_name", "factor", "finding_type", "finding",
            "source_name", "source_url", "as_of_date"]
    res.insert(1, "site_name", res["site_id"].map(names))
    for c in cols:
        if c not in res.columns:
            res[c] = ""
    df_res = res[cols].sort_values(["site_id", "factor"])

    # ---- Sheet 5: Location check ----------------------------------------
    lc = rs.get("location_check") or []
    df_lc = (pd.DataFrame(lc) if lc
             else pd.DataFrame({"note": ["Location check not performed or not recorded"]}))

    # ---- Sheet 6: Assumptions -------------------------------------------
    asm = [("Operating unit", a.ou), ("Country", a.country),
           ("Period from", a.start), ("Period to", a.end), ("Region", a.region),
           ("Metric requested", meta["metric_requested"]),
           ("Metric scored", meta["metric_used"])]
    asm += [(k, v) for k, v in meta["assumptions"].items()]
    asm += [("Distance model",
             "Great-circle distance x road factor; not routed drive time"),
            ("Composite score",
             "Normalised proximity and coverage, weighted, minus overlap penalty"),
            ("Research", "Researched sites only; computed and researched "
                         "evidence kept separate, never combined into one score")]
    df_asm = pd.DataFrame(asm, columns=["Assumption", "Value"])

    # ---- Sheet 7: Data confidence ----------------------------------------
    conf = [("Geocoded units %", meta["geocoded_units_pct"]),
            ("Ranking status", status),
            ("Demand points used", meta["demand_points_used"]),
            ("Postal-level points", meta["postal_level_points"]),
            ("Candidates evaluated", meta["candidates_evaluated"]),
            ("Existing nodes used in overlap test", meta["existing_nodes_used"]),
            ("Metric fallback applied", meta["fallback_applied"]),
            ("Sites researched", len(researched)),
            ("Research findings marked ABSENT",
             int((df_res["finding_type"] == "ABSENT").sum()))]
    for m, v in (meta.get("metric_coverage_pct") or {}).items():
        conf.append((f"{m} coverage %", v))
    df_conf = pd.DataFrame(conf, columns=["Indicator", "Value"])

    # ---- Sheet 8: Run log -----------------------------------------------
    log = rs.get("run_log") or []
    df_log = (pd.DataFrame({"step": [str(x) for x in log]}) if log
              else pd.DataFrame({"step": ["Run log not recorded"]}))

    # ---- Input sheets ----------------------------------------------------
    inputs = [("Input - Demand", load_input("demand")),
              ("Input - Candidates", load_input("candidate_sites")),
              ("Input - Network", load_input("network")),
              ("Input - Geocodes", load_input("geo_postal_cache"))]

    # ---- Write -----------------------------------------------------------
    safe_ou = re.sub(r"[^A-Za-z0-9]+", "_", a.ou).strip("_")
    out = os.path.join(
        DATA_DIR,
        f"Warehouse_Recommendation_{safe_ou}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx")

    sheets = [("Recommendation", df_rec), ("Comparison", df_cmp),
              ("Ranking", df_rank), ("Market Research", df_res),
              ("Location Check", df_lc), ("Assumptions", df_asm),
              ("Data Confidence", df_conf), ("Run Log", df_log)] + inputs

    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        for name, df in sheets:
            df.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0
                            for c in col[:200])
                ws.column_dimensions[col[0].column_letter].width = \
                    min(max(12, width + 2), 80)
            ws.freeze_panes = "A2"

    print("REPORT BUILT")
    print(out)


if __name__ == "__main__":
    main()