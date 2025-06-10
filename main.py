import requests
import os
import time
from datetime import datetime
from supabase import create_client, Client

# 🔐 Environment variables
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
RESEND_API_KEY = os.environ["RESEND_API_KEY"]
EMAIL_TO = os.environ["EMAIL_TO"]
EMAIL_FROM = os.environ.get("EMAIL_FROM", "onboarding@resend.dev")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_trials():
    """Fetch trials using the new ClinicalTrials.gov API v2"""
    print("📥 Fetching from ClinicalTrials.gov v2 API...")

    all_trials = []
    base_url = "https://clinicaltrials.gov/api/v2/studies"
    
    # Start with first page
    next_page_token = None
    page_num = 1
    
    while True:
        params = {
            "format": "json",
            "query.cond": "spinal cord injury",
            "fields": "NCTId,BriefTitle,OverallStatus,LastUpdatePostDate",
            "pageSize": 100,
        }
        
        # Add page token if we have one (for subsequent pages)
        if next_page_token:
            params["pageToken"] = next_page_token
        
        try:
            print(f"🔄 Fetching page {page_num}...")
            response = requests.get(base_url, params=params, timeout=30)
            print("Request URL:", response.url)
            response.raise_for_status()
            
            data = response.json()
            
            # Extract studies from the response
            studies = data.get("studies", [])
            print(f"✅ Retrieved {len(studies)} trials from page {page_num}")
            
            if not studies:
                break
                
            # Process each study to extract the fields we need
            for study in studies:
                try:
                    protocol_section = study.get("protocolSection", {})
                    identification_module = protocol_section.get("identificationModule", {})
                    status_module = protocol_section.get("statusModule", {})
                    
                    trial_data = {
                        "NCTId": [identification_module.get("nctId", "")],
                        "BriefTitle": [identification_module.get("briefTitle", "")],
                        "OverallStatus": [status_module.get("overallStatus", "")],
                        "LastUpdatePostDate": [status_module.get("lastUpdatePostDate", "")]
                    }
                    
                    all_trials.append(trial_data)
                    
                except Exception as e:
                    print(f"⚠️ Error processing study: {e}")
                    continue
            
            # Check if there are more pages
            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break
                
            page_num += 1
            time.sleep(0.5)  # Be respectful to the API
            
        except requests.exceptions.RequestException as e:
            print(f"❌ API request failed: {e}")
            break
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            break

    print(f"✅ Total trials fetched: {len(all_trials)}")
    return all_trials

def upsert_and_detect_changes(trials):
    """Upsert trials and detect changes - same logic as before"""
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

        try:
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
            
        except Exception as e:
            print(f"⚠️ Database error for trial {nct_id}: {e}")
            continue

    return new_trials, changed_trials

def send_email(new_trials, changed_trials):
    """Send email notification - same logic as before"""
    subject = "🧪 Clinical Trials Update: Spinal Cord Injury"
    lines = []
    if new_trials:
        lines.append("🆕 New Trials:\n" + "\n".join(f"- {t}" for t in new_trials))
    if changed_trials:
        lines.append("🔄 Status Changes:\n" + "\n".join(f"- {t}" for t in changed_trials))
    if not lines:
        lines.append("✅ No new or changed trials today.")

    html = "<br>".join(line.replace("\n", "<br>") for line in lines)

    try:
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
            timeout=30
        )

        print(f"📧 Email sent. Status code: {response.status_code}")
        if response.status_code >= 400:
            print("❌ Email error:", response.text)
    except Exception as e:
        print(f"❌ Failed to send email: {e}")

def main():
    """Main function"""
    try:
        trials = fetch_trials()
        if not trials:
            print("⚠️ No trials fetched, skipping email")
            return
            
        new_trials, changed_trials = upsert_and_detect_changes(trials)
        print("📨 Sending email...")
        print("New trials:", len(new_trials))
        print("Changed trials:", len(changed_trials))
        send_email(new_trials, changed_trials)
        print("✅ Process completed successfully")
    except Exception as e:
        print(f"❌ Main process failed: {e}")
        raise

if __name__ == "__main__":
    main()
