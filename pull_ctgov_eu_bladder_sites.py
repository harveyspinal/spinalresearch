#!/usr/bin/env python3

"""
pull_ctgov_eu_bladder_sites.py  —  ClinicalTrials.gov v2 API puller

Pulls *European* hospital/center sites from ClinicalTrials.gov for studies that:
- mention bladder-related terms (configurable),
- AND include at least one of these conditions (configurable): spinal cord injury, stroke, traumatic brain injury,
  spina bifida, multiple sclerosis.

Outputs a tidy CSV (and optional Excel) listing: Hospital/Center, City, Country, Conditions, Study Title, NCT ID, Location Status.

USAGE
-----
  python pull_ctgov_eu_bladder_sites.py \
      --outfile eu_bladder_sites_from_ctgov.csv \
      --xlsx \
      --terms bladder "lower urinary tract" urodynamic \
      --conditions "spinal cord injury" stroke "traumatic brain injury" "spina bifida" "multiple sclerosis"

DEPENDENCIES
------------
  pip install requests pandas openpyxl

NOTES
-----
- Uses ClinicalTrials.gov v2 API (JSON). See: https://clinicaltrials.gov/api/v2/studies
- Respects basic paging; no API key required.
- Filters to European countries (EU/EEA + UK/CH/NO/IS + neighbors commonly in pan-European trials).
"""

import argparse
import time
import requests
import pandas as pd
import sys

EUROPE_COUNTRIES = {
    "Albania","Andorra","Austria","Belarus","Belgium","Bosnia and Herzegovina","Bulgaria","Croatia","Cyprus",
    "Czechia","Czech Republic","Denmark","Estonia","Finland","France","Germany","Greece","Hungary","Iceland",
    "Ireland","Italy","Kosovo","Latvia","Liechtenstein","Lithuania","Luxembourg","Malta","Moldova","Monaco",
    "Montenegro","Netherlands","North Macedonia","Norway","Poland","Portugal","Romania","San Marino","Serbia",
    "Slovakia","Slovenia","Spain","Sweden","Switzerland","Türkiye","Turkey","Ukraine","United Kingdom","UK",
    "England","Scotland","Wales","Northern Ireland"
}

BASE = "https://clinicaltrials.gov/api/v2/studies"
FIELDS = ",".join([
    "NCTId","BriefTitle","OfficialTitle",
    "Condition","ContactsLocationsModule",
    "LocationFacility","LocationCity","LocationCountry","LocationStatus"
])

def build_query(terms, conditions):
    # example: bladder AND (spinal cord injury OR stroke OR ...)
    terms_clause = " OR ".join(f'"{t}"' if " " in t else t for t in terms)
    cond_clause = " OR ".join(f'"{c}"' if " " in c else c for c in conditions)
    return f'({terms_clause}) AND ({cond_clause})'

def fetch_page(page_token, query, page_size=100):
    params = {
        "query.term": query,
        "pageSize": page_size,
        "fields": FIELDS,
        "format": "json",
    }
    if page_token:
        params["pageToken"] = page_token
    r = requests.get(BASE, params=params, timeout=60)
    r.raise_for_status()
    return r.json()

def extract_rows(payload):
    rows = []
    for s in payload.get("studies", []):
        proto = s.get("protocolSection", {})
        ident = proto.get("identificationModule", {})
        nct = ident.get("nctId")
        title = ident.get("officialTitle") or ident.get("briefTitle")
        conds = proto.get("conditionsModule", {}).get("conditions", []) or []
        locmod = proto.get("contactsLocationsModule", {})
        locations = locmod.get("locations", []) or []
        for loc in locations:
            country = loc.get("country")
            if not country or country not in EUROPE_COUNTRIES:
                continue
            rows.append({
                "Hospital/Center": loc.get("facility"),
                "City": loc.get("city"),
                "Country": country,
                "Condition(s)": "; ".join(conds),
                "Study Title": title,
                "NCT ID": nct,
                "Location Status": loc.get("status"),
            })
    return rows

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outfile", default="eu_bladder_sites_from_ctgov.csv")
    ap.add_argument("--xlsx", action="store_true", help="also write an .xlsx with the same data")
    ap.add_argument("--terms", nargs="+", default=["bladder","lower urinary tract","urodynamic","neurogenic detrusor","urinary incontinence"],
                    help="free-text terms to search in ClinicalTrials.gov")
    ap.add_argument("--conditions", nargs="+", default=["spinal cord injury","stroke","traumatic brain injury","spina bifida","multiple sclerosis"],
                    help="conditions to include")
    ap.add_argument("--sleep", type=float, default=0.2, help="delay between pages (seconds)")
    args = ap.parse_args()

    query = build_query(args.terms, args.conditions)
    print("Query:", query, file=sys.stderr)

    all_rows = []
    seen = set()
    token = None

    while True:
        data = fetch_page(token, query)
        rows = extract_rows(data)
        for r in rows:
            key = (r["NCT ID"], r["Hospital/Center"], r["City"], r["Country"], r["Location Status"])
            if key in seen:
                continue
            seen.add(key)
            all_rows.append(r)
        token = data.get("nextPageToken")
        if not token:
            break
        time.sleep(args.sleep)

    df = pd.DataFrame(all_rows)
    # Optional extra filter: keep rows where title or conditions mention at least one term
    term_mask = pd.Series([True]*len(df))
    if not df.empty:
        term_mask = False
        for t in args.terms:
            term_mask = term_mask | df["Study Title"].str.contains(t, case=False, na=False) | df["Condition(s)"].str.contains(t, case=False, na=False)
        df = df[term_mask].copy()

    # Clean up hospital names a bit
    df["Hospital/Center"] = df["Hospital/Center"].fillna("").str.strip()
    df["City"] = df["City"].fillna("").str.strip()

    # Sort for readability
    df.sort_values(["Country","City","Hospital/Center","NCT ID"], inplace=True)

    # Write CSV
    df.to_csv(args.outfile, index=False, encoding="utf-8-sig")
    print(f"Wrote {len(df)} rows to {args.outfile}")
    if args.xlsx:
        xls_path = args.outfile.rsplit(".",1)[0] + ".xlsx"
        try:
            df.to_excel(xls_path, index=False)
            print(f"Wrote Excel file: {xls_path}")
        except Exception as e:
            print(f"Excel write skipped (install openpyxl to enable): {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
