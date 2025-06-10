import requests
import os
from datetime import datetime
from supabase import create_client, Client

# Load environment variables
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
RESEND_API_KEY = os.environ["RESEND_API_KEY"]
EMAIL_TO = os.environ["EMAIL_TO"]
EMAIL_FROM = os.environ.get("EMAIL_FROM", "clinical-trials@yourdomain.com")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_trials():
    print("📥 Fetching from ClinicalTrials.gov v2 API...")

    url = "https://clinicaltrials.gov/api/v2/studies"
    payload = {
        "query": {
            "term": "spinal cord injury"
        },
        "page": 1,
        "pageSize": 100
    }

    response = requests.post(url, json=payload)
    print("Request URL:", response.url)
    response.raise_for_status()

    data = response.json()
    studies = data.get("studies", [])
    print(f"✅ Retrieved {len(studies)} trials.")
    return studies

def upsert_and_detect_changes(trials):
    new_trials = []
    changed_trials = []

    for trial in trials:
        try:
            protocol = trial.get("protocolSection", {})
            identification = protocol.get("identificationModule", {})
            status_module = protocol.get("statusModule", {})

            nct_id = identification.get("nctId")
            brief_title = identification.get("briefTitle")
            status = status_module.get("overallStatus")
            last_updated = status_module.get("lastUpdatePostDateStruct", {}).get("date")
            last_checked = datetime.utcnow().isoformat()

            if not nct_id:
                print(f"⚠️ Skipping trial with missing NCTId: {trial}")
                continue

            existing = (
                supabase.table("trials")
                .select("status")
                .eq("nct_id", nct_id)
                .maybe_single()
                .execute()
                .data
            )

            if not existing:
                print(f"🆕 New trial: {brief_title}")
                new_trials.append(brief_title)
            elif existing["status"] != status:
                print(f"🔄 Status change: {brief_title} ({existing['status']} → {status})")
                changed_trials.append(f"{brief_title} ({existing['status']} → {status})")

            supabase.table("trials").upsert({
                "nct_id": nct_id,
                "brief_title": brief_title,
                "status": status,
                "last_updated": last_updated,
                "last_checked": last_checked
            }).execute()

        except Exception as e:
            print(f"❌ Error processing trial: {e}")
            continue

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
