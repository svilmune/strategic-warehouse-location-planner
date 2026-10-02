#!/usr/bin/env python3
"""
scoring.py  --  Warehouse Location Recommendation Agent  |  TIER 1 SCORING

Deterministic scoring of candidate warehouse sites against geocoded demand.

DESIGN RULE:
    All distance, coverage, normalisation and overlap arithmetic happens HERE.
    The agent executes this file unchanged and quotes its output verbatim.
    The agent must never author scoring logic, recompute, adjust or interpolate
    any figure this file returns.

Same inputs -> same ranking, every run.

--------------------------------------------------------------------------------
INPUT FILES  (in /mnt/data; written by the agent from MCP_VIEWS query results)
--------------------------------------------------------------------------------
Files are found by SUBSTRING match, so upload-system id prefixes are ignored.
Extensions .csv / .txt / .tsv / .dat are accepted. The delimiter (comma, tab,
semicolon, pipe) is detected automatically.

  *demand*             ship_to_country, ship_to_postal_code, units
                       optional: ship_to_city, ship_to_state, weight_kg,
                                 volume_m3, amount, period_month
  *network*            node_country, latitude, longitude
                       optional: organization_code, active_flag
  *geo_postal_cache*   geo_country, geo_postal_code, latitude, longitude,
                       resolution_level
  *candidate_sites*    site_id, site_name, site_country, latitude, longitude
                       optional: region, site_state, site_city,
                                 is_existing_node, active_flag

--------------------------------------------------------------------------------
USAGE
--------------------------------------------------------------------------------
  python scoring.py --country US
         --expect-units 144468 --expect-postal-codes 41
         --period-label-from 01-NOV-2023 --period-label-to 05-DEC-2026
         --out-json /mnt/data/tier1_result.json

  --expect-units / --expect-postal-codes are the control totals from the
  database. If the loaded demand file does not match them, scoring stops.
"""

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

DEFAULTS = {
    "metric":              "UNITS",
    "service_hours":       8.0,
    "w_proximity":         0.6,
    "w_coverage":          0.4,
    "top_n":               10,
    "road_factor":         1.25,
    "speed_kmph":          45.0,
    "overlap_radius_km":   150.0,
    "max_overlap_penalty": 0.25,
    "min_metric_coverage": 60.0,
}

DATA_DIR = os.environ.get("WLA_DATA_DIR", "/mnt/data")

METRIC_COLUMN = {
    "UNITS":  "units",
    "WEIGHT": "weight_kg",
    "VOLUME": "volume_m3",
    "AMOUNT": "amount",
}

EARTH_RADIUS_KM = 6371.0

OUT_COLS = [
    "rank", "site_id", "site_name", "region", "site_city", "site_state",
    "composite_score", "coverage_pct", "demand_weighted_km", "avg_drive_hours",
    "overlap_pct", "nearest_existing_node", "nearest_node_km", "is_existing_node",
]


# ==========================================================================
# File discovery and loading
# ==========================================================================
def resolve_path(stem):
    """
    Find an input file by SUBSTRING match on the stem.

    Handles two environment quirks:
      - upload systems prefix filenames with an internal id, e.g.
        assistant-DPnqb7ent...-demand.txt
      - Excel 'Save as text' produces tab-delimited .txt, not .csv

    Matching is case-insensitive and ignores any prefix or suffix.
    """
    stem = stem.lower()
    try:
        entries = os.listdir(DATA_DIR)
    except FileNotFoundError:
        return None

    hits = [
        f for f in entries
        if stem in f.lower()
        and os.path.splitext(f)[1].lower() in (".csv", ".txt", ".tsv", ".dat")
    ]
    if not hits:
        return None
    hits.sort(key=len)          # shortest match = least-decorated filename
    return os.path.join(DATA_DIR, hits[0])


def _read(name, required_cols):
    stem = os.path.splitext(name)[0]
    path = resolve_path(stem)
    if path is None:
        sys.exit(f"ERROR: no file matching '{stem}' (.csv/.txt/.tsv) found in {DATA_DIR}")
    df = pd.read_csv(path, sep=None, engine="python")
    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        sys.exit(f"ERROR: {os.path.basename(path)} is missing required column(s): "
                 f"{', '.join(missing)}")
    return df


def _clean_key(series):
    return series.astype(str).str.strip().str.upper()


def load_inputs():
    demand = _read("demand.csv", [
        "ship_to_country", "ship_to_postal_code", "units",
    ])
    network = _read("network.csv", [
        "node_country", "latitude", "longitude",
    ])
    geo = _read("geo_postal_cache.csv", [
        "geo_country", "geo_postal_code", "latitude", "longitude", "resolution_level",
    ])
    cand = _read("candidate_sites.csv", [
        "site_id", "site_name", "site_country", "latitude", "longitude",
    ])

    # Optional columns, defaulted so a thin extract still runs.
    for col in ("weight_kg", "volume_m3", "amount"):
        if col not in demand.columns:
            demand[col] = 0.0
    for col in ("category_name", "ship_from_org_id", "ship_to_city", "ship_to_state"):
        if col not in demand.columns:
            demand[col] = None
    for col in ("region", "site_state", "site_city"):
        if col not in cand.columns:
            cand[col] = None
    if "is_existing_node" not in cand.columns:
        cand["is_existing_node"] = "N"
    if "active_flag" not in cand.columns:
        cand["active_flag"] = "Y"
    if "active_flag" not in network.columns:
        network["active_flag"] = "Y"
    if "organization_code" not in network.columns:
        network["organization_code"] = network.index.astype(str)

    # Normalise join keys. Case and whitespace mismatches are the most common
    # cause of a silently empty geocode join.
    demand["ship_to_country"] = _clean_key(demand["ship_to_country"])
    demand["ship_to_postal_code"] = _clean_key(demand["ship_to_postal_code"])
    geo["geo_country"] = _clean_key(geo["geo_country"])
    geo["geo_postal_code"] = _clean_key(geo["geo_postal_code"])
    cand["site_country"] = _clean_key(cand["site_country"])
    network["node_country"] = _clean_key(network["node_country"])

    # Leading-zero repair: a numeric read turns 02108 into 2108, and a float
    # read turns 10001 into 10001.0. US ZIPs are 5 digits, so repair US rows.
    for df, ccol, pcol in ((demand, "ship_to_country", "ship_to_postal_code"),
                           (geo, "geo_country", "geo_postal_code")):
        us_f = (df[ccol] == "US") & df[pcol].str.fullmatch(r"\d+\.0")
        df.loc[us_f, pcol] = df.loc[us_f, pcol].str[:-2]
        us = (df[ccol] == "US") & df[pcol].str.fullmatch(r"\d{1,4}")
        df.loc[us, pcol] = df.loc[us, pcol].str.zfill(5)

    # Period is optional: the database query already filters the period.
    if "period_month" in demand.columns:
        demand["period_month"] = pd.to_datetime(demand["period_month"], errors="coerce")
    else:
        demand["period_month"] = pd.NaT

    for col in ("units", "weight_kg", "volume_m3", "amount"):
        demand[col] = pd.to_numeric(demand[col], errors="coerce").fillna(0.0)
    for df in (geo, cand, network):
        for col in ("latitude", "longitude"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return demand, network, geo, cand


# ==========================================================================
# Integrity check
# ==========================================================================
def integrity_check(demand, expect_units, expect_postal_codes):
    """
    The agent copied SQL results into the demand file. If the loaded file does
    not match the database's own control totals, rows were lost or altered in
    transfer. Stop rather than rank on corrupted data.
    """
    problems = []
    if expect_units is not None:
        loaded = float(demand["units"].sum())
        if abs(loaded - expect_units) > 0.5:
            problems.append(f"demand units {loaded:,.0f} != database total {expect_units:,.0f}")
    if expect_postal_codes is not None:
        # Match the SQL: NULL postal codes count as one distinct value.
        pc = demand["ship_to_postal_code"].replace(
            {"": "~NULL~", "NAN": "~NULL~", "NONE": "~NULL~"})
        loaded_pc = pc.nunique()
        if loaded_pc != expect_postal_codes:
            problems.append(f"demand postal codes {loaded_pc} != database count "
                            f"{expect_postal_codes}")
    if problems:
        print("INTEGRITY CHECK FAILED")
        for p in problems:
            print(f"  {p}")
        print("Data was lost or altered in transfer. Do not report a ranking.")
        print("Do not edit the demand file to match. Re-pull the data.")
        sys.exit(1)


# ==========================================================================
# Scoring
# ==========================================================================
def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance, vectorised."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    return EARTH_RADIUS_KM * 2.0 * np.arcsin(np.minimum(1.0, np.sqrt(a)))


def resolve_metric(scoped, requested, min_cov_pct):
    """
    Validate the requested metric. Scoring a column of zeros produces a
    confident but meaningless ranking, so a sparsely populated metric falls
    back to UNITS, and the fallback is flagged.
    """
    requested = (requested or "UNITS").upper()
    if requested not in METRIC_COLUMN:
        return "UNITS", requested, {}

    n = len(scoped)
    coverage = {}
    for m, col in METRIC_COLUMN.items():
        coverage[m] = round(100.0 * (scoped[col] > 0).sum() / n, 1) if n else 0.0

    effective = requested
    if requested != "UNITS" and coverage.get(requested, 0.0) < min_cov_pct:
        effective = "UNITS"
    return effective, requested, coverage


def score(demand, network, geo, cand, p):
    country = p["country"].upper()

    # ---- Scope -----------------------------------------------------------
    scoped = demand[demand["ship_to_country"] == country].copy()
    has_period = scoped["period_month"].notna().any()
    if has_period and p.get("from_month") is not None:
        scoped = scoped[scoped["period_month"] >= p["from_month"]]
    if has_period and p.get("to_month") is not None:
        scoped = scoped[scoped["period_month"] <= p["to_month"]]
    if p.get("category_name"):
        scoped = scoped[scoped["category_name"] == p["category_name"]]
    if p.get("ship_from_org_id") is not None:
        scoped = scoped[
            pd.to_numeric(scoped["ship_from_org_id"], errors="coerce")
            == p["ship_from_org_id"]
        ]

    if scoped.empty:
        return None, {"reason": f"No demand rows found for country {country} "
                                f"in the requested period."}

    # ---- Metric validation and fallback ----------------------------------
    eff_metric, req_metric, metric_cov = resolve_metric(
        scoped, p["metric"], p["min_metric_coverage"]
    )
    mcol = METRIC_COLUMN[eff_metric]

    # ---- Aggregate to postal grain BEFORE joining to candidates ----------
    pts = (
        scoped.groupby("ship_to_postal_code", as_index=False)
        .agg(metric_qty=(mcol, "sum"),
             units=("units", "sum"),
             city=("ship_to_city", "first"))
    )
    total_metric_in_scope = float(scoped[mcol].sum())

    geo_ok = geo[
        (geo["geo_country"] == country)
        & (geo["resolution_level"].astype(str).str.upper() != "UNRESOLVED")
        & geo["latitude"].notna()
        & geo["longitude"].notna()
    ].drop_duplicates(subset=["geo_postal_code"])
    pts = pts.merge(
        geo_ok[["geo_postal_code", "latitude", "longitude", "resolution_level"]],
        left_on="ship_to_postal_code", right_on="geo_postal_code", how="inner",
    )
    pts = pts[pts["metric_qty"] > 0]

    if pts.empty:
        return None, {"reason":
                      "No demand point could be geocoded. Check that postal codes in "
                      "the demand file match the geo postal cache for this country."}

    # ---- Confidence ------------------------------------------------------
    geocoded_pct = round(
        100.0 * float(pts["metric_qty"].sum()) / total_metric_in_scope, 1
    ) if total_metric_in_scope else 0.0

    # ---- Candidates ------------------------------------------------------
    sites = cand[
        (cand["site_country"] == country)
        & (cand["active_flag"].astype(str).str.strip().str.upper() == "Y")
        & cand["latitude"].notna()
        & cand["longitude"].notna()
    ].copy()
    if sites.empty:
        return None, {"reason":
                      f"No active candidate sites defined for {country}. "
                      "Run Geo Agent Mode B before scoring."}

    # ---- Measure: distance from every candidate to every demand point ----
    s_lat = sites["latitude"].to_numpy(dtype=float)[:, None]
    s_lon = sites["longitude"].to_numpy(dtype=float)[:, None]
    d_lat = pts["latitude"].to_numpy(dtype=float)[None, :]
    d_lon = pts["longitude"].to_numpy(dtype=float)[None, :]

    road_km = haversine_km(s_lat, s_lon, d_lat, d_lon) * p["road_factor"]

    qty = pts["metric_qty"].to_numpy(dtype=float)[None, :]
    total_qty = qty.sum()

    # ---- Score two dimensions, in their natural units --------------------
    dw_km = (road_km * qty).sum(axis=1) / total_qty
    drive_hours = dw_km / p["speed_kmph"]
    within = (road_km / p["speed_kmph"]) <= p["service_hours"]
    coverage_pct = 100.0 * (np.where(within, qty, 0.0)).sum(axis=1) / total_qty

    sites = sites.assign(
        demand_weighted_km=np.round(dw_km, 1),
        avg_drive_hours=np.round(drive_hours, 2),
        coverage_pct=np.round(coverage_pct, 1),
    )

    # ---- Overlap with the existing network (no region filter) ------------
    net = network[
        (network["node_country"] == country)
        & (network["active_flag"].astype(str).str.strip().str.upper() == "Y")
        & network["latitude"].notna()
        & network["longitude"].notna()
    ].drop_duplicates(subset=["organization_code"]).copy()

    if not net.empty:
        n_lat = net["latitude"].to_numpy(dtype=float)[None, :]
        n_lon = net["longitude"].to_numpy(dtype=float)[None, :]
        node_km = haversine_km(s_lat, s_lon, n_lat, n_lon)
        idx = node_km.argmin(axis=1)
        nearest_km = node_km.min(axis=1)
        nearest_name = net["organization_code"].astype(str).to_numpy()[idx]
    else:
        nearest_km = np.full(len(sites), np.nan)
        nearest_name = np.array([None] * len(sites), dtype=object)

    # Proportional penalty: full reduction on top of an existing node, none at
    # the radius edge. An existing node is not penalised for overlapping with
    # itself -- it is the baseline, not a new site cannibalising one.
    is_existing = sites["is_existing_node"].astype(str).str.strip().str.upper() == "Y"
    with np.errstate(invalid="ignore"):
        penalty = np.where(
            np.isnan(nearest_km) | (nearest_km >= p["overlap_radius_km"]),
            0.0,
            p["max_overlap_penalty"] * (1.0 - (nearest_km / p["overlap_radius_km"])),
        )
    self_match = is_existing.to_numpy() & (np.nan_to_num(nearest_km, nan=1e9) < 1.0)
    penalty = np.where(self_match, 0.0, penalty)

    sites = sites.assign(
        nearest_node_km=np.round(nearest_km, 1),
        nearest_existing_node=nearest_name,
        overlap_penalty=penalty,
    )

    # ---- Normalise: min-max so km and % become comparable ----------------
    km_min, km_max = sites["demand_weighted_km"].min(), sites["demand_weighted_km"].max()
    cv_min, cv_max = sites["coverage_pct"].min(), sites["coverage_pct"].max()

    prox_norm = (
        np.ones(len(sites)) if km_max == km_min
        else (km_max - sites["demand_weighted_km"]) / (km_max - km_min)
    )
    cov_norm = (
        np.ones(len(sites)) if cv_max == cv_min
        else (sites["coverage_pct"] - cv_min) / (cv_max - cv_min)
    )

    wsum = p["w_proximity"] + p["w_coverage"]
    composite = ((prox_norm * p["w_proximity"] + cov_norm * p["w_coverage"]) / wsum) \
                * (1.0 - sites["overlap_penalty"])

    sites = sites.assign(composite_score=np.round(composite, 4))
    sites = sites.sort_values(
        ["composite_score", "site_name"], ascending=[False, True]
    ).reset_index(drop=True)
    sites.insert(0, "rank", sites.index + 1)

    if has_period:
        period_from = str(scoped["period_month"].min().date())
        period_to = str(scoped["period_month"].max().date())
    else:
        period_from = str(p.get("period_label_from") or "as filtered in database")
        period_to = str(p.get("period_label_to") or "as filtered in database")

    meta = {
        "country":               country,
        "metric_used":           eff_metric,
        "metric_requested":      req_metric,
        "fallback_applied":      "Y" if eff_metric != req_metric else "N",
        "metric_coverage_pct":   metric_cov,
        "demand_points_used":    int(len(pts)),
        "geocoded_units_pct":    geocoded_pct,
        "postal_level_points":   int(
            (pts["resolution_level"].astype(str).str.upper() == "POSTAL").sum()
        ),
        "period_from":           period_from,
        "period_to":             period_to,
        "candidates_evaluated":  int(len(sites)),
        "existing_nodes_used":   int(len(net)),
        "assumptions": {
            "weight_proximity":     p["w_proximity"],
            "weight_coverage":      p["w_coverage"],
            "service_hours_target": p["service_hours"],
            "road_factor":          p["road_factor"],
            "speed_kmph":           p["speed_kmph"],
            "overlap_radius_km":    p["overlap_radius_km"],
            "max_overlap_penalty":  p["max_overlap_penalty"],
        },
    }
    return sites.head(int(p["top_n"])), meta


# ==========================================================================
# Output
# ==========================================================================
def _shortlist_frame(result):
    r = result.copy()
    r["overlap_pct"] = np.round(r["overlap_penalty"] * 100.0, 1)
    for c in OUT_COLS:
        if c not in r.columns:
            r[c] = None
    return r[OUT_COLS]


def emit_text(result, meta):
    r = _shortlist_frame(result)

    print("=" * 78)
    print("TIER 1 COMPUTED RANKING  --  deterministic, produced by scoring.py")
    print("=" * 78)
    print(f"Country: {meta['country']}   Period: {meta['period_from']} to {meta['period_to']}")
    print(f"Metric scored: {meta['metric_used']}   Requested: {meta['metric_requested']}"
          f"   Fallback applied: {meta['fallback_applied']}")
    print()
    print(r.to_string(index=False))
    print()
    print("-" * 78)
    print("DATA CONFIDENCE")
    print("-" * 78)
    print(f"  Demand points used        : {meta['demand_points_used']}")
    print(f"  Geocoded units %          : {meta['geocoded_units_pct']}")
    print(f"  Postal-level points       : {meta['postal_level_points']}")
    print(f"  Candidates evaluated      : {meta['candidates_evaluated']}")
    print(f"  Existing nodes in overlap : {meta['existing_nodes_used']}")
    if meta["geocoded_units_pct"] < 80:
        print("  WARNING: geocoded units below 80%. This ranking is PROVISIONAL "
              "and must be declared as such.")
    if meta["fallback_applied"] == "Y":
        print(f"  WARNING: '{meta['metric_requested']}' had insufficient data "
              f"(coverage {meta['metric_coverage_pct'].get(meta['metric_requested'])}%). "
              f"Scored on UNITS instead.")
    if meta["existing_nodes_used"] == 0:
        print("  WARNING: no geocoded existing nodes. Overlap penalty could not "
              "be applied; cannibalisation risk is UNASSESSED.")
    print()
    print("-" * 78)
    print("ASSUMPTIONS APPLIED")
    print("-" * 78)
    for k, v in meta["assumptions"].items():
        print(f"  {k:<22}: {v}")
    print()
    print("Distances are great-circle x road factor, not routed drive time. "
          "Quote these figures verbatim; do not recompute or adjust them.")
    print("=" * 78)


def build_payload(result, meta):
    r = _shortlist_frame(result)
    return {"shortlist": json.loads(r.to_json(orient="records")), "meta": meta}


# ==========================================================================
def parse_args():
    ap = argparse.ArgumentParser(description="Tier 1 warehouse candidate scoring.")
    ap.add_argument("--country", required=True, help="ISO country code, e.g. US")
    ap.add_argument("--from-month", default=None, help="YYYY-MM (only if file has period_month)")
    ap.add_argument("--to-month", default=None, help="YYYY-MM (only if file has period_month)")
    ap.add_argument("--metric", default=DEFAULTS["metric"],
                    choices=list(METRIC_COLUMN.keys()))
    ap.add_argument("--category", default=None)
    ap.add_argument("--ship-from-org-id", type=int, default=None)
    ap.add_argument("--service-hours", type=float, default=DEFAULTS["service_hours"])
    ap.add_argument("--w-proximity", type=float, default=DEFAULTS["w_proximity"])
    ap.add_argument("--w-coverage", type=float, default=DEFAULTS["w_coverage"])
    ap.add_argument("--top-n", type=int, default=DEFAULTS["top_n"])
    ap.add_argument("--road-factor", type=float, default=DEFAULTS["road_factor"])
    ap.add_argument("--speed-kmph", type=float, default=DEFAULTS["speed_kmph"])
    ap.add_argument("--overlap-radius-km", type=float,
                    default=DEFAULTS["overlap_radius_km"])
    ap.add_argument("--max-overlap-penalty", type=float,
                    default=DEFAULTS["max_overlap_penalty"])
    ap.add_argument("--min-metric-coverage", type=float,
                    default=DEFAULTS["min_metric_coverage"])
    # Integrity check and labelling
    ap.add_argument("--expect-units", type=float, default=None)
    ap.add_argument("--expect-postal-codes", type=int, default=None)
    ap.add_argument("--period-label-from", default=None)
    ap.add_argument("--period-label-to", default=None)
    # Output
    ap.add_argument("--json", action="store_true", help="Print JSON instead of text")
    ap.add_argument("--out-json", default=None, help="Also write results to this file")
    return ap.parse_args()


def main():
    a = parse_args()
    p = {
        "country":             a.country,
        "from_month":          pd.to_datetime(a.from_month) if a.from_month else None,
        "to_month":            pd.to_datetime(a.to_month) if a.to_month else None,
        "metric":              a.metric,
        "category_name":       a.category,
        "ship_from_org_id":    a.ship_from_org_id,
        "service_hours":       a.service_hours,
        "w_proximity":         a.w_proximity,
        "w_coverage":          a.w_coverage,
        "top_n":               a.top_n,
        "road_factor":         a.road_factor,
        "speed_kmph":          a.speed_kmph,
        "overlap_radius_km":   a.overlap_radius_km,
        "max_overlap_penalty": a.max_overlap_penalty,
        "min_metric_coverage": a.min_metric_coverage,
        "period_label_from":   a.period_label_from,
        "period_label_to":     a.period_label_to,
    }

    demand, network, geo, cand = load_inputs()
    integrity_check(demand, a.expect_units, a.expect_postal_codes)

    result, meta = score(demand, network, geo, cand, p)

    if result is None:
        print("NO RESULT")
        print(meta["reason"])
        print("Do not substitute general knowledge. Report this to the user as-is.")
        sys.exit(0)

    payload = build_payload(result, meta)
    if a.out_json:
        with open(a.out_json, "w") as f:
            json.dump(payload, f, indent=2, default=str)

    if a.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        emit_text(result, meta)
        if a.out_json:
            print(f"Results written to {a.out_json}")


if __name__ == "__main__":
    main()