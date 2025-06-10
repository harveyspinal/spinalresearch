import requests
import os
from datetime import datetime
import math
from supabase import create_client, Client

# 🔐 Environment Variables
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
RESEND_API_KEY = os.environ["RESEND_API_KEY"]
EMAIL_TO = os.environ["EMAIL_TO"]
EMAIL_FROM = os.environ.get("EMAIL_FROM", "onboarding@resend.dev")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_trials():
    print("📥 Fetching first page...")

    url = "https://clinicaltrials.gov/api/v2/studies"
    params = {
        "query.term": "spinal cord injury",
        "fields": "protocolSection",
        "pageSize": 100,
        "page": 1
    }

    response = requests.get(url, params=params)
    print("Request URL:", response.url)
    response.raise_for_status()

    data = response.json()
    studies = data.get("studies", [])
    print(f"✅ Retrieved {len(studies)} studies.")
    return studies

    response = requests.get(url, params=params)
    print("Request URL:", response.url)  # Helpful for debugging
    response.raise_for_status()
    return response.json().get("studies", [])

def upsert_and_detect_changes(trials):
    new_trials = []
    changed_trials = []
    now = datetime.utcnow().isoformat()

    for trial in trials:
        section = trial.get("protocolSection", {})
        id_mod = section.get("identificationModule", {})
        status_mod = section.get("statusModule", {})

        nct_id = id_mod.get("nctId")
        brief_title = id_mod.get("briefTitle")
        status = status_mod.get("overallStatus")
        last_updated = status_mod.get("lastUpdatePostDateStruct", {}).get("date")

        if not nct_id:
            print(f"⚠️ Skipping trial with missing NCTId: {trial}")
            continue

        response = supabase.table("trials") \
            .select("status") \
            .eq("nct_id", nct_id) \
            .maybe_single() \
            .execute()

        existing = getattr(response, "data", None)

        if not existing:
            print(f"🆕 New trial: {nct_id} - {brief_title}")
            new_trials.append(brief_title)
        elif existing["status"] != status:
            print(f"🔄 Status changed for {nct_id}: {existing['status']} → {status}")
            changed_trials.append(f"{brief_title} ({existing['status']} → {status})")

        # Upsert data into Supabase
        supabase.table("trials").upsert({
            "nct_id": nct_id,
            "brief_title": brief_title,
            "status": status,
            "last_updated": last_updated,
            "last_checked": now
        }).execute()

    return new_trials, changed_trials

def send_email(new_trials, changed_trials):
    subject = "🧪 Clinical Trials Update: Spinal Cord Injury"
    lines = []

    if new_trials:
        lines.append("🆕 New Trials:\n" + "\n".join(f"- {t}" for t in new_trials))
    if changed_trials:
        lines.append("🔄 Status Changes:\n" + "\n".join(f"- {t}" for t in changed_trials))
    if not lines:
        lines.append("✅ No new or changed trials today.")

    html = "<br>".join(line.replace("\n", "<br>") for line in lines)

    print("📨 Sending email...")
    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "from": EMAIL_FROM,
            "to": [EMAIL_TO],
            "subject": subject,
            "html": html,
        },
    )
    print(f"📧 Email sent. Status code: {response.status_code}")

def main():
    trials = fetch_trials()
    new_trials, changed_trials = upsert_and_detect_changes(trials)
    send_email(new_trials, changed_trials)

if __name__ == "__main__":
    main()
