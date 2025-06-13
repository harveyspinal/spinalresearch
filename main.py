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
                    
                    # More thorough extraction of last update date
                    last_update_date = ""
                    
                    # Try multiple possible field names and locations for the update date
                    if "lastUpdatePostDate" in status_module:
                        date_field = status_module["lastUpdatePostDate"]
                        # Handle both string and dict formats
                        if isinstance(date_field, dict):
                            last_update_date = date_field.get("date", "")
                        else:
                            last_update_date = date_field or ""
                    elif "lastUpdateSubmitDate" in status_module:
                        date_field = status_module["lastUpdateSubmitDate"]
                        if isinstance(date_field, dict):
                            last_update_date = date_field.get("date", "")
                        else:
                            last_update_date = date_field or ""
                    elif "studyFirstPostDate" in status_module:
                        date_field = status_module["studyFirstPostDate"]
                        if isinstance(date_field, dict):
                            last_update_date = date_field.get("date", "")
                        else:
                            last_update_date = date_field or ""
                    elif "resultsFirstPostDate" in status_module:
                        date_field = status_module["resultsFirstPostDate"]
                        if isinstance(date_field, dict):
                            last_update_date = date_field.get("date", "")
                        else:
                            last_update_date = date_field or ""
                    
                    # If still no date, check other sections
                    if not last_update_date:
                        # Check if there are any date fields in the status module
                        for key, value in status_module.items():
                            if "date" in key.lower() and "post" in key.lower() and value:
                                if isinstance(value, dict):
                                    last_update_date = value.get("date", "")
                                else:
                                    last_update_date = value
                                if last_update_date:
                                    break
                    
                    # Debug: Print first few records to see what we're getting
                    if len(all_trials) < 3:
                        print(f"🔍 Debug - Trial {identification_module.get('nctId', 'UNKNOWN')}:")
                        print(f"   Available status_module keys: {list(status_module.keys())}")
                        if "lastUpdatePostDate" in status_module:
                            print(f"   lastUpdatePostDate structure: {status_module['lastUpdatePostDate']}")
                        print(f"   Extracted last_update_date: '{last_update_date}'")
                    
                    trial_data = {
                        "trial_id": identification_module.get("nctId", ""),
                        "title": identification_module.get("briefTitle", ""),
                        "status": status_module.get("overallStatus", ""),
                        "last_updated": str(last_update_date) if last_update_date else "",  # Ensure it's a string
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
        
        # Parse XML response with much more robust logic
        root = ET.fromstring(response.content)
        
        # Find all trial elements in the XML - completely rewritten approach
        trials_found = 0
        
        # Debug: Print raw XML structure for first trial to understand format
        if len(root) > 0:
            print(f"🔍 ISRCTN XML Debug - Root tag: {root.tag}")
            print(f"🔍 ISRCTN XML Debug - Root children: {[child.tag for child in root[:3]]}")
        
        # Look for different possible XML structures more systematically
        for trial_elem in root.iter():
            # Skip if this element doesn't have children (likely not a trial container)
            if len(trial_elem) == 0:
                continue
                
            try:
                # Extract trial data from XML structure
                trial_id = ""
                title = ""
                status = ""
                last_updated = ""
                
                # Method 1: Look specifically for ISRCTN pattern in text content
                def find_isrctn_in_text(text):
                    if not text:
                        return None
                    import re
                    # Look for ISRCTN followed by exactly 8 digits
                    match = re.search(r'ISRCTN(\d{8})', text)
                    if match:
                        return f"ISRCTN{match.group(1)}"
                    # Look for just 8 digits that might be an ISRCTN number
                    elif re.match(r'^\d{8}$', text.strip()):
                        return f"ISRCTN{text.strip()}"
                    return None
                
                # Search through all text content in this element and children
                all_texts = []
                for elem in trial_elem.iter():
                    if elem.text and elem.text.strip():
                        all_texts.append(elem.text.strip())
                
                # Find ISRCTN ID in any of the text content
                for text in all_texts:
                    found_id = find_isrctn_in_text(text)
                    if found_id:
                        trial_id = found_id
                        break
                
                # Find title - look for longer text that's not an ISRCTN
                for text in all_texts:
                    if (len(text) > 20 and 
                        not find_isrctn_in_text(text) and 
                        text not in ['Dr', 'Mr', 'Miss', 'Ms', 'Prof', 'Professor'] and
                        not text.isdigit()):
                        title = text
                        break
                
                # Look for status in XML attributes or specific tags
                for elem in trial_elem.iter():
                    if ('status' in elem.tag.lower() or 
                        'state' in elem.tag.lower()) and elem.text:
                        status = elem.text.strip()
                        break
                
                # Look for dates
                for elem in trial_elem.iter():
                    if elem.text and any(word in elem.tag.lower() for word in ['date', 'updated', 'edited', 'modified']):
                        last_updated = elem.text.strip()
                        break
                
                # Only process if we have both a valid trial ID and title
                if trial_id and title and len(title) > 10:
                    # Debug: Print first few trials to verify parsing
                    if trials_found < 3:
                        print(f"🔍 ISRCTN Debug - Trial {trials_found + 1}:")
                        print(f"   Extracted trial_id: '{trial_id}'")
                        print(f"   Title: '{title[:80]}...'")
                        print(f"   Status: '{status}'")
                    
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
            # Handle both string and dict formats for last_updated
            if isinstance(last_updated, dict):
                processed_last_updated = last_updated.get("date") if last_updated.get("date") and last_updated.get("date").strip() else None
            else:
                processed_last_updated = last_updated if last_updated and str(last_updated).strip() else None

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
    """Get trials with recent research activity (last 30 days) based on when they were actually updated"""
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    thirty_days_ago_iso = thirty_days_ago.isoformat()
    
    try:
        # Get trials that have been updated in the last 30 days
        # Filter out trials with no last_updated date or empty dates
        recent_trials = (
            supabase.table("trials")
            .select("nct_id, brief_title, status, last_updated, last_checked, source, url")
            .gte("last_updated", thirty_days_ago_iso)  # Use actual research activity dates
            .not_.is_("last_updated", "null")  # Exclude trials with null update date
            .order("last_updated", desc=True)  # Order by most recent research activity
            .limit(50)
            .execute()
        ).data or []
        
        # Process and format the trials, with additional filtering for empty strings
        formatted_trials = []
        for trial in recent_trials:
            # Skip trials with empty or invalid last_updated dates
            last_updated_date = trial.get("last_updated")
            if not last_updated_date or last_updated_date.strip() == "" or last_updated_date == "Not specified":
                continue
                
            trial_info = {
                "trial_id": trial["nct_id"],
                "title": trial["brief_title"],
                "status": trial["status"],
                "last_updated": last_updated_date,
                "last_checked": trial["last_checked"],  # Keep for reference but not used for filtering
                "source": trial["source"],
                "url": trial["url"]
            }
            formatted_trials.append(trial_info)
        
        return formatted_trials
        
    except Exception as e:
        print(f"⚠️ Error fetching recent research activity: {e}")
        # Fallback: try without the null filter
        try:
            print("🔄 Trying fallback query without null filter...")
            recent_trials = (
                supabase.table("trials")
                .select("nct_id, brief_title, status, last_updated, last_checked, source, url")
                .gte("last_updated", thirty_days_ago_iso)
                .order("last_updated", desc=True)
                .limit(50)
                .execute()
            ).data or []
            
            # Filter out invalid dates in Python instead
            formatted_trials = []
            for trial in recent_trials:
                last_updated_date = trial.get("last_updated")
                if (last_updated_date and 
                    last_updated_date.strip() != "" and 
                    last_updated_date != "Not specified" and
                    last_updated_date is not None):
                    
                    trial_info = {
                        "trial_id": trial["nct_id"],
                        "title": trial["brief_title"],
                        "status": trial["status"],
                        "last_updated": last_updated_date,
                        "last_checked": trial["last_checked"],
                        "source": trial["source"],
                        "url": trial["url"]
                    }
                    formatted_trials.append(trial_info)
            
            return formatted_trials
            
        except Exception as fallback_error:
            print(f"⚠️ Fallback query also failed: {fallback_error}")
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
                    📈 Recent Research Activity (Last 30 Days)
                </h2>
                <div style="background: #f8fafc; padding: 15px; border-radius: 6px; border-left: 4px solid #1e40af; margin-bottom: 25px;">
                    <p style="color: #64748b; margin: 0; font-style: italic;">
                        Showing {len(recent_activity)} trials with recent research updates in the last 30 days 
                        ({len(ct_recent)} from ClinicalTrials.gov, {len(isrctn_recent)} from ISRCTN).
                        <br><strong>These represent active research developments, not just monitoring activity.</strong>
                    </p>
                </div>
                
                <div style="display: grid; gap: 12px;">
        """)
        
        for trial in recent_activity:
            source_color = "#1e40af" if trial['source'] == 'clinicaltrials.gov' else "#059669"
            source_name = "CT.gov" if trial['source'] == 'clinicaltrials.gov' else "ISRCTN"
            
            # Calculate days ago based on actual research activity
            try:
                if trial['last_updated'] and trial['last_updated'] != "Not specified":
                    # Parse the last_updated date from the research data
                    updated_date = datetime.fromisoformat(trial['last_updated'].replace('Z', '+00:00'))
                    days_ago = (datetime.utcnow().replace(tzinfo=updated_date.tzinfo) - updated_date).days
                    if days_ago == 0:
                        days_text = "Updated today"
                        days_color = "#dc2626"  # Red for very recent
                    elif days_ago == 1:
                        days_text = "Updated yesterday"
                        days_color = "#ea580c"  # Orange for recent
                    elif days_ago <= 7:
                        days_text = f"Updated {days_ago}d ago"
                        days_color = "#059669"  # Green for this week
                    else:
                        days_text = f"Updated {days_ago}d ago"
                        days_color = "#0891b2"  # Blue for this month
                else:
                    days_text = "Recently updated"
                    days_color = "#64748b"
            except:
                days_text = "Recently updated"
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
