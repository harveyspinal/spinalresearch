#!/usr/bin/env python3
"""
pull_ctgov_eu_bladder_sites.py — ClinicalTrials.gov v2 API puller

Pulls *European* hospital/center sites from ClinicalTrials.gov for studies that:
- mention bladder-related terms (configurable),
- AND include at least one of these conditions (configurable): spinal cord injury, stroke,
  traumatic brain injury, spina bifida, multiple sclerosis.

Outputs a tidy CSV (and optional Excel) listing:
Hospital/Center, City, Country, Condition(s), Study Title, NCT ID, Location Status

Usage (examples):
  python pull_ctgov_eu_bladder_sites.py --outfile data/eu_bladder_sites_from_ctgov.csv --xlsx
  python pull_ctgov_eu_bladder_sites.py --terms bladder "lower urinary tract" \
      --conditions "spinal cord injury" stroke "traumatic brain injury" "spina bifida" "multiple sclerosis"
  python pull_ctgov_eu_bladder_sites.py --max-retries 12 --retry-backoff 2 --page-size 75

Dependencies:
  pip install requests pandas openpyxl
"""

import argparse
import sys
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd

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
    # e.g., (bladder OR "lower urinary tract") AND ("spinal cord injury" OR stroke ...)
    terms_clause = " OR ".join(f'"{t}"' if " " in t else t for t in terms)
    cond_clause = " OR ".join(f'"{c}"' if " " in c else c for c in conditions)
    return f'({terms_clause}) AND ({cond_clause})'

def make_session(max_retries=8, backoff=1.5):
    """Create a retrying requests.Session with sensible headers."""
    retry = Retry(
        total=max_retries,
        connect=max_retries,
        read=max_retries,
        status=max_retries,
        backoff_factor=backoff,                 # exponential backoff: 1.5, 3.0, 4.5, ...
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "spinalresearch-eu-bladder-sites/1.0 (+github actions)",
        "Accept": "application/json",
    })
    adapter = HTTPAdapter(max_retries=retry)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    return sess

def fetch_page(session, page_token, query, page_size=100, timeout=90):
    """Fetch one page with the retrying session + a small manual retry loop."""
    params = {
        "query.term": query,
        "pageSize": page_size,
        "fields": FIELDS,
        "format": "json",
    }
    if page_token:
        params["pageToken"] = page_token

    last_err = None
    for attempt in range(3):
        try:
            r = session.get(BASE, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            last_err = e
            time.sleep(2 + attempt * 2)  # small extra sleep on top of urllib3 backoff
    raise SystemExit(f"Failed calling ClinicalTrials.gov after retries: {last_err}")

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
    ap.add_argument("--terms", nargs="+", default=[
        "bladder","lower urinary tract","urodynamic","neurogenic detrusor","urinary incontinence"
    ], help="free-text terms to search in ClinicalTrials.gov")
    ap.add_argument("--conditions", nargs="+", default=[
        "spinal cord injury","stroke","traumatic brain injury","spina bifida","multiple sclerosis"
    ], help="conditions to include")
    ap.add_argument("--sleep", type=float, default=0.2, help="delay between pages (seconds)")
    ap.add_argument("--page-size", type=int, default=100, help="API page size (<= 100)")
    ap.add_argument("--max-retries", type=int, default=8, help="max retries for HTTP/connection errors")
    ap.add_argument("--retry-backoff", type=float, default=1.5, help="exponential backoff factor for retries")
    ap.add_argument("--timeout", type=int, default=90, help="per-request timeout (seconds)")
    args = ap.parse_args()

    query = build_query(args.terms, args.conditions)
    print("Query:", query, file=sys.stderr)

    session = make_session(max_retries=args.max_retries, backoff=args.retry_backoff)

    all_rows = []
    seen = set()
    token = None

    while True:
        data = fetch_page(session, token, query, page_size=args.page_size, timeout=args.timeout)
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
    # keep rows where title or conditions mention at least one term (double-check filter)
    if not df.empty:
        term_mask = pd.Series(False, index=df.index)
        for t in args.terms:
            term_mask = term_mask | df["Study Title"].str.contains(t, case=False, na=False) | \
                        df["Condition(s)"].str.contains(t, case=False, na=False)
        df = df[term_mask].copy()

    # light cleanup and ordering
    for col in ("Hospital/Center","City"):
        df[col] = df[col].fillna("").strip()
    df.sort_values(["Country","City","Hospital/Center","NCT ID"], inplace=True)

    # write outputs
    df.to_csv(args.outfile, index=False, encoding="utf-8-sig")
    print(f"Wrote {len(df)} rows to {args.outfile}")
    if args.xlsx:
        try:
            xls_path = args.outfile.rsplit(".",1)[0] + ".xlsx"
            df.to_excel(xls_path, index=False)
            print(f"Wrote Excel file: {xls_path}")
        except Exception as e:
            print(f"Excel write skipped (install openpyxl to enable): {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
