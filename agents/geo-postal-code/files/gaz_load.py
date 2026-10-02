#!/usr/bin/env python3
"""
gaz_load.py -- builds MERGE statements that load coordinates for PENDING
postal codes from the cleaned Census ZCTA Gazetteer file.

Inputs (in /mnt/data, found by name fragment; upload prefixes ignored):
  *pending*      written by the agent from the MCP queue query:
                 header geo_country,geo_postal_code
  *zcta* / *gaz* cleaned Gazetteer: column 1 = ZIP, column 2 = latitude,
                 last column = longitude (header optional, any delimiter)

Usage:
  python gaz_load.py --run-id R20261001 --expect-pending 412
      -> summary only: matched, unmatched, number of chunks, checksums
  python gaz_load.py --run-id R20261001 --expect-pending 412 --chunk 3
      -> also prints chunk 3 as ONE MERGE between
         --- MERGE BEGIN --- / --- MERGE END ---

Only postal codes found in the Gazetteer are written (POSTAL / HIGH).
Unmatched codes are listed and NOT written, so Mode A can still research them.
"""
import argparse, os, sys
import pandas as pd

DATA_DIR = os.environ.get("WLA_DATA_DIR", "/mnt/data")
EXTS = (".csv", ".txt", ".tsv", ".dat", "")
CHUNK = 50
SOURCE_NAME = "US Census Gazetteer 2025 ZCTA"
SOURCE_URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/"


def find(fragments, exclude=()):
    try:
        entries = os.listdir(DATA_DIR)
    except FileNotFoundError:
        return None
    hits = [f for f in entries
            if os.path.splitext(f)[1].lower() in EXTS
            and not f.lower().endswith(".py")
            and any(fr in f.lower() for fr in fragments)
            and not any(x in f.lower() for x in exclude)]
    if not hits:
        return None
    hits.sort(key=len)
    return os.path.join(DATA_DIR, hits[0])


def zip5(s):
    s = s.astype(str).str.strip().str.upper().str.replace(r"\.0$", "", regex=True)
    return s.where(~s.str.fullmatch(r"\d{1,4}"), s.str.zfill(5))


def load_gazetteer(path):
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        sample = [f.readline() for _ in range(5)]
    counts = {d: min(l.count(d) for l in sample if l.strip())
              for d in ("|", "\t", ",", ";")}
    sep = max(counts, key=counts.get)
    if counts[sep] == 0:
        sep = r"\s+"                      # whitespace-separated
    g = pd.read_csv(path, sep=sep, engine="python", dtype=str, header=None,
                    encoding="utf-8-sig")
    # Drop a header row if the first cell is not a number
    if not str(g.iloc[0, 0]).strip().isdigit():
        g = g.iloc[1:]
    g = pd.DataFrame({"zip": g.iloc[:, 0], "lat": g.iloc[:, 1], "lon": g.iloc[:, -1]})
    g["zip"] = zip5(g["zip"])
    g["lat"] = pd.to_numeric(g["lat"].str.strip(), errors="coerce")
    g["lon"] = pd.to_numeric(g["lon"].str.strip(), errors="coerce")
    g = g.dropna(subset=["lat", "lon"])
    # Sanity: US + territories box, never 0,0
    g = g[g["lat"].between(17, 72) & g["lon"].between(-180, -64)
          & ~((g["lat"] == 0) & (g["lon"] == 0))]
    return g.drop_duplicates("zip")


def build_merge(rows, run_id):
    blocks = [f"SELECT '{z}' z, {la:.6f} la, {lo:.6f} lo FROM dual"
              for z, la, lo in rows]
    return (
        "MERGE INTO MCP_VIEWS.XXWLA_GEO_POSTAL_CACHE tgt\nUSING (\n  "
        + "\n  UNION ALL ".join(blocks)
        + "\n) src\n"
        "   ON (tgt.geo_country = 'US' AND tgt.geo_postal_code = src.z)\n"
        " WHEN MATCHED THEN UPDATE SET\n"
        "        tgt.latitude = src.la, tgt.longitude = src.lo,\n"
        "        tgt.resolution_level = 'POSTAL', tgt.reliability = 'HIGH',\n"
        f"        tgt.source_name = '{SOURCE_NAME}',\n"
        f"        tgt.citation_url = '{SOURCE_URL}',\n"
        "        tgt.as_of_date = TRUNC(SYSDATE), tgt.last_updated_date = SYSDATE,\n"
        f"        tgt.last_updated_by = 'GAZ_{run_id}'\n"
        "      WHERE tgt.resolution_level <> 'POSTAL'\n"
        " WHEN NOT MATCHED THEN INSERT\n"
        "        (geo_country, geo_postal_code, latitude, longitude,\n"
        "         resolution_level, reliability, source_name, citation_url,\n"
        "         as_of_date, last_updated_by)\n"
        "  VALUES ('US', src.z, src.la, src.lo, 'POSTAL', 'HIGH',\n"
        f"         '{SOURCE_NAME}', '{SOURCE_URL}',\n"
        f"         TRUNC(SYSDATE), 'GAZ_{run_id}')")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--expect-pending", type=int, required=True)
    ap.add_argument("--chunk", type=int, default=None)
    ap.add_argument("--chunk-size", type=int, default=25)
    a = ap.parse_args()
    run_id = "".join(ch for ch in a.run_id.upper() if ch.isalnum())[:40]

    ppath = find(["pending"])
    gpath = find(["zcta", "gaz"], exclude=["pending"])
    if ppath is None:
        sys.exit("ERROR: no pending file found in /mnt/data")
    if gpath is None:
        sys.exit("ERROR: no Gazetteer file (name containing 'zcta' or 'gaz') found")

    p = pd.read_csv(ppath, sep=None, engine="python", dtype=str)
    p.columns = [c.strip().lower() for c in p.columns]
    if "geo_postal_code" not in p.columns:
        sys.exit("ERROR: pending file needs column geo_postal_code")
    if "geo_country" not in p.columns:
        p["geo_country"] = "US"
    p["geo_country"] = p["geo_country"].astype(str).str.strip().str.upper()
    p["geo_postal_code"] = p["geo_postal_code"].astype(str).str.strip().str.upper()
    p = p.drop_duplicates(["geo_country", "geo_postal_code"])
    # Match key: ZIP+4 (02116-3321 or 021163321) matches on its first 5 digits.
    # The ORIGINAL code is written, because the demand view joins on it exactly.
    key = p["geo_postal_code"].str.extract(r"^(\d{5})(?:-?\d{4})?$")[0]
    p["match_key"] = key.fillna(zip5(p["geo_postal_code"]))

    if len(p) != a.expect_pending:
        print("INTEGRITY CHECK FAILED")
        print(f"  pending file has {len(p)} codes; database queue count is {a.expect_pending}")
        print("Re-pull the queue. Do not edit the file to match.")
        sys.exit(1)

    g = load_gazetteer(gpath)
    us = p[p["geo_country"] == "US"]
    m = us.merge(g, left_on="match_key", right_on="zip", how="left")
    hit = m[m["lat"].notna()].sort_values("geo_postal_code")
    miss = sorted(set(p["geo_postal_code"]) - set(hit["geo_postal_code"]))

    rows = list(zip(hit["geo_postal_code"], hit["lat"].round(6), hit["lon"].round(6)))
    size = max(1, a.chunk_size)
    chunks = [rows[i:i + size] for i in range(0, len(rows), size)]

    print(f"Gazetteer file     : {os.path.basename(gpath)} ({len(g):,} usable rows)")
    print(f"Pending codes      : {len(p)}")
    print(f"Matched            : {len(rows)}")
    print(f"Not in Gazetteer   : {len(miss)}  (not written; leave for Mode A)")
    if miss:
        print("  " + ", ".join(miss))
    print(f"Chunks to send     : {len(chunks)}  (up to {size} rows each)")
    print(f"Run tag            : GAZ_{run_id}")
    print("EXPECTED AFTER ALL CHUNKS (for the verification query):")
    print(f"  rows = {len(rows)}")
    print(f"  sum_lat = {round(sum(r[1] for r in rows), 6)}")
    print(f"  sum_lon = {round(sum(r[2] for r in rows), 6)}")

    if a.chunk is not None:
        if not 1 <= a.chunk <= len(chunks):
            sys.exit(f"ERROR: chunk must be between 1 and {len(chunks)}")
        c = chunks[a.chunk - 1]
        print()
        print(f"CHUNK {a.chunk} of {len(chunks)}: {len(c)} rows")
        print("--- MERGE BEGIN ---")
        print(build_merge(c, run_id))
        print("--- MERGE END ---")


if __name__ == "__main__":
    main()