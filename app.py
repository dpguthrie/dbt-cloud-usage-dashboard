# stdlib
from datetime import datetime, timedelta

# third party
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(
    page_title="Usage Metrics",
    page_icon="🌌",
    layout="wide",
)

st.sidebar.text_input(
    label="Account ID",
    value="",
    key="dbt_cloud_account_id",
)
st.sidebar.text_input(
    label="Service Token",
    value="",
    type="password",
    key="dbt_cloud_service_token",
)
st.sidebar.text_input(
    label="Host",
    value="cloud.getdbt.com",
    key="dbt_cloud_host",
)

init_app = st.sidebar.button(label="Initialize App", key="init_app")

BILLING_URL = f"https://{st.session_state.dbt_cloud_host}/api/private/accounts/{st.session_state.dbt_cloud_account_id}/billing/usage/"
ADMIN_API_URL = f"https://{st.session_state.dbt_cloud_host}/api/v2/accounts/{st.session_state.dbt_cloud_account_id}"
BILLABLE_METRICS = ["Successful Models Built", "Semantic Layer Metrics Request"]
WINDOW_SIZES = ["month", "day", "hour"]
GROUP_KEY_MAP = {
    "Project": "project_id",
    "Environment": "environment_id",
    "Job": "job_id",
}
START_DATE = datetime.now() - timedelta(days=30)
END_DATE = datetime.now()
RELATIVE_DATE_RANGES = {
    "Last 7 days": (7, 0),
    "Last 30 days": (30, 0),
    "Last 60 days": (90, 0),
    "Last 90 days": (90, 0),
    "Last 180 days": (180, 0),
    "Last year": (365, 0),
}


# Project, Environment, and Job information
@st.cache_data
def admin_api_request(path: str, **params):
    url = f"{ADMIN_API_URL}/{path}"
    headers = {"Authorization": f"Bearer {st.session_state.dbt_cloud_service_token}"}
    r = requests.get(url, headers=headers, params=params)
    return r.json()


if init_app:
    # Get all projects
    projects = admin_api_request("projects")["data"]
    st.session_state.projects_list = [
        {"project_id": p["id"], "project_name": p["name"]} for p in projects
    ]

    # Get all environments
    environments = admin_api_request("environments")["data"]
    st.session_state.environments_list = [
        {
            "environment_id": e["id"],
            "environment_name": e["name"],
            "project_id": e["project_id"],
        }
        for e in environments
    ]

    # Get all jobs
    st.session_state.jobs_list = []
    offset = 0
    limit = 100
    while True:
        jobs = admin_api_request("jobs", offset=offset, limit=limit)
        job_list_for_project = [
            {
                "job_id": j["id"],
                "job_name": j["name"],
                "environment_id": j["environment_id"],
            }
            for j in jobs["data"]
        ]
        st.session_state.jobs_list.extend(job_list_for_project)
        offset += limit
        if offset > jobs["extra"]["pagination"]["total_count"]:
            break

    df_projects = pd.DataFrame(st.session_state.projects_list)
    df_environments = pd.DataFrame(st.session_state.environments_list)
    df_jobs = pd.DataFrame(st.session_state.jobs_list)

    merged_df = df_jobs.merge(df_environments, on="environment_id", how="left")
    final_df = merged_df.merge(df_projects, on="project_id", how="left")
    st.session_state.user_df = final_df[
        [
            "job_id",
            "job_name",
            "environment_id",
            "environment_name",
            "project_id",
            "project_name",
        ]
    ]


@st.cache_data
def get_billing_data(
    billable_metric: str,
    start_date: datetime.date,
    end_date: datetime.date,
    window: str,
    group_key_value: str,
    group_key_name: str,
    *,
    group_values: list[str] = None,
):
    df = st.session_state.user_df

    params = {
        "billable_metric_name": billable_metric,
        "start_date": start_date.strftime("%Y-%m-%dT00:00:00.000Z"),
        "end_date": end_date.strftime("%Y-%m-%dT00:00:00.000Z"),
        "window_size": window,
        "group_key": group_key_value,
    }
    if group_values:
        st.session_state.user_df[group_key_name].isin(group_values)
        params["group_values"] = list(
            df[df[group_key_name].isin(group_values)][group_key_value].unique()
        )

    headers = {"Authorization": f"Bearer {st.session_state.dbt_cloud_service_token}"}
    json_response = requests.get(BILLING_URL, params=params, headers=headers).json()
    if not json_response["status"]["is_success"]:
        error = json_response["status"]["developer_message"]
        st.error(f"Error making request: {error}")

    billing_df = pd.DataFrame(json_response["data"])
    if billing_df.empty:
        return billing_df

    id_to_name_mapping = st.session_state.user_df.set_index(group_key_value)[
        group_key_name
    ].to_dict()

    # Convert group_value to int before replacing with name
    billing_df["group_value"] = billing_df["group_value"].astype(int)

    # Add in additional columns depending on grain of request
    if group_key_name == "environment_name":
        billing_df["project_name"] = billing_df["group_value"].map(
            st.session_state.user_df.drop_duplicates("environment_id").set_index(
                "environment_id"
            )["project_name"]
        )

    if group_key_name == "job_name":
        billing_df["environment_name"] = billing_df["group_value"].map(
            st.session_state.user_df.drop_duplicates("job_id").set_index("job_id")[
                "environment_name"
            ]
        )
        billing_df["project_name"] = billing_df["group_value"].map(
            st.session_state.user_df.drop_duplicates("job_id").set_index("job_id")[
                "project_name"
            ]
        )

    # Replace group_value with names
    billing_df["group_value"] = billing_df["group_value"].map(id_to_name_mapping)

    # Update date format
    if window != "hour":
        billing_df["date"] = pd.to_datetime(billing_df["date"]).dt.date

    # Rename group_value to group_key_name
    billing_df.rename(columns={"group_value": group_key_name}, inplace=True)

    return billing_df


def create_billing_chart(df: pd.DataFrame):
    # Create a Plotly bar chart
    group_by = st.session_state.group_by.lower()
    if group_by == "project":
        color_name = "project_name"
    elif group_by == "environment":
        color_name = "Env Name (Project)"
        df[color_name] = df["environment_name"] + " (" + df["project_name"] + ")"
    else:
        color_name = "Job Name (Project | Environment)"
        df[color_name] = (
            df["job_name"]
            + " ("
            + df["project_name"]
            + " | "
            + df["environment_name"]
            + ")"
        )
    fig = px.bar(
        df,
        x="date",
        y="value",
        color=color_name,
        title=st.session_state.billable_metric,
        labels={"date": "Date", "value": "Value", "group_value": "Group"},
    )

    # Display the chart in Streamlit
    st.plotly_chart(fig, use_container_width=True)


st.title("Usage Metrics")

if "user_df" not in st.session_state:
    st.markdown("""
    This app allows you to view usage metrics for your dbt Cloud account, specifically
    the number of successful models built and the number of semantic layer metrics requests.

    Additionally, you can:
    - Group the data by project, environment, or job
    - Retrieve data at different time intervals (day, month, hour)
    - Download the data as a CSV file

    To get started, please enter your dbt Cloud account ID, service token, and (optionally) 
    the dbt Cloud host where your account is located (default is cloud.getdbt.com) in the
    sidebar and click 'Initialize App'.
    """)
    st.warning("Please initialize the app to get started.")
    st.stop()

col1, col2, col3, col4 = st.columns([0.4, 0.2, 0.2, 0.2])
col1.selectbox(
    label="Billable Metric",
    options=BILLABLE_METRICS,
    key="billable_metric",
)
col2.selectbox(
    label="Grain",
    options=WINDOW_SIZES,
    key="window_size",
)
col3.selectbox(
    label="Date Range",
    options=list(RELATIVE_DATE_RANGES.keys()),
    key="date_range",
)
col4.selectbox(
    label="Group By",
    options=list(GROUP_KEY_MAP.keys()),
    key="group_by",
)
group_key_value = st.session_state.group_by.lower() + "_id"
group_key_name = st.session_state.group_by.lower() + "_name"
# group_values = sorted(list(st.session_state.user_df[group_key_name].unique()))
# col5.multiselect(
#     label="Select Group Values",
#     options=group_values,
#     key="group_values",
# )

get_data = st.button(label="Get Data", key="get_data")

if get_data:
    start_delta, end_delta = RELATIVE_DATE_RANGES[st.session_state.date_range]
    start_date = datetime.now() - timedelta(days=start_delta)
    end_date = datetime.now() - timedelta(days=end_delta)
    billing_df = get_billing_data(
        st.session_state.billable_metric.replace(" ", "_").lower(),
        start_date,
        end_date,
        st.session_state.window_size,
        group_key_value,
        group_key_name,
        # group_values=st.session_state.group_values,
    )
    if billing_df.empty:
        st.warning("No data available for the selected filters")
        st.stop()
    tab1, tab2 = st.tabs(["Chart", "Data"])
    with tab2:
        st.dataframe(
            billing_df.drop(columns=["plan_id", "group_key"]), use_container_width=True
        )
    with tab1:
        create_billing_chart(billing_df)
