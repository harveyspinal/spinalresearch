#!/usr/bin/env python3
# (Corrected) pull_ctgov_eu_bladder_sites.py — with retry/backoff and robust pandas cleanup
# See chat for full docstring and usage.

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
    terms_clause = " OR ".join(f'"{t}"' if " " in t else t for t in terms)
    cond_clause = " OR ".join(f'"{c}"' if " " in c else c for c in conditions)
    return f'({terms_clause}) AND ({cond_clause})'

def make_session(max_retries=8, backoff=1.5):
    retry = Retry(
        total=max_retries,
        connect=max_retries,
        read=max_retries,
        status=max_retries,
        backoff_factor=backoff,
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
            time.sleep(2 + attempt * 2)
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
    ap.add_argument("--xlsx", action="store_true")
    ap.add_argument("--terms", nargs="+", default=[
        "bladder","lower urinary tract","urodynamic","neurogenic detrusor","urinary incontinence"
    ])
    ap.add_argument("--conditions", nargs="+", default=[
        "spinal cord injury","stroke","traumatic brain injury","spina bifida","multiple sclerosis"
    ])
    ap.add_argument("--sleep", type=float, default=0.2)
    ap.add_argument("--page-size", type=int, default=100)
    ap.add_argument("--max-retries", type=int, default=8)
    ap.add_argument("--retry-backoff", type=float, default=1.5)
    ap.add_argument("--timeout", type=int, default=90)
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

    # Ensure required columns exist before filtering/cleanup
    for col in ["Study Title", "Condition(s)", "Hospital/Center", "City", "Country", "NCT ID", "Location Status"]:
        if col not in df.columns:
            df[col] = ""

    # keep rows where title or conditions mention at least one term
    if not df.empty:
        term_mask = pd.Series(False, index=df.index)
        for t in args.terms:
            term_mask = term_mask | df["Study Title"].str.contains(t, case=False, na=False) | \
                        df["Condition(s)"].str.contains(t, case=False, na=False)
        df = df[term_mask].copy()

    # cleanup
    df["Hospital/Center"] = df["Hospital/Center"].fillna("").str.strip()
    df["City"] = df["City"].fillna("").str.strip()

    # sort & write
    df.sort_values(["Country","City","Hospital/Center","NCT ID"], inplace=True)
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
