import requests
import os
from datetime import datetime
from supabase import create_client, Client

# --- Environment Variables ---
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
RESEND_API_KEY = os.environ["RESEND_API_KEY"]
EMAIL_TO = os.environ["EMAIL_TO"]
EMAIL_FROM = os.environ.get("EMAIL_FROM", "clinical-trials@yourdomain.com")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Fetch Trials from ClinicalTrials.gov ---
def fetch_trials():
    url = "https://clinicaltrials.gov/api/v2/studies"
    params = {
        "query.term": "spinal cord injury",
        "pageSize": 100,
        "fields": "NCTId,BriefTitle,OverallStatus,LastUpdatePostDate",
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    studies = response.json().get("studies", [])
    print(f"📥 Fetched {len(studies)} trials.")
    return studies

# --- Upsert Trials & Detect Changes ---
def upsert_and_detect_changes(trials):
    new_trials = []
    changed_trials = []

    for trial in trials:
        nct_id = trial.get("NCTId")
        if not nct_id:
            print("⚠️ Skipping trial with missing NCTId:", trial)
            continue

        brief_title = trial.get("BriefTitle")
        status = trial.get("OverallStatus")
        last_updated = trial.get("LastUpdatePostDate")
        last_checked = datetime.utcnow().isoformat()

        # Safely fetch existing trial by NCTId
        result = (
            supabase.table("trials")
            .select("status")
            .eq("nct_id", nct_id)
            .maybe_single()
            .execute()
        )

        existing = result.data if result and hasattr(result, "data") else None

        if not existing:
            print(f"🆕 New trial: {brief_title}")
            new_trials.append(brief_title)
        elif existing["status"] != status:
            print(f"🔄 Status change: {brief_title} ({existing['status']} → {status})")
            changed_trials.append(f"{brief_title} ({existing['status']} → {status})")

        # Upsert trial record
        upsert_payload = {
            "nct_id": nct_id,
            "brief_title": brief_title,
            "status": status,
            "last_updated": last_updated,
            "last_checked": last_checked,
        }

        supabase.table("trials").upsert(upsert_payload).execute()

    return new_trials, changed_trials

# --- Email Summary via Resend ---
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
    print(f"📤 Email sent with status code {response.status_code}")

# --- Entrypoint ---
def main():
    trials = fetch_trials()
    new_trials, changed_trials = upsert_and_detect_changes(trials)
    send_email(new_trials, changed_trials)

if __name__ == "__main__":
    main()
