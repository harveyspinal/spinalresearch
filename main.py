import requests
import os
import time
from datetime import datetime, timedelta
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

def get_recent_activity():
    """Get trials added or changed in the last 30 days"""
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    thirty_days_ago_iso = thirty_days_ago.isoformat()
    
    try:
        # Get trials added in the last 30 days
        recent_new = (
            supabase.table("trials")
            .select("nct_id, brief_title, status, last_updated, last_checked")
            .gte("last_checked", thirty_days_ago_iso)
            .order("last_checked", desc=True)
            .limit(50)  # Limit to prevent email from being too long
            .execute()
        ).data or []
        
        # Get all trials to check for status changes in last 30 days
        # Note: This is a simplified approach. For production, you'd want a separate 
        # "status_history" table to track changes over time
        recent_trials = []
        for trial in recent_new:
            trial_info = {
                "nct_id": trial["nct_id"],
                "brief_title": trial["brief_title"],
                "status": trial["status"],
                "last_updated": trial["last_updated"] or "Not specified",
                "last_checked": trial["last_checked"],
                "url": f"https://clinicaltrials.gov/study/{trial['nct_id']}"
            }
            recent_trials.append(trial_info)
        
        return recent_trials
        
    except Exception as e:
        print(f"⚠️ Error fetching recent activity: {e}")
        return []

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

def send_email(new_trials, changed_trials, recent_activity=None):
    """Send detailed email notification with Spinal Research branding"""
    subject = "🧪 Clinical Trials Update: Spinal Cord Injury Research"
    html_parts = []
    
    # Header with Spinal Research branding
    html_parts.append("""
    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 800px; margin: 0 auto; background-color: #ffffff;">
        <!-- Header Banner -->
        <div style="background: linear-gradient(135deg, #1e40af 0%, #059669 100%); padding: 25px; text-align: center; border-radius: 8px 8px 0 0;">
            <h1 style="color: white; margin: 0; font-size: 28px; font-weight: 600; text-shadow: 0 2px 4px rgba(0,0,0,0.3);">
                🧬 Clinical Trials Research Update
            </h1>
            <p style="color: #e0f2fe; margin: 8px 0 0 0; font-size: 16px; font-weight: 300;">
                Spinal Cord Injury Research • Daily Monitoring Report
            </p>
        </div>
        
        <!-- Content Container -->
        <div style="padding: 30px; background-color: #fafbfc; border: 1px solid #e1e8ed; border-top: none; border-radius: 0 0 8px 8px;">
    """)
    
    # Daily Report Section (First)
    html_parts.append("""
        <div style="margin-bottom: 40px;">
            <h2 style="color: #1e40af; font-size: 22px; margin: 0 0 20px 0; padding-bottom: 10px; border-bottom: 3px solid #059669;">
                📊 Today's Activity Report
            </h2>
    """)
    
    if new_trials:
        html_parts.append(f"""
            <div style="margin-bottom: 30px;">
                <h3 style="color: #059669; font-size: 18px; margin: 0 0 15px 0; display: flex; align-items: center;">
                    <span style="background-color: #dcfce7; color: #166534; padding: 4px 12px; border-radius: 20px; font-size: 14px; font-weight: 600; margin-right: 10px;">
                        {len(new_trials)}
                    </span>
                    🆕 New Trials Discovered
                </h3>
        """)
        
        for trial in new_trials:
            html_parts.append(f"""
                <div style="background: white; border: 1px solid #e1e8ed; border-left: 4px solid #059669; border-radius: 6px; padding: 20px; margin: 15px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.05);">
                    <h4 style="margin: 0 0 12px 0; font-size: 16px; line-height: 1.4;">
                        <a href="{trial['url']}" style="color: #1e40af; text-decoration: none; font-weight: 600;" target="_blank">
                            {trial['nct_id']}: {trial['brief_title']}
                        </a>
                    </h4>
                    <div style="display: flex; flex-wrap: wrap; gap: 15px; align-items: center; color: #64748b; font-size: 14px;">
                        <div>
                            <strong style="color: #374151;">Status:</strong>
                            <span style="background: linear-gradient(135deg, #dcfce7, #bbf7d0); color: #166534; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600; margin-left: 5px;">
                                {trial['status']}
                            </span>
                        </div>
                        <div>
                            <strong style="color: #374151;">Last Updated:</strong> {trial['last_updated']}
                        </div>
                    </div>
                    <div style="margin-top: 12px;">
                        <a href="{trial['url']}" style="color: #1e40af; text-decoration: none; font-size: 13px; font-weight: 500;" target="_blank">
                            → View full details on ClinicalTrials.gov
                        </a>
                    </div>
                </div>
            """)
        
        html_parts.append("</div>")
    
    if changed_trials:
        html_parts.append(f"""
            <div style="margin-bottom: 30px;">
                <h3 style="color: #dc2626; font-size: 18px; margin: 0 0 15px 0; display: flex; align-items: center;">
                    <span style="background-color: #fee2e2; color: #dc2626; padding: 4px 12px; border-radius: 20px; font-size: 14px; font-weight: 600; margin-right: 10px;">
                        {len(changed_trials)}
                    </span>
                    🔄 Status Changes Detected
                </h3>
        """)
        
        for trial in changed_trials:
            html_parts.append(f"""
                <div style="background: white; border: 1px solid #e1e8ed; border-left: 4px solid #dc2626; border-radius: 6px; padding: 20px; margin: 15px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.05);">
                    <h4 style="margin: 0 0 12px 0; font-size: 16px; line-height: 1.4;">
                        <a href="{trial['url']}" style="color: #1e40af; text-decoration: none; font-weight: 600;" target="_blank">
                            {trial['nct_id']}: {trial['brief_title']}
                        </a>
                    </h4>
                    <div style="margin-bottom: 10px;">
                        <strong style="color: #374151;">Status Change:</strong>
                        <div style="margin-top: 8px; display: flex; align-items: center; gap: 10px;">
                            <span style="background: #fecaca; color: #dc2626; padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; text-decoration: line-through;">
                                {trial['old_status']}
                            </span>
                            <span style="color: #6b7280; font-weight: bold;">→</span>
                            <span style="background: linear-gradient(135deg, #dcfce7, #bbf7d0); color: #166534; padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 600;">
                                {trial['status']}
                            </span>
                        </div>
                    </div>
                    <div style="color: #64748b; font-size: 14px; margin-bottom: 12px;">
                        <strong style="color: #374151;">Last Updated:</strong> {trial['last_updated']}
                    </div>
                    <div>
                        <a href="{trial['url']}" style="color: #1e40af; text-decoration: none; font-size: 13px; font-weight: 500;" target="_blank">
                            → View full details on ClinicalTrials.gov
                        </a>
                    </div>
                </div>
            """)
        
        html_parts.append("</div>")
    
    if not new_trials and not changed_trials:
        html_parts.append("""
            <div style="text-align: center; padding: 40px; background: white; border-radius: 8px; border: 1px solid #e1e8ed;">
                <div style="font-size: 48px; margin-bottom: 15px;">✅</div>
                <h3 style="color: #059669; margin: 0 0 10px 0; font-size: 20px;">No Changes Today</h3>
                <p style="color: #64748b; margin: 0; font-size: 16px;">All spinal cord injury trials remain unchanged since yesterday's check.</p>
            </div>
        """)
    
    html_parts.append("</div>")  # End daily report section
    
    # Recent Activity Section (Second)
    if recent_activity:
        html_parts.append(f"""
            <div style="border-top: 2px solid #e1e8ed; padding-top: 30px;">
                <h2 style="color: #1e40af; font-size: 22px; margin: 0 0 20px 0; padding-bottom: 10px; border-bottom: 3px solid #059669;">
                    📈 Recent Activity (Last 30 Days)
                </h2>
                <p style="color: #64748b; margin: 0 0 25px 0; font-style: italic; background: #f8fafc; padding: 15px; border-radius: 6px; border-left: 4px solid #1e40af;">
                    Showing {len(recent_activity)} trials that were added to our monitoring system in the last 30 days (limited to 50 most recent).
                </p>
                
                <div style="display: grid; gap: 12px;">
        """)
        
        for trial in recent_activity:
            # Calculate days ago
            try:
                checked_date = datetime.fromisoformat(trial['last_checked'].replace('Z', '+00:00'))
                days_ago = (datetime.utcnow().replace(tzinfo=checked_date.tzinfo) - checked_date).days
                if days_ago == 0:
                    days_text = "Today"
                    days_color = "#059669"
                elif days_ago == 1:
                    days_text = "Yesterday"
                    days_color = "#0891b2"
                else:
                    days_text = f"{days_ago} days ago"
                    days_color = "#64748b"
            except:
                days_text = "Recently"
                days_color = "#64748b"
            
            html_parts.append(f"""
                <div style="background: white; border: 1px solid #e1e8ed; border-radius: 6px; padding: 16px; transition: all 0.2s;">
                    <div style="display: flex; justify-content: between; align-items: flex-start; margin-bottom: 8px;">
                        <h5 style="margin: 0; font-size: 14px; font-weight: 600; flex: 1; line-height: 1.3;">
                            <a href="{trial['url']}" style="color: #1e40af; text-decoration: none;" target="_blank">
                                {trial['nct_id']}: {trial['brief_title'][:85]}{'...' if len(trial['brief_title']) > 85 else ''}
                            </a>
                        </h5>
                        <span style="background: {days_color}; color: white; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; white-space: nowrap; margin-left: 10px;">
                            {days_text}
                        </span>
                    </div>
                    <div style="display: flex; flex-wrap: wrap; gap: 15px; color: #64748b; font-size: 12px;">
                        <div>
                            <strong>Status:</strong>
                            <span style="background: #f1f5f9; color: #475569; padding: 1px 6px; border-radius: 4px; margin-left: 3px;">
                                {trial['status']}
                            </span>
                        </div>
                        <div>
                            <strong>Last Updated:</strong> {trial['last_updated']}
                        </div>
                    </div>
                </div>
            """)
        
        html_parts.append("</div></div>")  # End recent activity section
    
    # Footer with Spinal Research branding
    total_today = len(new_trials) + len(changed_trials)
    html_parts.append(f"""
            <!-- Footer -->
            <div style="margin-top: 40px; padding: 25px; background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%); border-radius: 8px; border: 1px solid #e1e8ed;">
                <div style="text-align: center; margin-bottom: 20px;">
                    <div style="color: #1e40af; font-size: 18px; font-weight: 600; margin-bottom: 5px;">
                        📊 Report Summary
                    </div>
                    <div style="color: #374151; font-size: 14px;">
                        <strong>{total_today}</strong> changes today • <strong>{len(recent_activity) if recent_activity else 0}</strong> trials added in last 30 days
                    </div>
                </div>
                
                <div style="text-align: center; padding-top: 20px; border-top: 1px solid #cbd5e1; color: #64748b; font-size: 12px;">
                    <p style="margin: 0 0 8px 0;">
                        <strong>Automated Clinical Trials Monitoring</strong><br>
                        Generated on {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}
                    </p>
                    <p style="margin: 0; color: #94a3b8;">
                        Supporting spinal cord injury research • Together we can cure paralysis
                    </p>
                </div>
            </div>
        </div>  <!-- End content container -->
    </div>  <!-- End main container -->
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
        
        # Get recent activity for the last 30 days
        recent_activity = get_recent_activity()
        
        print("📨 Sending email...")
        print(f"New trials today: {len(new_trials)}")
        print(f"Changed trials today: {len(changed_trials)}")
        print(f"Recent activity (30 days): {len(recent_activity)}")
        
        send_email(new_trials, changed_trials, recent_activity)
        print("✅ Process completed successfully")
    except Exception as e:
        print(f"❌ Main process failed: {e}")
        raise

if __name__ == "__main__":
    main()
