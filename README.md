(README for https://lineageanddependencieschecker.streamlit.app/ ; currently deployed)

---

# QuickSight Governance & Lineage Tool: Implementation Guide

## 1. Use Case & Value
This application serves as a "meta-analysis" tool for Amazon QuickSight implementations, specifically designed for complex environments where 140+ source datasets feed into numerous visualizations.

**It solves 3 specific problems:**
1.  **Impact Analysis:** "If I change or delete, say, the `QuizAttempts.csv` dataset, which Dashboards will break?"
2.  **Cleanup (Orphan Detection):** "Which datasets are consuming SPICE capacity but are not actually used in any dashboard?"
3.  **Visualization:** "Show me a visual map of how data flows from Raw Sources -> Datasets -> Dashboards."

**Architecture:**
*   **Method:** Snapshot-based (Air-gapped security).
*   **Security:** Uses existing AWS permissions (Read-Only). No AWS Admin keys are stored in the application.
*   **Platform:** Streamlit Community Cloud (connected to a Private GitHub Repository).

---

## 2. Phase 1: Data Extraction (AWS CloudShell)

**Goal:** Generate a JSON file (`qs_snapshot.json`) containing the metadata of your QuickSight environment.

**Prerequisites:**
*   Access to AWS Console.
*   Permission to view QuickSight.
*   Access to AWS CloudShell (Top right terminal icon `>_` in the console).

### Step A: Determine your AWS Region
1.  Log into Amazon QuickSight in your browser.
2.  Look at the URL in your address bar.
    *   Example: `https://us-east-2.quicksight.aws.amazon.com/...`
3.  Note the region code (e.g., `us-east-1`, `us-east-2`, `ca-central-1`). **This is critical.**

### Step B: The Extraction Script
1.  Open **AWS CloudShell**.
2.  Create the script file: `nano extract.py`
3.  Paste the code below (Update the `region_name` value to match Step A):

```python
import boto3
import json

# --- CONFIGURATION ---
# CRITICAL: Change this to your QuickSight URL region (e.g., 'us-east-2', 'ca-central-1')
TARGET_REGION = 'us-east-1' 
# ---------------------

qs = boto3.client('quicksight', region_name=TARGET_REGION)
sts = boto3.client('sts')
account_id = sts.get_caller_identity()["Account"]

print(f"Connected to AWS Account: {account_id} in Region: {TARGET_REGION}")
print("⏳ Scanning QuickSight... (Wait for 'Found Dashboard' messages)")

data_export = {"dashboards": [], "datasets": []}

# 1. SCAN DASHBOARDS
try:
    paginator = qs.get_paginator('list_dashboards')
    for page in paginator.paginate(AwsAccountId=account_id):
        for d in page['DashboardSummaryList']:
            try:
                # Describe dashboard to get dependencies
                details = qs.describe_dashboard(AwsAccountId=account_id, DashboardId=d['DashboardId'])
                used_arns = details['Dashboard']['Version']['DataSetArns']
                
                data_export["dashboards"].append({
                    "name": d['Name'],
                    "id": d['DashboardId'],
                    "used_datasets": used_arns
                })
                print(f"  -> Found Dashboard: {d['Name']}")
            except Exception as e:
                continue # Skip dashboards without read permission
except Exception as e:
    print(f"Error reading dashboards: {str(e)}")

# 2. SCAN DATASETS
try:
    paginator = qs.get_paginator('list_data_sets')
    for page in paginator.paginate(AwsAccountId=account_id):
        for ds in page['DataSetSummaries']:
            data_export["datasets"].append({
                "name": ds['Name'],
                "arn": ds['Arn'],
                "id": ds['DataSetId']
            })
except Exception as e:
    print(f"Error reading datasets: {str(e)}")

# 3. SAVE FILE
with open('qs_snapshot.json', 'w') as f:
    json.dump(data_export, f, indent=4)

print(f"\n✅ SUCCESS! Scanned {len(data_export['dashboards'])} Dashboards and {len(data_export['datasets'])} Datasets.")
print("👉 Go to Actions -> Download file -> 'qs_snapshot.json'")
```

4.  Save and Exit (`Ctrl+X`, then `Y`, then `Enter`).
5.  Run the script: `python3 extract.py`
6.  **Verify:** Ensure you see text scrolling indicating dashboards were found.
7.  **Download:** Actions -> Download file -> `qs_snapshot.json`.

---

## 3. Phase 2: Deployment (Streamlit & GitHub)

**Goal:** Host the application securely.

### Step A: Repository Setup
1.  Create a **Private** repository on GitHub.
2.  Add the following 3 files to the repo:

**1. `requirements.txt`**
```text
streamlit
pandas
streamlit-agraph
```

**2. `qs_snapshot.json`**
*   Upload the JSON file you downloaded from AWS.
*   *Note:* Ensure the file size is >1KB. If it is 44 Bytes, it is empty (see Troubleshooting).

**3. `app.py` (The Application Code)**
```python
import streamlit as st
import pandas as pd
import json
import os
from streamlit_agraph import agraph, Node, Edge, Config

# page configuration
st.set_page_config(page_title="QuickSight Governance Tool", layout="wide")

# ---------------------------------------------------------
# security configuration
# ---------------------------------------------------------

# security function
def check_password():
    """Returns `True` if the user had the correct password."""
    if st.session_state.get("password_correct", False):
        return True

    st.header("🔒 Login Required")
    password = st.text_input("Enter App Password", type="password")
    
    if st.button("Login"):
        if password == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("😕 Password incorrect")
    return False

if not check_password():
    st.stop()

# ---------------------------------------------------------
# main application
# ---------------------------------------------------------

st.title("🛡️ QuickSight Governance & Lineage")
st.markdown("""
<style>
    .metric-card {background-color: #f0f2f6; border-radius: 10px; padding: 20px;}
</style>
""", unsafe_allow_html=True)

# data loading logic
default_filename = "qs_snapshot.json"
data = None

with st.sidebar:
    st.header("Data Source")
    
    # 1. attempt to auto-load from repository
    if os.path.exists(default_filename):
        try:
            with open(default_filename, 'r') as f:
                data = json.load(f)
            st.success("✅ Auto-loaded data from repository.")
        except Exception as e:
            st.error(f"Error reading repo file: {e}")
            
    # 2. always show uploader (manual override)
    uploaded_file = st.file_uploader("Upload Manual Snapshot", type="json")
    
    if uploaded_file:
        data = json.load(uploaded_file)
        st.info("📂 Using manually uploaded file.")
        
    if data is None:
        st.warning("⚠️ No data found. Please upload a snapshot.")
        st.stop()

# main logic
if data is not None:
    
    df_dash = pd.DataFrame(data.get('dashboards', []))
    df_data = pd.DataFrame(data.get('datasets', []))

    # --- CRITICAL CHECK: IS DATA EMPTY? ---
    if df_data.empty and df_dash.empty:
        st.error("⚠️ The loaded file is empty or missing data.")
        st.warning(f"File analysis: Found {len(df_dash)} dashboards and {len(df_data)} datasets.")
        st.info("Check: Did you run the CloudShell script in the correct AWS Region?")
        st.stop() 

    arn_to_name = dict(zip(df_data['arn'], df_data['name']))
 
    all_used_arns = []
    if 'used_datasets' in df_dash.columns:
        for used_list in df_dash['used_datasets']:
            all_used_arns.extend(used_list)
    
    unique_used_arns = set(all_used_arns)
    orphans = df_data[~df_data['arn'].isin(unique_used_arns)]
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Dashboards", len(df_dash))
    col2.metric("Total Datasets", len(df_data))
    col3.metric("Orphan Datasets", len(orphans), delta_color="inverse")
    
    st.divider()

    tab1, tab2, tab3 = st.tabs(["💥 Impact Analysis", "🧹 Cleanup Candidates", "🕸️ Interactive Map"])

    with tab1:
        st.subheader("Downstream Impact Checker")
        if not df_data.empty:
            selected_dataset_name = st.selectbox("Select a Dataset to check:", df_data['name'].sort_values())
            selected_arn = df_data[df_data['name'] == selected_dataset_name]['arn'].values[0]
            
            if not df_dash.empty and 'used_datasets' in df_dash.columns:
                affected = df_dash[df_dash['used_datasets'].apply(lambda x: selected_arn in x)]
                if not affected.empty:
                    st.error(f"⚠️ Warning! Modifying '{selected_dataset_name}' will impact {len(affected)} Dashboard(s):")
                    st.dataframe(affected[['name', 'id']], hide_index=True, use_container_width=True)
                else:
                    st.success(f"✅ Safe. '{selected_dataset_name}' is not currently used.")

    with tab2:
        st.subheader("Orphaned Datasets")
        if not orphans.empty:
            st.dataframe(orphans[['name', 'id']], hide_index=True, use_container_width=True)
        else:
            st.write("No orphans found!")

    with tab3:
        st.subheader("Dependency Graph")
        nodes = []
        edges = []
        
        for _, row in df_dash.iterrows():
            nodes.append(Node(id=row['name'], label=row['name'], size=25, shape="dot", color="#FF9900"))
            if 'used_datasets' in row:
                for arn in row['used_datasets']:
                    ds_name = arn_to_name.get(arn, "Unknown Dataset")
                    edges.append(Edge(source=ds_name, target=row['name'], color="#bdc3c7"))

        for arn in unique_used_arns:
            ds_name = arn_to_name.get(arn, "Unknown Dataset")
            nodes.append(Node(id=ds_name, label=ds_name, size=15, shape="dot", color="#00BFFF"))

        config = Config(width=900, height=600, directed=True, physics=True, hierarchical=False)
        agraph(nodes=nodes, edges=edges, config=config)
```

### Step B: Connect to Streamlit
1.  Go to [share.streamlit.io](https://share.streamlit.io).
2.  Click **New App**.
3.  Select your Private Repository.
4.  **Important:** Before clicking Deploy, click **Advanced Settings** -> **Secrets**.
5.  Add your password:
    ```toml
    APP_PASSWORD = "YourSecretPassword"
    ```
6.  Click **Deploy**.

---

## 4. Troubleshooting Guide

### Error: "The loaded file is empty or missing data"
*   **Symptom:** The file size is ~44 Bytes. The app shows 0 Dashboards found.
*   **Cause:** The CloudShell script was run in the wrong AWS Region.
*   **Fix:** Check your QuickSight URL. If it says `us-east-2`, update the `region_name='us-east-2'` in the Python script and re-run.

### Error: "KeyError: 'APP_PASSWORD'"
*   **Symptom:** App crashes immediately upon loading.
*   **Cause:** You forgot to set the Secret in the Streamlit Cloud dashboard.
*   **Fix:** Go to Streamlit -> Manage App -> Settings -> Secrets and add the TOML entry.

### Warning: "File 'qs_snapshot.json' not found in repository"
*   **Symptom:** Yellow box in sidebar.
*   **Cause:** You haven't uploaded the JSON file to GitHub yet.
*   **Fix:** The app will still work! Just drag and drop your local JSON file into the "Upload Manual Snapshot" box in the sidebar. To make this permanent, upload the file to GitHub.

---

## 5. Maintenance
This is a **Snapshot** tool, meaning it does not update live, so the JSON file will need to be...renewed regularly/as needed.
*   **Routine:** Once a month (or after major deployments), re-run the CloudShell extraction.
*   **Update:** Drag the new JSON file into the running app for a quick check, or upload it to GitHub to update the "Auto-Load" version for everyone.
