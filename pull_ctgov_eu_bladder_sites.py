#!/usr/bin/env python3

"""
pull_ctgov_eu_bladder_sites.py — ClinicalTrials.gov v2 API puller (with investigators)

Adds investigator and contact columns:
- Overall Officials: PI/Study Director/Chair (name, role, affiliation)
- Site Contacts: names/roles listed for each site (if present)

Usage examples:
  python pull_ctgov_eu_bladder_sites.py --outfile data/eu_bladder_sites_from_ctgov.csv --xlsx
  python pull_ctgov_eu_bladder_sites.py --max-retries 12 --retry-backoff 2 --page-size 75
"""

import argparse, sys, time, requests, pandas as pd
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

EUROPE_COUNTRIES = {
    "Albania","Andorra","Austria","Belarus","Belgium","Bosnia and Herzegovina","Bulgaria","Croatia","Cyprus",
    "Czechia","Czech Republic","Denmark","Estonia","Finland","France","Germany","Greece","Hungary","Iceland",
    "Ireland","Italy","Kosovo","Latvia","Liechtenstein","Lithuania","Luxembourg","Malta","Moldova","Monaco",
    "Montenegro","Netherlands","North Macedonia","Norway","Poland","Portugal","Romania","San Marino","Serbia",
    "Slovakia","Slovenia","Spain","Sweden","Switzerland","Türkiye","Turkey","Ukraine","United Kingdom","UK",
    "England","Scotland","Wales","Northern Ireland"
}

BASE = "https://clinicaltrials.gov/api/v2/studies"
# Keep the payload small; ContactsLocationsModule includes officials/contacts/locations.
FIELDS = ",".join([
    "NCTId","BriefTitle","OfficialTitle",
    "Condition","ContactsLocationsModule",
    "LocationFacility","LocationCity","LocationCountry","LocationStatus"
])

def build_query(terms, conditions):
    terms_clause = " OR ".join(f'"{t}"' if " " in t else t for t in terms)
    cond_clause  = " OR ".join(f'"{c}"' if " " in c else c for c in conditions)
    return f'({terms_clause}) AND ({cond_clause})'

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def make_session(max_retries=8, backoff=1.5):
    retry = Retry(
        total=max_retries, connect=max_retries, read=max_retries, status=max_retries,
        backoff_factor=backoff, status_forcelist=[429,500,502,503,504],
        allowed_methods=["GET"], raise_on_status=False, respect_retry_after_header=True,
    )
    s = requests.Session()
    s.headers.update({"User-Agent":"spinalresearch-eu-bladder-sites/1.1 (+github actions)","Accept":"application/json"})
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter); s.mount("http://", adapter)
    return s

def fetch_page(session, page_token, query, page_size=100, timeout=90):
    params = {"query.term":query, "pageSize":page_size, "fields":FIELDS, "format":"json"}
    if page_token: params["pageToken"] = page_token
    last_err = None
    for attempt in range(3):
        try:
            r = session.get(BASE, params=params, timeout=timeout)
            r.raise_for_status(); return r.json()
        except requests.RequestException as e:
            last_err = e; time.sleep(2 + attempt*2)
    raise SystemExit(f"Failed calling ClinicalTrials.gov after retries: {last_err}")

def fmt_overall_officials(overall_officials):
    items = []
    for o in overall_officials or []:
        name = (o.get("name") or "").strip()
        role = (o.get("role") or "").strip()
        aff  = (o.get("affiliation") or "").strip()
        if name or role or aff:
            part = f"{role}: {name}" if role else name
            if aff: part += f" ({aff})"
            items.append(part)
    return "; ".join(items)

def fmt_contacts(contacts):
    items = []
    for c in contacts or []:
        nm = (c.get("name") or "").strip()
        rl = (c.get("role") or "").strip()
        if nm or rl:
            items.append(f"{rl}: {nm}" if rl else nm)
    return "; ".join(items)

def extract_rows(payload):
    rows = []
    for s in payload.get("studies", []):
        proto = s.get("protocolSection", {}) or {}
        ident = proto.get("identificationModule", {}) or {}
        nct   = ident.get("nctId")
        title = ident.get("officialTitle") or ident.get("briefTitle")
        conds = proto.get("conditionsModule", {}).get("conditions", []) or []
        clm   = proto.get("contactsLocationsModule", {}) or {}

        overall_officials = fmt_overall_officials(clm.get("overallOfficials"))
        central_contacts  = fmt_contacts(clm.get("centralContacts"))

        for loc in (clm.get("locations") or []):
            country = loc.get("country")
            if not country or country not in EUROPE_COUNTRIES: 
                continue
            site_contacts = fmt_contacts(loc.get("contacts"))
            site_invs = []
            for key in ("investigators","investigator","siteInvestigators"):
                if key in (loc or {}):
                    for inv in (loc.get(key) or []):
                        nm = (inv.get("name") or inv.get("fullName") or "").strip()
                        rl = (inv.get("role") or "").strip()
                        site_invs.append(f"{rl}: {nm}" if rl and nm else (nm or rl))
            rows.append({
                "Hospital/Center": loc.get("facility"),
                "City": loc.get("city"),
                "Country": country,
                "Condition(s)": "; ".join(conds),
                "Study Title": title,
                "NCT ID": nct,
                "Location Status": loc.get("status"),
                "Overall Officials": overall_officials,
                "Central Contacts": central_contacts,
                "Site Contacts": site_contacts,
                "Site Investigator(s)": "; ".join([x for x in site_invs if x]),
            })
    return rows

def main():
    import argparse
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

    all_rows, seen, token = [], set(), None
    while True:
        data = fetch_page(session, token, query, page_size=args.page_size, timeout=args.timeout)
        for r in extract_rows(data):
            key = (r["NCT ID"], r["Hospital/Center"], r["City"], r["Country"], r["Location Status"])
            if key in seen: continue
            seen.add(key); all_rows.append(r)
        token = data.get("nextPageToken")
        if not token: break
        time.sleep(args.sleep)

    df = pd.DataFrame(all_rows)
    # Ensure columns exist for robust cleanup
    for col in ["Study Title","Condition(s)","Hospital/Center","City","Country","NCT ID","Location Status",
                "Overall Officials","Central Contacts","Site Contacts","Site Investigator(s)"]:
        if col not in df.columns: df[col] = ""

    # Keep rows where title or conditions mention at least one term
    if not df.empty:
        term_mask = pd.Series(False, index=df.index)
        for t in args.terms:
            term_mask |= df["Study Title"].str.contains(t, case=False, na=False) | \
                         df["Condition(s)"].str.contains(t, case=False, na=False)
        df = df[term_mask].copy()

    # Cleanup + sort
    df["Hospital/Center"] = df["Hospital/Center"].fillna("").str.strip()
    df["City"]            = df["City"].fillna("").str.strip()
    df.sort_values(["Country","City","Hospital/Center","NCT ID"], inplace=True)

    df.to_csv(args.outfile, index=False, encoding="utf-8-sig")
    print(f"Wrote {len(df)} rows to {args.outfile}")
    if args.xlsx:
        try:
            xls = args.outfile.rsplit(".",1)[0] + ".xlsx"
            df.to_excel(xls, index=False); print(f"Wrote Excel file: {xls}")
        except Exception as e:
            print(f"Excel write skipped (install openpyxl to enable): {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
