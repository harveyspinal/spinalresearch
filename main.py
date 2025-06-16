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

def debug_isrctn_status_fields():
    """Debug function to understand ISRCTN XML status field structure"""
    print("🔍 Debugging ISRCTN status fields...")
    
    try:
        params = {
            "q": 'condition:"spinal cord"',
            "limit": 3  # Just a few for debugging
        }
        
        response = requests.get("https://www.isrctn.com/api/query/format/default", 
                              params=params, timeout=30)
        response.raise_for_status()
        
        root = ET.fromstring(response.content)
        namespace = {'isrctn': 'http://www.67bricks.com/isrctn'}
        
        full_trials = root.findall('.//isrctn:fullTrial', namespace) or \
                     root.findall('.//{http://www.67bricks.com/isrctn}fullTrial')
        
        print(f"📊 Analyzing {len(full_trials)} trials for status fields...")
        
        for i, trial_elem in enumerate(full_trials):
            print(f"\n🔍 Trial {i+1} Status Analysis:")
            
            # Get trial ID first
            trial_id = "Unknown"
            isrctn_fields = trial_elem.findall('.//*')
            for field in isrctn_fields:
                if field.text and field.text.strip():
                    text = field.text.strip()
                    import re
                    match = re.search(r'ISRCTN(\d{8})', text)
                    if match:
                        trial_id = f"ISRCTN{match.group(1)}"
                        break
            
            print(f"   Trial ID: {trial_id}")
            
            # Look for ALL fields containing "status", "recruit", "state", etc.
            status_related_fields = []
            all_field_names = set()
            
            for field in isrctn_fields:
                field_name = field.tag.lower().split('}')[-1]  # Remove namespace
                all_field_names.add(field_name)
                
                # Check if field name suggests it's status-related
                if any(keyword in field_name for keyword in 
                       ['status', 'recruit', 'state', 'phase', 'trial', 'overall', 'current']):
                    if field.text and field.text.strip():
                        status_related_fields.append({
                            'field_name': field_name,
                            'value': field.text.strip()[:100]  # First 100 chars
                        })
            
            print(f"   📋 Status-related fields found:")
            if status_related_fields:
                for field_info in status_related_fields:
                    print(f"      {field_info['field_name']}: '{field_info['value']}'")
            else:
                print(f"      ❌ No obvious status fields found")
            
            # Show sample of all available field names
            sorted_fields = sorted(list(all_field_names))
            print(f"   📝 All available fields ({len(sorted_fields)}): {sorted_fields[:15]}...")
            
    except Exception as e:
        print(f"❌ Debug failed: {e}")

def fetch_isrctn():
    """Fetch trials from ISRCTN API"""
    print("📥 Fetching from ISRCTN API...")

    all_trials = []
    base_url = "https://www.isrctn.com/api/query/format/default"
    
    try:
        params = {
            "q": 'condition:"spinal cord"',  # Broader search to match database
            "limit": 1000  # Start with large limit, adjust if needed
        }
        
        print("🔄 ISRCTN - Fetching trials...")
        response = requests.get(base_url, params=params, timeout=30)
        print("Request URL:", response.url)
        response.raise_for_status()
        
        # Parse XML response with much more robust logic
        root = ET.fromstring(response.content)
        
        # Debug: Print raw XML structure for first trial to understand format
        if len(root) > 0:
            print(f"🔍 ISRCTN XML Debug - Root tag: {root.tag}")
            print(f"🔍 ISRCTN XML Debug - Root children: {[child.tag for child in root[:3]]}")
        
        # Look specifically for fullTrial elements (the main trial containers)
        trials_found = 0
        namespace = {'isrctn': 'http://www.67bricks.com/isrctn'}
        
        # Find all fullTrial elements
        full_trials = root.findall('.//isrctn:fullTrial', namespace) or root.findall('.//{http://www.67bricks.com/isrctn}fullTrial')
        
        print(f"🔍 Found {len(full_trials)} fullTrial elements")
        
        for trial_elem in full_trials:
            try:
                # Extract trial data using more specific field mapping
                trial_id = ""
                title = ""
                status = ""
                last_updated = ""
                
                # Continue with existing field extraction for ID, title, status
                isrctn_fields = trial_elem.findall('.//*') 
                for field in isrctn_fields:
                    if field.text and field.text.strip():
                        text = field.text.strip()
                        # Look for ISRCTN pattern
                        import re
                        match = re.search(r'ISRCTN(\d{8})', text)
                        if match:
                            trial_id = f"ISRCTN{match.group(1)}"
                            break
                        # Look for just 8 digits that might be an ISRCTN number
                        elif re.match(r'^\d{8}$', text):
                            trial_id = f"ISRCTN{text}"
                            break
                
                # Find title - look for title-like fields or longer descriptive text
                for field in isrctn_fields:
                    if field.text and field.text.strip():
                        text = field.text.strip()
                        field_name = field.tag.lower().split('}')[-1]  # Remove namespace
                        
                        # Priority fields for title
                        if any(keyword in field_name for keyword in ['title', 'name', 'brief']):
                            if len(text) > 10 and not re.search(r'ISRCTN\d{8}', text):
                                title = text
                                break
                        # Fallback: longer text that's not an ID or status
                        elif (len(text) > 30 and 
                              not re.search(r'ISRCTN\d{8}', text) and
                              not any(status_word in text.lower() for status_word in ['recruiting', 'completed', 'ongoing', 'stopped', 'suspended']) and
                              not text.startswith('The datasets') and  # Avoid data sharing text
                              not '@' in text):  # Avoid email addresses
                            if not title:  # Only use as fallback
                                title = text
                
                # Find status - Use DOCUMENTED ISRCTN API field names
                status = ""
                
                # DOCUMENTED field names from ISRCTN API (exact case sensitivity)
                documented_status_fields = [
                    'trialStatus',      # Documented: "Ongoing", "Completed", "Stopped", "Suspended", "Enrolling by invitation"
                    'recruitmentStatus', # Documented: "Not yet recruiting", "Recruiting", "No longer recruited", etc.
                    'trialstatus',      # Case variations
                    'recruitmentstatus',
                    'overallstatus',
                    'status'
                ]
                
                # Debug: Look for the documented fields specifically
                if trials_found < 3:
                    print(f"   🔍 Looking for documented ISRCTN status fields...")
                    found_status_fields = []
                    for field in isrctn_fields:
                        field_name_original = field.tag.split('}')[-1]  # Keep original case
                        field_name_lower = field_name_original.lower()
                        
                        if field_name_lower in ['trialstatus', 'recruitmentstatus'] or field_name_original in ['trialStatus', 'recruitmentStatus']:
                            field_value = field.text.strip() if field.text else "EMPTY"
                            found_status_fields.append(f"{field_name_original}: '{field_value}'")
                    
                    if found_status_fields:
                        print(f"   📋 Found documented status fields: {found_status_fields}")
                    else:
                        print(f"   ❌ Documented status fields (trialStatus/recruitmentStatus) NOT FOUND")
                
                # First, try documented field names with exact case matching
                for priority_field in documented_status_fields:
                    for field in isrctn_fields:
                        field_name_original = field.tag.split('}')[-1]  # Keep original case
                        field_name_lower = field_name_original.lower()
                        
                        # Try both exact case and lowercase matching
                        if ((field_name_original == priority_field or field_name_lower == priority_field.lower()) 
                            and field.text and field.text.strip()):
                            status = field.text.strip()
                            if trials_found < 3:
                                print(f"   ✅ Found status in {field_name_original}: '{status}'")
                            break
                    if status:
                        break
                
                # Second, look for any field with documented status values
                if not status:
                    documented_status_values = [
                        # trialStatus values
                        'ongoing', 'completed', 'stopped', 'suspended', 'enrolling by invitation',
                        # recruitmentStatus values  
                        'not yet recruiting', 'recruiting', 'no longer recruited'
                    ]
                    
                    for field in isrctn_fields:
                        if field.text and field.text.strip():
                            text = field.text.strip()
                            field_name = field.tag.lower().split('}')[-1]
                            
                            # SKIP date-like fields (major bug fix!)
                            if (any(date_keyword in field_name for date_keyword in 
                                   ['date', 'start', 'end', 'time']) or
                                'T' in text and 'Z' in text):  # Skip ISO timestamps
                                continue
                            
                            # Check if field contains documented status values
                            if (len(text) < 100 and  # Status should be relatively short
                                any(status_value in text.lower() for status_value in documented_status_values)):
                                status = text
                                if trials_found < 3:
                                    print(f"   ✅ Found documented status value in {field_name}: '{status}'")
                                break
                
                # Third, fallback to any reasonable status-like field (excluding dates)
                if not status:
                    for field in isrctn_fields:
                        if field.text and field.text.strip():
                            text = field.text.strip()
                            field_name = field.tag.lower().split('}')[-1]
                            
                            # SKIP date-like fields and timestamps
                            if (any(date_keyword in field_name for date_keyword in 
                                  ['date', 'start', 'end', 'time', 'created', 'updated']) or
                                ('T' in text and 'Z' in text)):
                                continue
                            
                            # Look for status-like field names
                            if (any(keyword in field_name for keyword in ['status', 'recruit', 'state', 'phase']) and
                                len(text) < 200 and  # Reasonable status length
                                not text.isdigit()):  # Not just a number
                                status = text
                                if trials_found < 3:
                                    print(f"   ⚠️ Fallback status from {field_name}: '{status[:50]}...'")
                                break
                
                # Enhanced debugging when no status found
                if not status and trials_found < 3:
                    print(f"   ❌ NO STATUS FOUND - Enhanced Debug:")
                    
                    # Show all fields that might contain status
                    all_fields_debug = []
                    for field in isrctn_fields:
                        field_name_orig = field.tag.split('}')[-1]
                        field_name_lower = field_name_orig.lower()
                        field_value = field.text.strip()[:50] if field.text else "EMPTY"
                        
                        # Show fields that might be status-related
                        if any(keyword in field_name_lower for keyword in 
                              ['status', 'recruit', 'trial', 'state', 'phase', 'overall']):
                            all_fields_debug.append(f"{field_name_orig}: '{field_value}'")
                    
                    print(f"      📋 All potential status fields: {all_fields_debug}")
                    
                    # Fallback to "Unknown" with a note
                    status = "Unknown - No status fields found"
                
                # Find dates - ENHANCED: Prioritize official lastUpdated attribute
                latest_date = None
                latest_date_text = ""
                
                # PRIORITY 1: Check for lastUpdated XML attribute on <trial> element (OFFICIAL TIMESTAMP)
                trial_element = trial_elem.find('.//{http://www.67bricks.com/isrctn}trial')
                if trial_element is not None and 'lastUpdated' in trial_element.attrib:
                    official_timestamp = trial_element.attrib['lastUpdated']
                    try:
                        # Parse and validate the official timestamp
                        from datetime import datetime
                        date_obj = datetime.fromisoformat(official_timestamp.replace('Z', '+00:00'))
                        iso_date = date_obj.strftime('%Y-%m-%d')
                        
                        # Only use dates that aren't in the future
                        if date_obj <= datetime.now(date_obj.tzinfo):
                            latest_date_text = official_timestamp  # Keep full precision timestamp
                            if trials_found < 3:
                                print(f"   🎯 Using official lastUpdated attribute: '{official_timestamp}'")
                        else:
                            if trials_found < 3:
                                print(f"   ⚠️ Official timestamp is in future, ignoring: '{official_timestamp}'")
                    except Exception as e:
                        if trials_found < 3:
                            print(f"   ⚠️ Failed to parse official timestamp '{official_timestamp}': {e}")
                
                # PRIORITY 2: Only do text parsing if no official timestamp found
                if not latest_date_text:
                    if trials_found < 3:
                        print(f"   🔍 No official timestamp, falling back to text parsing...")
                    
                    for field in isrctn_fields:
                        if field.text and field.text.strip():
                            text = field.text.strip()
                            field_name = field.tag.lower().split('}')[-1]  # Remove namespace
                            
                            # Look for multiple date patterns in text content
                            import re
                            from datetime import datetime
                            
                            # Pattern 1: "as of DD/MM/YYYY" - HIGHEST PRIORITY for text parsing
                            date_match = re.search(r'as of (\d{1,2}/\d{1,2}/\d{4})', text, re.IGNORECASE)
                            if date_match:
                                date_str = date_match.group(1)
                                try:
                                    date_obj = datetime.strptime(date_str, '%d/%m/%Y')
                                    iso_date = date_obj.strftime('%Y-%m-%d')
                                    # Only use dates that aren't in the future
                                    if date_obj <= datetime.now():
                                        if not latest_date or date_obj > latest_date:
                                            latest_date = date_obj
                                            latest_date_text = iso_date
                                            if trials_found < 3:
                                                print(f"   ✅ Found 'as of' date in {field_name}: '{date_str}' → '{iso_date}'")
                                        continue
                                except:
                                    pass
                            
                            # Pattern 2: "as of DD/MM/YY" (2-digit year) - HIGH PRIORITY for text parsing
                            date_match = re.search(r'as of (\d{1,2}/\d{1,2}/\d{2})', text, re.IGNORECASE)
                            if date_match:
                                date_str = date_match.group(1)
                                try:
                                    date_obj = datetime.strptime(date_str, '%d/%m/%y')
                                    iso_date = date_obj.strftime('%Y-%m-%d')
                                    # Only use dates that aren't in the future
                                    if date_obj <= datetime.now():
                                        if not latest_date or date_obj > latest_date:
                                            latest_date = date_obj
                                            latest_date_text = iso_date
                                            if trials_found < 3:
                                                print(f"   ✅ Found 'as of' date (2-digit) in {field_name}: '{date_str}' → '{iso_date}'")
                                        continue
                                except:
                                    pass
                    
                    # If no "as of" dates found in text, look for other dates but exclude future planning dates
                    if not latest_date_text:
                        for field in isrctn_fields:
                            if field.text and field.text.strip():
                                text = field.text.strip()
                                field_name = field.tag.lower().split('}')[-1]
                                
                                # Skip future planning fields
                                if field_name in ['overallenddate', 'intenttopublish', 'plannedenddate', 'expectedenddate']:
                                    continue
                                    
                                # Pattern 3: "YYYY-MM-DD" format in relevant fields
                                date_match = re.search(r'(\d{4}-\d{1,2}-\d{1,2})', text)
                                if date_match:
                                    date_str = date_match.group(1)
                                    try:
                                        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                                        iso_date = date_obj.strftime('%Y-%m-%d')
                                        # Only use dates that aren't in the future
                                        if date_obj <= datetime.now():
                                            if not latest_date or date_obj > latest_date:
                                                latest_date = date_obj
                                                latest_date_text = iso_date
                                                if trials_found < 3:
                                                    print(f"   ✅ Found ISO date in {field_name}: '{date_str}'")
                                            continue
                                    except:
                                        pass
                    
                    # Final fallback to existing logic for overallstartdate
                    if not latest_date_text:
                        for field in isrctn_fields:
                            if field.text and field.text.strip():
                                text = field.text.strip()
                                field_name = field.tag.lower().split('}')[-1]
                                
                                if field_name == 'overallstartdate':
                                    if (re.match(r'\d{4}-\d{2}-\d{2}', text) or 'T' in text):
                                        latest_date_text = text
                                        if trials_found < 3:
                                            print(f"   📅 Final fallback to start date: '{text}'")
                                        break
                
                # Debug: For trials with no dates found, show diagnostic info
                if not latest_date_text and trials_found < 5:
                    print(f"   ⚠️ No date patterns found for trial {trials_found + 1}")
                    # Check if trial element exists but has no lastUpdated attribute
                    if trial_element is not None:
                        available_attrs = list(trial_element.attrib.keys())
                        print(f"     Available trial attributes: {available_attrs}")
                    else:
                        print(f"     No trial element found in XML structure")
                
                # Use the final determined date
                if latest_date_text:
                    last_updated = latest_date_text
                    if trials_found < 3:
                        print(f"   ✅ Final last_updated value: '{last_updated}'")
                else:
                    last_updated = ""
                    if trials_found < 3:
                        print(f"   ❌ No last_updated date found")
                
                # Only process if we have both a valid trial ID and title
                if trial_id and title and len(title) > 10:
                    # Debug: Print first few trials to verify parsing
                    if trials_found < 3:
                        print(f"🔍 ISRCTN Debug - Trial {trials_found + 1}:")
                        print(f"   Extracted trial_id: '{trial_id}'")
                        print(f"   Title: '{title[:80]}...'")
                        print(f"   Status: '{status[:100]}...' ")
                        print(f"   Last Updated: '{last_updated}'")
                        
                        # Debug: Show available field names for first trial
                        field_names = [field.tag.lower().split('}')[-1] for field in isrctn_fields if field.text and field.text.strip()]
                        unique_fields = sorted(list(set(field_names)))
                        print(f"   Available XML fields: {unique_fields[:20]}...")  # Show first 20 field names
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
    """Upsert trials and detect changes across both sources - FIXED for timestamp precision"""
    new_trials = []
    changed_trials = []

    print(f"🔄 Processing {len(trials)} trials for database operations...")

    isrctn_debug_count = 0  # Track ISRCTN trials separately for debugging

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

        # Track ISRCTN trials for debugging
        if source == "isrctn":
            isrctn_debug_count += 1

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

            # Determine change type for tracking
            change_type = "UPDATED"  # Default
            if not existing:
                new_trials.append(trial_info)
                change_type = "NEW"
            elif existing.get("status") != status:
                trial_info["old_status"] = existing.get("status", "Unknown")
                changed_trials.append(trial_info)
                # Store detailed status change info
                old_status = existing.get("status", "Unknown")
                change_type = f"STATUS_CHANGE: {old_status} → {status}"

            # FIXED: Handle timestamp precision for PostgreSQL compatibility
            processed_last_updated = None
            if isinstance(last_updated, dict):
                raw_timestamp = last_updated.get("date") if last_updated.get("date") and last_updated.get("date").strip() else None
            else:
                raw_timestamp = last_updated if last_updated and str(last_updated).strip() else None
            
            # Fix precision issues for PostgreSQL (max 6 decimal places)
            if raw_timestamp:
                try:
                    ts_str = str(raw_timestamp)
                    if '.' in ts_str and ts_str.endswith('Z'):
                        # Split timestamp at decimal point
                        base_ts, frac_and_tz = ts_str.split('.', 1)
                        frac_part = frac_and_tz[:-1]  # Remove 'Z'
                        
                        # Truncate to max 6 decimal places for PostgreSQL
                        if len(frac_part) > 6:
                            frac_part = frac_part[:6]
                            processed_last_updated = f"{base_ts}.{frac_part}Z"
                            # Debug for ISRCTN trials
                            if source == "isrctn" and isrctn_debug_count <= 5:
                                print(f"   🔧 Fixed precision for {trial_id}: '{raw_timestamp}' → '{processed_last_updated}'")
                        else:
                            processed_last_updated = raw_timestamp
                            # Debug for ISRCTN trials - no fix needed
                            if source == "isrctn" and isrctn_debug_count <= 5:
                                print(f"   ✅ No precision fix needed for {trial_id}: '{processed_last_updated}' ({len(frac_part)} digits)")
                    else:
                        processed_last_updated = raw_timestamp
                        if source == "isrctn" and isrctn_debug_count <= 5:
                            print(f"   ✅ No decimals for {trial_id}: '{processed_last_updated}'")
                except Exception as precision_error:
                    # If precision fix fails, try without microseconds
                    try:
                        dt = datetime.fromisoformat(str(raw_timestamp).replace('Z', '+00:00'))
                        processed_last_updated = dt.strftime('%Y-%m-%dT%H:%M:%SZ')
                        if source == "isrctn" and isrctn_debug_count <= 5:
                            print(f"   🔄 Fallback format for {trial_id}: '{processed_last_updated}'")
                    except:
                        processed_last_updated = None
                        if source == "isrctn" and isrctn_debug_count <= 5:
                            print(f"   ❌ Timestamp processing failed for {trial_id}: '{raw_timestamp}'")
            else:
                if source == "isrctn" and isrctn_debug_count <= 5:
                    print(f"   ⚠️ No raw timestamp for {trial_id}")

            # Simplified upsert with better error handling
            try:
                upsert_data = {
                    "nct_id": trial_id,
                    "brief_title": title[:500] if title else "",
                    "status": status[:100] if status else "", 
                    "last_updated": processed_last_updated,  # Use precision-fixed timestamp
                    "source": source,
                    "url": url,
                    "last_checked": last_checked,
                    "change_type": change_type  # Track what kind of change this was
                }
                
                supabase.table("trials").upsert(upsert_data).execute()
                
                # Success debug for ISRCTN
                if source == "isrctn" and isrctn_debug_count <= 5:
                    if processed_last_updated:
                        print(f"   ✅ Successfully stored {trial_id} with timestamp: '{processed_last_updated}'")
                    else:
                        print(f"   ⚠️ Stored {trial_id} with NULL timestamp")
                
            except Exception as upsert_error:
                # Enhanced error logging for timestamp issues
                error_msg = str(upsert_error)
                if source == "isrctn" and ("timestamp" in error_msg.lower() or "date" in error_msg.lower()):
                    print(f"   🚨 Timestamp error for {trial_id}: {error_msg[:150]}...")
                elif i < 10:  # Only log first 10 general errors to avoid spam
                    print(f"⚠️ Database upsert failed for trial {trial_id}: {str(upsert_error)[:100]}...")
                continue
            
        except Exception as e:
            # Log error but continue processing
            if i < 10:  # Only log first 10 errors to avoid spam
                print(f"⚠️ Processing error for trial {trial_id}: {str(e)[:100]}...")
            continue

    print(f"✅ Completed processing {len(trials)} trials")
    print(f"📊 Found {len(new_trials)} new trials and {len(changed_trials)} changed trials")
    
    # Summary for ISRCTN processing
    isrctn_trials = [t for t in trials if t['source'] == 'isrctn']
    if isrctn_trials:
        print(f"🔍 ISRCTN Summary: Processed {len(isrctn_trials)} trials with timestamp debugging")
    
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
            .select("nct_id, brief_title, status, last_updated, last_checked, source, url, change_type")
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
                "url": trial["url"],
                "change_type": trial.get("change_type", "UPDATED")  # Default to UPDATED if missing
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
                .select("nct_id, brief_title, status, last_updated, last_checked, source, url, change_type")
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
                        "url": trial["url"],
                        "change_type": trial.get("change_type", "UPDATED")  # Default to UPDATED if missing
                    }
                    formatted_trials.append(trial_info)
            
            return formatted_trials
            
        except Exception as fallback_error:
            print(f"⚠️ Fallback query also failed: {fallback_error}")
            return []

def send_email(new_trials, changed_trials, recent_activity=None):
    """Send detailed email notification with trials from both registries"""
    
    def smart_truncate(text, max_length=120):
        """Truncate text at word boundary to avoid cutting mid-word"""
        if len(text) <= max_length:
            return text
        # Find last space before max_length
        truncated = text[:max_length].rsplit(' ', 1)[0]
        return truncated + '...'
    
    subject = "🧬 Clinical Trials Update: Spinal Cord Injury Research"
    html_parts = []
    
    # Header with Spinal Research branding - official brand colors
    html_parts.append("""
    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 800px; margin: 0 auto; background-color: #ffffff;">
        <!-- Header Banner -->
        <div style="background-color: #380dbd; padding: 30px 25px; text-align: center; border-radius: 8px 8px 0 0;">
            <!-- Spinal Research Logo -->
            <div style="margin-bottom: 15px;">
                <!-- GitHub-hosted logo with fallback -->
                <img src="https://raw.githubusercontent.com/harveyspinal/spinalresearch/main/assets/spinal-research-logo-white.png" 
                     alt="Spinal Research" 
                     style="height: 35px !important; max-height: 35px; width: auto; max-width: 200px; display: block; margin: 0 auto;"
                     onerror="this.style.display='none'; this.nextElementSibling.style.display='block';" />
                <!-- Fallback branded text if image fails -->
                <div style="display: none; color: white; font-size: 16px; font-weight: bold; text-align: center; line-height: 1.2;">
                    <div style="margin-bottom: 3px;">
                        <span style="color: #84c735;">●</span> 
                        <span style="color: white; letter-spacing: 1px;">spinal</span>
                    </div>
                    <div style="margin-bottom: 3px;">
                        <span style="color: #380dbd;">●</span> 
                        <span style="color: white; letter-spacing: 1px;">research</span>
                    </div>
                    <div style="font-size: 10px; color: #84c735; font-weight: normal;">
                        Curing paralysis together
                    </div>
                </div>
            </div>
            <h1 style="color: white; margin: 0 0 10px 0; font-size: 26px; font-weight: 600;">
                🧬 Clinical Trials Research Update
            </h1>
            <p style="color: #e8f2ff; margin: 0; font-size: 16px; font-weight: 400;">
                Spinal Cord Injury Research Monitoring • ClinicalTrials.gov + ISRCTN Registry
            </p>
            <div style="margin-top: 15px; font-size: 14px; color: #b8d4f0;">
                Together we can cure paralysis
            </div>
        </div>
        
        <!-- Content Container -->
        <div style="padding: 30px; background-color: #f8f8f8; border: 1px solid #dee2e6; border-top: none; border-radius: 0 0 8px 8px;">
    """)
    
    # Count trials by source for today's activity
    ct_new = [t for t in new_trials if t['source'] == 'clinicaltrials.gov']
    isrctn_new = [t for t in new_trials if t['source'] == 'isrctn']
    ct_changed = [t for t in changed_trials if t['source'] == 'clinicaltrials.gov']
    isrctn_changed = [t for t in changed_trials if t['source'] == 'isrctn']
    
    # Daily Report Section with official brand colors
    html_parts.append("""
        <div style="margin-bottom: 40px;">
            <h2 style="color: #380dbd; font-size: 22px; margin: 0 0 20px 0; padding-bottom: 10px; border-bottom: 3px solid #84c735;">
                📊 Today's Activity Report
            </h2>
    """)
    
    # Registry Summary with official brand colors
    html_parts.append(f"""
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 25px;">
            <div style="background: white; border: 1px solid #dee2e6; border-radius: 6px; padding: 15px; text-align: center;">
                <h4 style="margin: 0 0 5px 0; color: #380dbd;">ClinicalTrials.gov</h4>
                <p style="margin: 0; color: #6c757d; font-size: 14px;">{len(ct_new)} new • {len(ct_changed)} changed</p>
            </div>
            <div style="background: white; border: 1px solid #dee2e6; border-radius: 6px; padding: 15px; text-align: center;">
                <h4 style="margin: 0 0 5px 0; color: #84c735;">ISRCTN Registry</h4>
                <p style="margin: 0; color: #6c757d; font-size: 14px;">{len(isrctn_new)} new • {len(isrctn_changed)} changed</p>
            </div>
        </div>
    """)
    
    if new_trials:
        html_parts.append(f"""
            <div style="margin-bottom: 30px;">
                <h3 style="color: #84c735; font-size: 18px; margin: 0 0 15px 0; display: flex; align-items: center;">
                    <span style="background-color: #d4edda; color: #155724; padding: 4px 12px; border-radius: 20px; font-size: 14px; font-weight: 600; margin-right: 10px;">
                        {len(new_trials)}
                    </span>
                    🆕 New Trials Discovered
                </h3>
        """)
        
        for trial in new_trials:
            source_color = "#380dbd" if trial['source'] == 'clinicaltrials.gov' else "#84c735"
            source_name = "ClinicalTrials.gov" if trial['source'] == 'clinicaltrials.gov' else "ISRCTN"
            
            html_parts.append(f"""
                <div style="background: white; border: 1px solid #dee2e6; border-left: 4px solid {source_color}; border-radius: 6px; padding: 20px; margin: 15px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
                        <h4 style="margin: 0; font-size: 16px; line-height: 1.4; flex: 1;">
                            <a href="{trial['url']}" style="color: #380dbd; text-decoration: none; font-weight: 600;" target="_blank">
                                {trial['trial_id']}: {trial['title']}
                            </a>
                        </h4>
                        <span style="background: {source_color}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; white-space: nowrap; margin-left: 10px;">
                            {source_name}
                        </span>
                    </div>
                    <div style="display: flex; flex-wrap: wrap; gap: 15px; align-items: center; color: #6c757d; font-size: 14px;">
                        <div>
                            <strong style="color: #495057;">Status:</strong>
                            <span style="background: #d4edda; color: #155724; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600; margin-left: 5px;">
                                {trial['status']}
                            </span>
                        </div>
                        <div>
                            <strong style="color: #495057;">Last Updated:</strong> {trial['last_updated']}
                        </div>
                    </div>
                    <div style="margin-top: 12px;">
                        <a href="{trial['url']}" style="color: #380dbd; text-decoration: none; font-size: 13px; font-weight: 500;" target="_blank">
                            → View full details on {source_name}
                        </a>
                    </div>
                </div>
            """)
        
        html_parts.append("</div>")
    
    if changed_trials:
        html_parts.append(f"""
            <div style="margin-bottom: 30px;">
                <h3 style="color: #fd7e14; font-size: 18px; margin: 0 0 15px 0; display: flex; align-items: center;">
                    <span style="background-color: #fff3cd; color: #856404; padding: 4px 12px; border-radius: 20px; font-size: 14px; font-weight: 600; margin-right: 10px;">
                        {len(changed_trials)}
                    </span>
                    🔄 Status Changes Detected
                </h3>
        """)
        
        for trial in changed_trials:
            source_color = "#380dbd" if trial['source'] == 'clinicaltrials.gov' else "#84c735"
            source_name = "ClinicalTrials.gov" if trial['source'] == 'clinicaltrials.gov' else "ISRCTN"
            
            html_parts.append(f"""
                <div style="background: white; border: 1px solid #dee2e6; border-left: 4px solid #fd7e14; border-radius: 6px; padding: 20px; margin: 15px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
                        <h4 style="margin: 0; font-size: 16px; line-height: 1.4; flex: 1;">
                            <a href="{trial['url']}" style="color: #380dbd; text-decoration: none; font-weight: 600;" target="_blank">
                                {trial['trial_id']}: {trial['title']}
                            </a>
                        </h4>
                        <span style="background: {source_color}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; white-space: nowrap; margin-left: 10px;">
                            {source_name}
                        </span>
                    </div>
                    <div style="margin-bottom: 10px;">
                        <strong style="color: #495057;">Status Change:</strong>
                        <div style="margin-top: 8px; display: flex; align-items: center; gap: 10px;">
                            <span style="background: #f8d7da; color: #721c24; padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; text-decoration: line-through;">
                                {trial['old_status']}
                            </span>
                            <span style="color: #6c757d; font-weight: bold;">→</span>
                            <span style="background: #d4edda; color: #155724; padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 600;">
                                {trial['status']}
                            </span>
                        </div>
                    </div>
                    <div style="color: #6c757d; font-size: 14px; margin-bottom: 12px;">
                        <strong style="color: #495057;">Last Updated:</strong> {trial['last_updated']}
                    </div>
                    <div>
                        <a href="{trial['url']}" style="color: #380dbd; text-decoration: none; font-size: 13px; font-weight: 500;" target="_blank">
                            → View full details on {source_name}
                        </a>
                    </div>
                </div>
            """)
        
        html_parts.append("</div>")
    
    if not new_trials and not changed_trials:
        html_parts.append("""
            <div style="text-align: center; padding: 40px; background: white; border-radius: 8px; border: 1px solid #dee2e6;">
                <div style="font-size: 48px; margin-bottom: 15px;">✅</div>
                <h3 style="color: #84c735; margin: 0 0 10px 0; font-size: 20px;">No Changes Today</h3>
                <p style="color: #6c757d; margin: 0; font-size: 16px;">All spinal cord injury trials remain unchanged across both registries.</p>
            </div>
        """)
    
    html_parts.append("</div>")  # End daily report section
    
    # Recent Activity Section (if provided)
    if recent_activity:
        # Count by source
        ct_recent = [t for t in recent_activity if t['source'] == 'clinicaltrials.gov']
        isrctn_recent = [t for t in recent_activity if t['source'] == 'isrctn']
        
        html_parts.append(f"""
            <div style="border-top: 2px solid #dee2e6; padding-top: 30px;">
                <h2 style="color: #380dbd; font-size: 22px; margin: 0 0 20px 0; padding-bottom: 10px; border-bottom: 3px solid #84c735;">
                    📈 Recent Research Activity (Last 30 Days)
                </h2>
                <div style="background: #f8f8f8; padding: 15px; border-radius: 6px; border-left: 4px solid #380dbd; margin-bottom: 25px;">
                    <p style="color: #6c757d; margin: 0; font-style: italic;">
                        Showing {len(recent_activity)} trials with recent research updates in the last 30 days 
                        ({len(ct_recent)} from ClinicalTrials.gov, {len(isrctn_recent)} from ISRCTN).
                        <br><strong>These represent active research developments, not just monitoring activity.</strong>
                    </p>
                </div>
                
                <div style="display: grid; gap: 12px;">
        """)
        
        for trial in recent_activity:
            source_color = "#380dbd" if trial['source'] == 'clinicaltrials.gov' else "#84c735"
            source_name = "CT.gov" if trial['source'] == 'clinicaltrials.gov' else "ISRCTN"
            
            # Parse detailed change type information
            change_type_raw = trial.get('change_type', 'UPDATED')
            
            if change_type_raw == 'NEW':
                change_emoji = "🆕"
                change_color = "#84c735"  # Hopeful Green for new
                change_text = "NEW TRIAL"
                change_detail = ""
            elif change_type_raw.startswith('STATUS_CHANGE:'):
                change_emoji = "🔄"
                change_color = "#fd7e14"  # Orange for status change
                # Extract the status change details
                status_change = change_type_raw.replace('STATUS_CHANGE: ', '')
                change_text = "STATUS"
                change_detail = status_change  # e.g., "Recruiting → Completed"
            else:  # UPDATED or any other type
                change_emoji = "📝"
                change_color = "#17a2b8"  # Blue for general updates
                change_text = "UPDATED"
                change_detail = ""
            
            # Calculate days ago based on actual research activity
            try:
                if trial['last_updated'] and trial['last_updated'] != "Not specified":
                    # Parse the last_updated date from the research data
                    updated_date = datetime.fromisoformat(trial['last_updated'].replace('Z', '+00:00'))
                    days_ago = (datetime.utcnow().replace(tzinfo=updated_date.tzinfo) - updated_date).days
                    if days_ago == 0:
                        days_text = "Updated today"
                        days_color = "#dc3545"  # Red for very recent
                    elif days_ago == 1:
                        days_text = "Updated yesterday"
                        days_color = "#fd7e14"  # Orange for recent
                    elif days_ago <= 7:
                        days_text = f"Updated {days_ago}d ago"
                        days_color = "#28a745"  # Green for this week
                    else:
                        days_text = f"Updated {days_ago}d ago"
                        days_color = "#17a2b8"  # Blue for this month
                else:
                    days_text = "Recently updated"
                    days_color = "#6c757d"
            except:
                days_text = "Recently updated"
                days_color = "#6c757d"
            
            html_parts.append(f"""
                <div style="background: white; border: 1px solid #dee2e6; border-radius: 6px; padding: 16px;">
                    <!-- Mobile-friendly layout: title gets full width, tags stack below -->
                    <div style="margin-bottom: 12px;">
                        <h5 style="margin: 0 0 8px 0; font-size: 14px; font-weight: 600; line-height: 1.3; width: 100%;">
                            <a href="{trial['url']}" style="color: #380dbd; text-decoration: none;" target="_blank">
                                {trial['trial_id']}: {smart_truncate(trial['title'])}
                            </a>
                        </h5>
                        <!-- Tags section - stacks nicely on mobile -->
                        <div style="display: flex; gap: 5px; flex-wrap: wrap; align-items: center;">
                            <span style="background: {change_color}; color: white; padding: 2px 6px; border-radius: 8px; font-size: 10px; font-weight: 600;">
                                {change_emoji} {change_text}
                            </span>
                            <span style="background: {source_color}; color: white; padding: 2px 6px; border-radius: 8px; font-size: 10px; font-weight: 600;">
                                {source_name}
                            </span>
                            <span style="background: {days_color}; color: white; padding: 2px 6px; border-radius: 8px; font-size: 10px; font-weight: 600;">
                                {days_text}
                            </span>
                        </div>
                    </div>
                    {"<div style='margin-bottom: 8px; font-size: 12px; color: #fd7e14; font-weight: 600;'>" + change_detail + "</div>" if change_detail else ""}
                    <div style="color: #6c757d; font-size: 12px;">
                        <strong>Status:</strong>
                        <span style="background: #f8f8f8; color: #495057; padding: 1px 6px; border-radius: 4px; margin-left: 3px;">
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
            <div style="margin-top: 40px; padding: 25px; background: #f8f8f8; border-radius: 8px; border: 1px solid #dee2e6;">
                <div style="text-align: center; margin-bottom: 20px;">
                    <div style="color: #380dbd; font-size: 18px; font-weight: 600; margin-bottom: 5px;">
                        📊 Comprehensive Report Summary
                    </div>
                    <div style="color: #495057; font-size: 14px;">
                        <strong>{total_today}</strong> changes today ({ct_total} ClinicalTrials.gov, {isrctn_total} ISRCTN) • 
                        <strong>{len(recent_activity) if recent_activity else 0}</strong> recent additions (30 days)
                    </div>
                </div>
                
                <div style="text-align: center; padding-top: 20px; border-top: 1px solid #dee2e6; color: #6c757d; font-size: 12px;">
                    <p style="margin: 0 0 8px 0;">
                        <strong>Clinical Trials Monitoring by Spinal Research</strong><br>
                        Generated on {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}
                    </p>
                    <p style="margin: 0; color: #84c735; font-weight: 600;">
                        Together we can cure paralysis
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
