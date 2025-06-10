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
    """Upsert trials and detect changes - return detailed trial info"""
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
            # Query existing trial with better error handling
            result = (
                supabase.table("trials")
                .select("status")
                .eq("nct_id", nct_id)
                .maybe_single()
                .execute()
            )
            
            existing = result.data if result else None

            # Create detailed trial info dictionary
            trial_info = {
                "nct_id": nct_id,
                "brief_title": brief_title,
                "status": status,
                "last_updated": last_updated if last_updated and last_updated.strip() else "Not specified",
                "url": f"https://clinicaltrials.gov/study/{nct_id}"
            }

            if not existing:
                new_trials.append(trial_info)
            elif existing.get("status") != status:
                trial_info["old_status"] = existing.get("status", "Unknown")
                changed_trials.append(trial_info)

            # Handle empty date strings - convert to None for database
            processed_last_updated = last_updated if last_updated and last_updated.strip() else None

            supabase.table("trials").upsert({
                "nct_id": nct_id,
                "brief_title": brief_title,
                "status": status,
                "last_updated": processed_last_updated,
                "last_checked": last_checked
            }).execute()
            
        except Exception as e:
            print(f"⚠️ Database error for trial {nct_id}: {e}")
            continue

    return new_trials, changed_trials

def send_email(new_trials, changed_trials):
    """Send detailed email notification with trial information"""
    subject = "🧪 Clinical Trials Update: Spinal Cord Injury"
    html_parts = []
    
    # Header styling
    html_parts.append("""
    <div style="font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto;">
        <h2 style="color: #2563eb; border-bottom: 2px solid #e5e7eb; padding-bottom: 10px;">
            🧪 Clinical Trials Update: Spinal Cord Injury
        </h2>
    """)
    
    if new_trials:
        html_parts.append(f"""
        <h3 style="color: #059669; margin-top: 30px;">🆕 New Trials ({len(new_trials)})</h3>
        """)
        
        for trial in new_trials:
            html_parts.append(f"""
            <div style="border: 1px solid #d1d5db; border-radius: 8px; padding: 15px; margin: 10px 0; background-color: #f9fafb;">
                <h4 style="color: #1f2937; margin: 0 0 10px 0;">
                    <a href="{trial['url']}" style="color: #2563eb; text-decoration: none;">
                        {trial['nct_id']}: {trial['brief_title']}
                    </a>
                </h4>
                <p style="margin: 5px 0; color: #4b5563;">
                    <strong>Status:</strong> <span style="background-color: #dbeafe; padding: 2px 6px; border-radius: 4px; font-size: 12px;">{trial['status']}</span>
                </p>
                <p style="margin: 5px 0; color: #4b5563;">
                    <strong>Last Updated:</strong> {trial['last_updated']}
                </p>
                <p style="margin: 5px 0;">
                    <a href="{trial['url']}" style="color: #2563eb; text-decoration: none; font-size: 14px;">
                        → View on ClinicalTrials.gov
                    </a>
                </p>
            </div>
            """)
    
    if changed_trials:
        html_parts.append(f"""
        <h3 style="color: #dc2626; margin-top: 30px;">🔄 Status Changes ({len(changed_trials)})</h3>
        """)
        
        for trial in changed_trials:
            html_parts.append(f"""
            <div style="border: 1px solid #d1d5db; border-radius: 8px; padding: 15px; margin: 10px 0; background-color: #fffbeb;">
                <h4 style="color: #1f2937; margin: 0 0 10px 0;">
                    <a href="{trial['url']}" style="color: #2563eb; text-decoration: none;">
                        {trial['nct_id']}: {trial['brief_title']}
                    </a>
                </h4>
                <p style="margin: 5px 0; color: #4b5563;">
                    <strong>Status Change:</strong> 
                    <span style="background-color: #fecaca; padding: 2px 6px; border-radius: 4px; font-size: 12px; text-decoration: line-through;">{trial['old_status']}</span>
                    →
                    <span style="background-color: #bbf7d0; padding: 2px 6px; border-radius: 4px; font-size: 12px;">{trial['status']}</span>
                </p>
                <p style="margin: 5px 0; color: #4b5563;">
                    <strong>Last Updated:</strong> {trial['last_updated']}
                </p>
                <p style="margin: 5px 0;">
                    <a href="{trial['url']}" style="color: #2563eb; text-decoration: none; font-size: 14px;">
                        → View on ClinicalTrials.gov
                    </a>
                </p>
            </div>
            """)
    
    if not new_trials and not changed_trials:
        html_parts.append("""
        <div style="text-align: center; padding: 30px; color: #6b7280;">
            <h3 style="color: #059669;">✅ No new or changed trials today</h3>
            <p>All spinal cord injury trials remain unchanged since the last check.</p>
        </div>
        """)
    
    # Footer
    html_parts.append(f"""
        <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #e5e7eb; color: #6b7280; font-size: 12px;">
            <p>This automated report was generated on {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}.</p>
            <p>Monitoring {len(new_trials) + len(changed_trials)} trials related to spinal cord injury research.</p>
        </div>
    </div>
    """)
    
    html_content = "".join(html_parts)

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
                "html": html_content,
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
