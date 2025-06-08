import requests
import os
from datetime import datetime
from supabase import create_client, Client

# Env vars
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
RESEND_API_KEY = os.environ["RESEND_API_KEY"]
EMAIL_TO = os.environ["EMAIL_TO"]
EMAIL_FROM = os.environ.get("EMAIL_FROM", "harvey.sihota@gmail.com")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_trials():
    url = "https://clinicaltrials.gov/api/v2/studies"
    params = {
        "query.term": "spinal cord injury",
        "pageSize": 100,
        "fields": "protocolSection.identificationModule.nctId,protocolSection.identificationModule.briefTitle,protocolSection.statusModule.overallStatus,protocolSection.statusModule.lastUpdatePostDateStruct.date",
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()
    trials = data.get("studies", [])
    print(f"📥 Fetched {len(trials)} trials.")
    return trials

def upsert_and_detect_changes(trials):
    new_trials = []
    changed_trials = []

    for trial in trials:
        try:
            nct_id = trial["protocolSection"]["identificationModule"]["nctId"]
            brief_title = trial["protocolSection"]["identificationModule"]["briefTitle"]
            status = trial["protocolSection"]["statusModule"]["overallStatus"]
            last_updated = trial["protocolSection"]["statusModule"]["lastUpdatePostDateStruct"]["date"]
        except KeyError as e:
            print(f"⚠️ Skipping trial due to missing field {e}: {trial}")
            continue

        last_checked = datetime.utcnow().isoformat()

        existing = (
            supabase.table("trials")
            .select("status")
            .eq("nct_id", nct_id)
            .maybe_single()
            .execute()
        )

        existing_data = getattr(existing, "data", None)

        if not existing_data:
            new_trials.append(brief_title)
        elif existing_data["status"] != status:
            changed_trials.append(f"{brief_title} ({existing_data['status']} → {status})")

        upsert_payload = {
            "nct_id": nct_id,
            "brief_title": brief_title,
            "status": status,
            "last_updated": last_updated,
            "last_checked": last_checked
        }

        supabase.table("trials").upsert(upsert_payload).execute()

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
    print("📨 Sending email...")
    print("New trials:", new_trials)
    print("Changed trials:", changed_trials)
    send_email(new_trials, changed_trials)

if __name__ == "__main__":
    main()
