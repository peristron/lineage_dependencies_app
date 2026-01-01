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
    
    # if password was already correct in this session, return True
    if st.session_state.get("password_correct", False):
        return True

    # show input for password
    st.header("🔒 Login Required")
    password = st.text_input("Enter App Password", type="password")
    
    if st.button("Login"):
        # this checks the "APP_PASSWORD" key in your streamlit secrets
        if password == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("😕 Password incorrect")
    return False

# stop the app execution here if password is not correct
if not check_password():
    st.stop()

# ---------------------------------------------------------
# main application
# ---------------------------------------------------------

# title and CSS
st.title("🛡️ QuickSight Governance & Lineage")
st.markdown("""
<style>
    .metric-card {background-color: #f0f2f6; border-radius: 10px; padding: 20px;}
</style>
""", unsafe_allow_html=True)

# data loading logic
# hybrid approach: check repo first, fall back to upload
default_filename = "qs_snapshot.json"
data = None

with st.sidebar:
    st.header("Data Source")
    
    # check if file exists in the repo (auto-load)
    if os.path.exists(default_filename):
        with open(default_filename, 'r') as f:
            data = json.load(f)
        st.success(f"✅ Auto-loaded data from repository.")
        
    # otherwise, ask for manual upload
    else:
        st.warning(f"File '{default_filename}' not found in repository.")
        uploaded_file = st.file_uploader("Upload 'qs_snapshot.json'", type="json")
        if uploaded_file:
            data = json.load(uploaded_file)
        st.info("💡 Don't have the file? Run the extraction script in AWS CloudShell first.")

# main logic
if data is not None:
    
    # 1 process dashboards into a dataFrame
    df_dash = pd.DataFrame(data['dashboards'])
    
    # 2 process datasets into a dataFrame
    df_data = pd.DataFrame(data['datasets'])

    # helper: dictionary to look up dataset Name by ARN
    arn_to_name = dict(zip(df_data['arn'], df_data['name']))
    
    # 3 calculating dependencies
    # making list of all ARNs that are actually used in dashboards
    all_used_arns = []
    for used_list in df_dash['used_datasets']:
        all_used_arns.extend(used_list)
    
    unique_used_arns = set(all_used_arns)
    
    # identify orphans (datasets that exist but are NOT in the used list)
    orphans = df_data[~df_data['arn'].isin(unique_used_arns)]
    
    # metrics rows
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Dashboards", len(df_dash))
    col2.metric("Total Datasets", len(df_data))
    col3.metric("Orphan Datasets", len(orphans), delta_color="inverse")
    
    st.divider()

    # the tabs
    tab1, tab2, tab3 = st.tabs(["💥 Impact Analysis", "🧹 Cleanup Candidates", "🕸️ Interactive Map"])

    # tab 1: impact analysis
    with tab1:
        st.subheader("Downstream Impact Checker")
        st.write("If I change a dataset, what breaks?")
        
        # dropdown to pick a dataset
        selected_dataset_name = st.selectbox("Select a Dataset to check:", df_data['name'].sort_values())
        
        # get the ARN for the selected name
        selected_arn = df_data[df_data['name'] == selected_dataset_name]['arn'].values[0]
        
        # find which dashboards use this ARN
        # logic: look at every dashboard, check if selected_arn is in its 'used_datasets' list
        affected = df_dash[df_dash['used_datasets'].apply(lambda x: selected_arn in x)]
        
        if not affected.empty:
            st.error(f"⚠️ Warning! Modifying '{selected_dataset_name}' will impact {len(affected)} Dashboard(s):")
            st.dataframe(affected[['name', 'id']], hide_index=True, use_container_width=True)
        else:
            st.success(f"✅ Safe. '{selected_dataset_name}' is not currently used by any Dashboard.")

    # tab 2: clean-up
    with tab2:
        st.subheader("Orphaned Datasets")
        st.write("These datasets are taking up space (and maybe SPICE capacity) but aren't used in any dashboard.")
        
        if not orphans.empty:
            st.dataframe(orphans[['name', 'id']], hide_index=True, use_container_width=True)
            st.download_button(
                "Download List as CSV",
                orphans[['name', 'id']].to_csv(index=False),
                "orphan_datasets.csv",
                "text/csv"
            )
        else:
            st.write("No orphans found! Your environment is clean.")

    # tab 3: visualization
    with tab3:
        st.subheader("Dependency Graph")
        st.caption("Drag nodes to rearrange. Scroll to zoom.")
        
        # using streamlit-agraph to build the nodes and edges
        nodes = []
        edges = []
        
        # adding dashboard nodes (orange)
        for _, row in df_dash.iterrows():
            nodes.append(Node(
                id=row['name'], 
                label=row['name'], 
                size=25, 
                shape="dot",
                color="#FF9900" # orange
            ))
            
            # 2 adding edges (dataset -> dashboard)
            for arn in row['used_datasets']:
                # lookup the dataset name from the ARN
                ds_name = arn_to_name.get(arn, "Unknown Dataset")
                
                # add the dataset node (blue) if not already added logic happens internally in agraph usually, 
                # but let's ensure we add edges carefully
                edges.append(Edge(source=ds_name, target=row['name'], color="#bdc3c7"))

        # 3 add dataset nodes (blue) - only the used ones to keep graph readable
        for arn in unique_used_arns:
            ds_name = arn_to_name.get(arn, "Unknown Dataset")
            nodes.append(Node(
                id=ds_name, 
                label=ds_name, 
                size=15, 
                shape="dot",
                color="#00BFFF" # blue
            ))

        # config for the physics engine
        config = Config(
            width=900, 
            height=600, 
            directed=True, 
            physics=True, 
            hierarchical=False
        )

        return_value = agraph(nodes=nodes, edges=edges, config=config)

else:
    # start screen instruction if no data loaded yet
    st.info("👈 Please verify data source in sidebar.")
