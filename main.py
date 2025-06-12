import requests
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from supabase import create_client, Client

# 🔐 Environment variables
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
RESEND_API_KEY = os.environ["RESEND_API_KEY"]
EMAIL_TO = os.environ["EMAIL_TO"]
EMAIL_FROM = os.environ.get("EMAIL_FROM", "onboarding@resend.dev")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_clinicaltrials_gov():
    """Fetch trials from ClinicalTrials.gov API v2"""
    print("📥 Fetching from ClinicalTrials.gov v2 API...")

    all_trials = []
    base_url = "https://clinicaltrials.gov/api/v2/studies"
    
    next_page_token = None
    page_num = 1
    
    while True:
        params = {
            "format": "json",
            "query.cond": "spinal cord injury",
            "fields": "NCTId,BriefTitle,OverallStatus,LastUpdatePostDate",
            "pageSize": 100,
        }
        
        if next_page_token:
            params["pageToken"] = next_page_token
        
        try:
            print(f"🔄 ClinicalTrials.gov - Fetching page {page_num}...")
            response = requests.get(base_url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            studies = data.get("studies", [])
            print(f"✅ ClinicalTrials.gov - Retrieved {len(studies)} trials from page {page_num}")
            
            if not studies:
                break
                
            # Process each study to extract the fields we need
            for study in studies:
                try:
                    protocol_section = study.get("protocolSection", {})
                    identification_module = protocol_section.get("identificationModule", {})
                    status_module = protocol_section.get("statusModule", {})
                    
                    trial_data = {
                        "trial_id": identification_module.get("nctId", ""),
                        "title": identification_module.get("briefTitle", ""),
                        "status": status_module.get("overallStatus", ""),
                        "last_updated": status_module.get("lastUpdatePostDate", ""),
                        "source": "clinicaltrials.gov",
                        "url": f"https://clinicaltrials.gov/study/{identification_module.get('nctId', '')}"
                    }
                    
                    all_trials.append(trial_data)
                    
                except Exception as e:
                    print(f"⚠️ Error processing ClinicalTrials.gov study: {e}")
                    continue
            
            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break
                
            page_num += 1
            time.sleep(0.5)
            
        except requests.exceptions.RequestException as e:
            print(f"❌ ClinicalTrials.gov API request failed: {e}")
            break
        except Exception as e:
            print(f"❌ ClinicalTrials.gov unexpected error: {e}")
            break

    print(f"✅ ClinicalTrials.gov - Total trials fetched: {len(all_trials)}")
    return all_trials

def fetch_isrctn():
    """Fetch trials from ISRCTN API"""
    print("📥 Fetching from ISRCTN API...")

    all_trials = []
    base_url = "https://www.isrctn.com/api/query/format/default"
    
    try:
        params = {
            "q": 'condition:"spinal cord injury"',
            "limit": 1000  # Start with large limit, adjust if needed
        }
        
        print("🔄 ISRCTN - Fetching trials...")
        response = requests.get(base_url, params=params, timeout=30)
        print("Request URL:", response.url)
        response.raise_for_status()
        
        # Parse XML response
        root = ET.fromstring(response.content)
        
        # Find all trial elements in the XML
        trials_found = 0
        for trial_elem in root.iter():
            if 'isrctn' in trial_elem.tag.lower() or 'trial' in trial_elem.tag.lower():
                try:
                    # Extract trial data from XML structure
                    trial_id = ""
                    title = ""
                    status = ""
                    last_updated = ""
                    
                    # Look for ISRCTN ID
                    for elem in trial_elem.iter():
                        if 'isrctn' in elem.tag.lower() and elem.text:
                            trial_id = elem.text
                            break
                    
                    # Look for title
                    for elem in trial_elem.iter():
                        if any(word in elem.tag.lower() for word in ['title', 'brief']) and elem.text:
                            title = elem.text
                            break
                    
                    # Look for status
                    for elem in trial_elem.iter():
                        if 'status' in elem.tag.lower() and elem.text:
                            status = elem.text
                            break
                    
                    # Look for date
                    for elem in trial_elem.iter():
                        if any(word in elem.tag.lower() for word in ['date', 'updated', 'edited']) and elem.text:
                            last_updated = elem.text
                            break
                    
                    if trial_id and title:  # Only process if we have essential data
                        trial_data = {
                            "trial_id": trial_id,
                            "title": title,
                            "status": status or "Unknown",
                            "last_updated": last_updated or "",
                            "source": "isrctn",
                            "url": f"https://www.isrctn.com/{trial_id}"
                        }
                        
                        all_trials.append(trial_data)
                        trials_found += 1
                        
                except Exception as e:
                    print(f"⚠️ Error processing ISRCTN trial: {e}")
                    continue
        
        print(f"✅ ISRCTN - Retrieved {trials_found} trials")
        
    except requests.exceptions.RequestException as e:
        print(f"❌ ISRCTN API request failed: {e}")
    except ET.ParseError as e:
        print(f"❌ ISRCTN XML parsing failed: {e}")
    except Exception as e:
        print(f"❌ ISRCTN unexpected error: {e}")

    print(f"✅ ISRCTN - Total trials fetched: {len(all_trials)}")
    return all_trials

def upsert_and_detect_changes(trials):
    """Upsert trials and detect changes across both sources"""
    new_trials = []
    changed_trials = []

    print(f"🔄 Processing {len(trials)} trials for database operations...")

    for i, trial in enumerate(trials):
        if i % 100 == 0:  # Progress update every 100 trials
            print(f"📊 Processed {i}/{len(trials)} trials...")

        try:
            trial_id = trial["trial_id"]
            title = trial["title"]
            status = trial["status"]
            last_updated = trial["last_updated"]
            source = trial["source"]
            url = trial["url"]
            last_checked = datetime.utcnow().isoformat()
            
        except KeyError as e:
            print(f"⚠️ Skipping trial due to missing data: {e}")
            continue

        try:
            # Query existing trial with better error handling
            existing = None
            try:
                result = supabase.table("trials").select("status, source").eq("nct_id", trial_id).maybe_single().execute()
                existing = result.data if result and hasattr(result, 'data') and result.data else None
            except Exception as query_error:
                # Skip the query error logging to reduce noise, just set existing to None
                existing = None

            # Create detailed trial info dictionary
            trial_info = {
                "trial_id": trial_id,
                "title": title,
                "status": status,
                "last_updated": last_updated if last_updated and last_updated.strip() else "Not specified",
                "source": source,
                "url": url
            }

            if not existing:
                new_trials.append(trial_info)
            elif existing.get("status") != status:
                trial_info["old_status"] = existing.get("status", "Unknown")
                changed_trials.append(trial_info)

            # Handle empty date strings - convert to None for database
            processed_last_updated = last_updated if last_updated and last_updated.strip() else None

            # Simplified upsert - just try once and move on if it fails
            try:
                upsert_data = {
                    "nct_id": trial_id,
                    "brief_title": title[:500] if title else "",
                    "status": status[:100] if status else "", 
                    "last_updated": processed_last_updated,
                    "source": source,
                    "url": url,
                    "last_checked": last_checked
                }
                
                supabase.table("trials").upsert(upsert_data).execute()
                
            except Exception as upsert_error:
                # Log error but continue processing - don't let one failure stop everything
                if i < 10:  # Only log first 10 errors to avoid spam
                    print(f"⚠️ Database upsert failed for trial {trial_id}: {str(upsert_error)[:100]}...")
                continue
            
        except Exception as e:
            # Log error but continue processing
            if i < 10:  # Only log first 10 errors to avoid spam
                print(f"⚠️ Processing error for trial {trial_id}: {str(e)[:100]}...")
            continue

    print(f"✅ Completed processing {len(trials)} trials")
    print(f"📊 Found {len(new_trials)} new trials and {len(changed_trials)} changed trials")
    return new_trials, changed_trials

def get_recent_activity():
    """Get trials added or changed in the last 30 days"""
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    thirty_days_ago_iso = thirty_days_ago.isoformat()
    
    try:
        recent_new = (
            supabase.table("trials")
            .select("nct_id, brief_title, status, last_updated, last_checked, source, url")  # Use existing column names
            .gte("last_checked", thirty_days_ago_iso)
            .order("last_checked", desc=True)
            .limit(50)
            .execute()
        ).data or []
        
        recent_trials = []
        for trial in recent_new:
            trial_info = {
                "trial_id": trial["nct_id"],  # Map to standard format for email
                "title": trial["brief_title"],  # Map to standard format for email
                "status": trial["status"],
                "last_updated": trial["last_updated"] or "Not specified",
                "last_checked": trial["last_checked"],
                "source": trial["source"],
                "url": trial["url"]
            }
            recent_trials.append(trial_info)
        
        return recent_trials
        
    except Exception as e:
        print(f"⚠️ Error fetching recent activity: {e}")
        return []

def send_email(new_trials, changed_trials, recent_activity=None):
    """Send detailed email notification with trials from both registries"""
    subject = "🧬 Clinical Trials Update: Spinal Cord Injury Research"
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
                Spinal Cord Injury Research • ClinicalTrials.gov + ISRCTN Registry
            </p>
        </div>
        
        <!-- Content Container -->
        <div style="padding: 30px; background-color: #fafbfc; border: 1px solid #e1e8ed; border-top: none; border-radius: 0 0 8px 8px;">
    """)
    
    # Count trials by source for today's activity
    ct_new = [t for t in new_trials if t['source'] == 'clinicaltrials.gov']
    isrctn_new = [t for t in new_trials if t['source'] == 'isrctn']
    ct_changed = [t for t in changed_trials if t['source'] == 'clinicaltrials.gov']
    isrctn_changed = [t for t in changed_trials if t['source'] == 'isrctn']
    
    # Daily Report Section
    html_parts.append("""
        <div style="margin-bottom: 40px;">
            <h2 style="color: #1e40af; font-size: 22px; margin: 0 0 20px 0; padding-bottom: 10px; border-bottom: 3px solid #059669;">
                📊 Today's Activity Report
            </h2>
    """)
    
    # Registry Summary
    html_parts.append(f"""
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 25px;">
            <div style="background: white; border: 1px solid #e1e8ed; border-radius: 6px; padding: 15px; text-align: center;">
                <h4 style="margin: 0 0 5px 0; color: #1e40af;">ClinicalTrials.gov</h4>
                <p style="margin: 0; color: #64748b; font-size: 14px;">{len(ct_new)} new • {len(ct_changed)} changed</p>
            </div>
            <div style="background: white; border: 1px solid #e1e8ed; border-radius: 6px; padding: 15px; text-align: center;">
                <h4 style="margin: 0 0 5px 0; color: #059669;">ISRCTN Registry</h4>
                <p style="margin: 0; color: #64748b; font-size: 14px;">{len(isrctn_new)} new • {len(isrctn_changed)} changed</p>
            </div>
        </div>
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
            source_color = "#1e40af" if trial['source'] == 'clinicaltrials.gov' else "#059669"
            source_name = "ClinicalTrials.gov" if trial['source'] == 'clinicaltrials.gov' else "ISRCTN"
            
            html_parts.append(f"""
                <div style="background: white; border: 1px solid #e1e8ed; border-left: 4px solid {source_color}; border-radius: 6px; padding: 20px; margin: 15px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.05);">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
                        <h4 style="margin: 0; font-size: 16px; line-height: 1.4; flex: 1;">
                            <a href="{trial['url']}" style="color: #1e40af; text-decoration: none; font-weight: 600;" target="_blank">
                                {trial['trial_id']}: {trial['title']}
                            </a>
                        </h4>
                        <span style="background: {source_color}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; white-space: nowrap; margin-left: 10px;">
                            {source_name}
                        </span>
                    </div>
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
                            → View full details on {source_name}
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
            source_color = "#1e40af" if trial['source'] == 'clinicaltrials.gov' else "#059669"
            source_name = "ClinicalTrials.gov" if trial['source'] == 'clinicaltrials.gov' else "ISRCTN"
            
            html_parts.append(f"""
                <div style="background: white; border: 1px solid #e1e8ed; border-left: 4px solid #dc2626; border-radius: 6px; padding: 20px; margin: 15px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.05);">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
                        <h4 style="margin: 0; font-size: 16px; line-height: 1.4; flex: 1;">
                            <a href="{trial['url']}" style="color: #1e40af; text-decoration: none; font-weight: 600;" target="_blank">
                                {trial['trial_id']}: {trial['title']}
                            </a>
                        </h4>
                        <span style="background: {source_color}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; white-space: nowrap; margin-left: 10px;">
                            {source_name}
                        </span>
                    </div>
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
                            → View full details on {source_name}
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
                <p style="color: #64748b; margin: 0; font-size: 16px;">All spinal cord injury trials remain unchanged across both registries.</p>
            </div>
        """)
    
    html_parts.append("</div>")  # End daily report section
    
    # Recent Activity Section (if provided)
    if recent_activity:
        # Count by source
        ct_recent = [t for t in recent_activity if t['source'] == 'clinicaltrials.gov']
        isrctn_recent = [t for t in recent_activity if t['source'] == 'isrctn']
        
        html_parts.append(f"""
            <div style="border-top: 2px solid #e1e8ed; padding-top: 30px;">
                <h2 style="color: #1e40af; font-size: 22px; margin: 0 0 20px 0; padding-bottom: 10px; border-bottom: 3px solid #059669;">
                    📈 Recent Activity (Last 30 Days)
                </h2>
                <div style="background: #f8fafc; padding: 15px; border-radius: 6px; border-left: 4px solid #1e40af; margin-bottom: 25px;">
                    <p style="color: #64748b; margin: 0; font-style: italic;">
                        Showing {len(recent_activity)} trials added to our monitoring system in the last 30 days 
                        ({len(ct_recent)} from ClinicalTrials.gov, {len(isrctn_recent)} from ISRCTN).
                    </p>
                </div>
                
                <div style="display: grid; gap: 12px;">
        """)
        
        for trial in recent_activity:
            source_color = "#1e40af" if trial['source'] == 'clinicaltrials.gov' else "#059669"
            source_name = "CT.gov" if trial['source'] == 'clinicaltrials.gov' else "ISRCTN"
            
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
                    days_text = f"{days_ago}d ago"
                    days_color = "#64748b"
            except:
                days_text = "Recently"
                days_color = "#64748b"
            
            html_parts.append(f"""
                <div style="background: white; border: 1px solid #e1e8ed; border-radius: 6px; padding: 16px;">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
                        <h5 style="margin: 0; font-size: 14px; font-weight: 600; flex: 1; line-height: 1.3;">
                            <a href="{trial['url']}" style="color: #1e40af; text-decoration: none;" target="_blank">
                                {trial['trial_id']}: {trial['title'][:75]}{'...' if len(trial['title']) > 75 else ''}
                            </a>
                        </h5>
                        <div style="display: flex; gap: 5px; margin-left: 10px;">
                            <span style="background: {source_color}; color: white; padding: 2px 6px; border-radius: 8px; font-size: 10px; font-weight: 600;">
                                {source_name}
                            </span>
                            <span style="background: {days_color}; color: white; padding: 2px 6px; border-radius: 8px; font-size: 10px; font-weight: 600;">
                                {days_text}
                            </span>
                        </div>
                    </div>
                    <div style="color: #64748b; font-size: 12px;">
                        <strong>Status:</strong>
                        <span style="background: #f1f5f9; color: #475569; padding: 1px 6px; border-radius: 4px; margin-left: 3px;">
                            {trial['status']}
                        </span>
                        <span style="margin-left: 15px;"><strong>Updated:</strong> {trial['last_updated']}</span>
                    </div>
                </div>
            """)
        
        html_parts.append("</div></div>")  # End recent activity section
    
    # Enhanced Footer
    total_today = len(new_trials) + len(changed_trials)
    ct_total = len(ct_new) + len(ct_changed)
    isrctn_total = len(isrctn_new) + len(isrctn_changed)
    
    html_parts.append(f"""
            <!-- Footer -->
            <div style="margin-top: 40px; padding: 25px; background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%); border-radius: 8px; border: 1px solid #e1e8ed;">
                <div style="text-align: center; margin-bottom: 20px;">
                    <div style="color: #1e40af; font-size: 18px; font-weight: 600; margin-bottom: 5px;">
                        📊 Comprehensive Report Summary
                    </div>
                    <div style="color: #374151; font-size: 14px;">
                        <strong>{total_today}</strong> changes today ({ct_total} ClinicalTrials.gov, {isrctn_total} ISRCTN) • 
                        <strong>{len(recent_activity) if recent_activity else 0}</strong> recent additions (30 days)
                    </div>
                </div>
                
                <div style="text-align: center; padding-top: 20px; border-top: 1px solid #cbd5e1; color: #64748b; font-size: 12px;">
                    <p style="margin: 0 0 8px 0;">
                        <strong>Unified Clinical Trials Monitoring</strong><br>
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

    # Handle multiple email addresses
    email_list = [email.strip() for email in EMAIL_TO.split(',')]

    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": EMAIL_FROM,
                "to": email_list,
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
    """Main function - fetches from both registries"""
    try:
        print("🚀 Starting unified clinical trials monitoring...")
        
        # Fetch from both sources
        ct_trials = fetch_clinicaltrials_gov()
        isrctn_trials = fetch_isrctn()
        
        # Combine all trials
        all_trials = ct_trials + isrctn_trials
        
        if not all_trials:
            print("⚠️ No trials fetched from either source, skipping email")
            return
            
        print(f"📊 Combined total: {len(all_trials)} trials ({len(ct_trials)} ClinicalTrials.gov, {len(isrctn_trials)} ISRCTN)")
        
        # Process trials and detect changes
        new_trials, changed_trials = upsert_and_detect_changes(all_trials)
        
        # Get recent activity
        recent_activity = get_recent_activity()
        
        print("📨 Sending unified email report...")
        print(f"New trials today: {len(new_trials)} ({len([t for t in new_trials if t['source'] == 'clinicaltrials.gov'])} CT.gov, {len([t for t in new_trials if t['source'] == 'isrctn'])} ISRCTN)")
        print(f"Changed trials today: {len(changed_trials)} ({len([t for t in changed_trials if t['source'] == 'clinicaltrials.gov'])} CT.gov, {len([t for t in changed_trials if t['source'] == 'isrctn'])} ISRCTN)")
        print(f"Recent activity (30 days): {len(recent_activity)}")
        
        send_email(new_trials, changed_trials, recent_activity)
        print("✅ Unified monitoring process completed successfully")
        
    except Exception as e:
        print(f"❌ Main process failed: {e}")
        raise

if __name__ == "__main__":
    main()
