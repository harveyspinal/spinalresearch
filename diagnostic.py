import requests

def run_diagnostic():
    url = "https://clinicaltrials.gov/api/query/study_fields"
    params = {
        "expr": "spinal cord injury",
        "fields": "NCTId,BriefTitle,OverallStatus,LastUpdatePostDate",
        "min_rnk": 1,
        "max_rnk": 2,  # Keep small for fast test
        "fmt": "JSON"
    }

    print("📡 Sending request to ClinicalTrials.gov API...")
    try:
        response = requests.get(url, params=params)
        print(f"Status Code: {response.status_code}")
        print("Final URL:", response.url)
        response.raise_for_status()
        print("✅ Response received:")
        print(response.text[:1000])  # Print only first 1000 characters for readability
    except requests.exceptions.RequestException as e:
        print("❌ Request failed:")
        print(e)

if __name__ == "__main__":
    run_diagnostic()
