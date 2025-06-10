import requests
import os
from datetime import datetime
from supabase import create_client, Client

# 🔐 Environment variables
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
RESEND_API_KEY = os.environ["RESEND_API_KEY"]
EMAIL_TO = os.environ["EMAIL_TO"]
EMAIL_FROM = os.environ.get("EMAIL_FROM", "onboarding@resend.dev")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 📦 Fields we want from the API
FIELDS = ["NCTId", "BriefTitle", "OverallStatus", "LastUpdatePostDate"]
PAGE_SIZE = 100  # Max page size

def fetch_trials():
    print("📥 Fetching from ClinicalTrials.gov v1 API...")

    all_trials = []
    base_url = "https://clinicaltrials.gov/api/query/study_fields"

    rank = 1
    while True:
        params = {
            "expr": "spinal cord injury",
            "fields": ",".join(FIELDS),
            "min_rnk": rank,
            "max_rnk": rank + PAGE_SIZE - 1,
            "fmt": "JSON"
        }

        response = requests.get(base_url, params=params)
        print(f"🔄 Fetching rank {rank} to {rank + PAGE_SIZE - 1}...")
        print("Request URL:", response.url)
        response.raise_for_status()

        data = response.json()
        studies = data["StudyFieldsResponse"]["StudyFields"]
        print(f"✅ Retrieved {len(studies)} trials")

        if not studies:
            break

        all_trials.extend(studies)
        rank += PAGE_SIZE

    print(f"✅ Total trials fetched: {len(all_trials)}")
    return all_trials

def upsert_and_detect_changes(trials):
    new_trials = []
    changed_trials = []

    for trial in trials:
        try:
            nct_id = trial["NCTId"][0]
            brief_title = trial["BriefTitle"][0]
            status = trial["OverallStatus"][0]
            last_updated = trial["LastUpdatePostDate"][0]
            last_checked = datetime.utcnow().isoformat()
        except (KeyError, IndexError) as e:
            print(f"⚠️ Skipping trial due to missing data: {e}")
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
            new_trials.append(brief_title)
        elif existing["status"] != status:
            changed_trials.append(f"{brief_title} ({existing['status']} → {status})")

        supabase.table("trials").upsert({
            "nct_id": nct_id,
            "brief_title": brief_title,
            "status": status,
            "last_updated": last_updated,
            "last_checked": last_checked
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
    if response.status_code >= 400:
        print("❌ Email error:", response.text)

def main():
    trials = fetch_trials()
    new_trials, changed_trials = upsert_and_detect_changes(trials)
    print("📨 Sending email...")
    print("New trials:", new_trials)
    print("Changed trials:", changed_trials)
    send_email(new_trials, changed_trials)

if __name__ == "__main__":
    main()
