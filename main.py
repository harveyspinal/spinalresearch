import requests
import os
from datetime import datetime
from supabase import create_client, Client

# 🌍 Env vars from GitHub Actions or .env
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
RESEND_API_KEY = os.environ["RESEND_API_KEY"]
EMAIL_TO = os.environ["EMAIL_TO"]
EMAIL_FROM = os.environ.get("EMAIL_FROM", "onboarding@resend.dev")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def fetch_trials(page=1, page_size=100):
    print("📥 Fetching from ClinicalTrials.gov v2 API...")
    url = "https://clinicaltrials.gov/api/v2/studies"
    params = {
        "query": "spinal cord injury",
        "pageSize": page_size,
        "page": page
    }

    response = requests.get(url, params=params)
    print("Request URL:", response.url)
    response.raise_for_status()
    data = response.json()
    studies = data.get("studies", [])
    print(f"✅ Page {page}: Retrieved {len(studies)} trials.")
    return studies


def upsert_and_detect_changes(trials):
    new_trials = []
    changed_trials = []

    for trial in trials:
        try:
            nct_id = trial["protocolSection"]["identificationModule"]["nctId"]
            brief_title = trial["protocolSection"]["identificationModule"]["briefTitle"]
            status = trial["protocolSection"]["statusModule"]["overallStatus"]
            last_updated = trial["protocolSection"]["statusModule"]["lastUpdatePostDateStruct"]["date"]
            last_checked = datetime.utcnow().isoformat()
        except KeyError as e:
            print(f"⚠️ Skipping trial with missing data: {e}")
            continue

        # Check existing status
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

        # Upsert the trial
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
    all_trials = []
    page = 1

    while True:
        trials = fetch_trials(page)
        if not trials:
            break
        all_trials.extend(trials)
        if len(trials) < 100:
            break
        page += 1

    print(f"📦 Total trials fetched: {len(all_trials)}")

    new_trials, changed_trials = upsert_and_detect_changes(all_trials)
    print("📨 Sending email...")
    print("New trials:", new_trials)
    print("Changed trials:", changed_trials)
    send_email(new_trials, changed_trials)


if __name__ == "__main__":
    main()
