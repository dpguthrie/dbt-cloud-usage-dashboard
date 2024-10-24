# stdlib
import urllib.parse
from datetime import datetime, timedelta

# third party
import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from requests.exceptions import ConnectionError

QUERY = """
query Query($environmentId: BigInt!, $end: Date!, $start: Date!, $limit: Int) {
  performance(environmentId: $environmentId) {
    mostExecutedModels(end: $end, start: $start, limit: $limit) {
      uniqueId
      byJob {
        jobId
        totalExecutions
      }
    }
  }
}
"""


def set_headers():
    st.session_state.headers = {
        "Authorization": f"Bearer {st.session_state.get('dbt_cloud_service_token', None)}"
    }


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
    on_change=set_headers,
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
WINDOW_SIZES = ["hour", "day", "month"]
GROUPS = ["Project", "Environment", "Job", "Model"]
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


# Get URL for Discovery API
def get_disco_url():
    access_url = st.session_state.get("dbt_cloud_host", None)
    if access_url is None:
        return None

    netloc = urllib.parse.urlparse(f"https://{access_url}/").netloc
    netloc_split = netloc.split(".")
    if "us1" in netloc_split or "us2" in netloc_split:
        account_prefix = netloc_split[0]
        the_rest = ".".join(netloc_split[1:])
        host = f"https://{account_prefix}.metadata.{the_rest}"
    else:
        host = f"https://metadata.{netloc}"
    return host + "/beta/graphql"


# Get Models Data
def discovery_api_request():
    @st.cache_data
    def _request(url: str, variables: dict):
        return requests.post(
            url,
            json={"query": QUERY, "variables": variables},
            headers=st.session_state.headers,
        )

    if st.session_state.get("environments_list", None) is None:
        st.error("No environments found for your account!")
        st.stop()

    deployment_environments = [
        e
        for e in st.session_state.environments_list
        if e["deployment_type"] in ["staging", "production"]
    ]
    url = get_disco_url()
    if url is None:
        st.error("A problem with your host was encountered.  Please double-check!")
        st.stop()

    progress_text = "Retrieving environment data..."
    progress_bar = st.progress(0, text=progress_text)
    results = []
    variables = {
        "start": st.session_state.start_date.strftime("%Y-%m-%d"),
        "end": st.session_state.end_date.strftime("%Y-%m-%d"),
        "limit": None,
    }
    for i, environment in enumerate(deployment_environments):
        env_id = environment["environment_id"]
        env_name = environment["environment_name"]
        env_type = environment["deployment_type"]
        full_name = f"Environment: {env_name} ({env_type})"
        variables["environmentId"] = env_id
        response = _request(url, variables)
        if not response.ok:
            st.warning(f"Error retrieving data for {full_name}")
            continue

        try:
            most_executed_models = (
                response.json()
                .get("data", {})
                .get("performance", {})
                .get("mostExecutedModels", [])
            )
        except (AttributeError, KeyError) as e:
            st.warning(f"Error accessing models.  See response:\n {response.json()}")
            continue

        results.extend(most_executed_models)
        percent_complete = (i + 1) / len(deployment_environments)
        progress_bar.progress(percent_complete, text=f"Retrieved data for {full_name}")
    df = pd.DataFrame(results)
    df[["resource", "package", "model_name"]] = df["uniqueId"].str.split(
        ".", n=2, expand=True
    )
    df = df.explode("byJob")
    df["total_executions"] = df["byJob"].apply(lambda x: x["totalExecutions"])
    df["jobId"] = df["byJob"].apply(lambda x: x["jobId"])
    df = df.drop(columns=["byJob"])

    # Merge with user_df to get additional job, environment and project information
    df = df.merge(
        st.session_state.user_df[
            [
                "job_id",
                "job_name",
                "environment_id",
                "environment_name",
                "project_id",
                "project_name",
            ]
        ],
        left_on="jobId",
        right_on="job_id",
        how="left",
    )

    # Drop the redundant job_id column
    df = df.drop(columns=["jobId"])

    # Sort dataframe
    df = df.sort_values(by=["project_name", "total_executions"])
    return df


# Project, Environment, and Job information
def admin_api_request(path: str):
    def is_success(json_response: dict) -> tuple[bool, str]:
        return json_response["status"]["is_success"]

    response_list = []
    url = f"{ADMIN_API_URL}/{path}"
    limit = 100
    params = {"offset": 0, "limit": limit}
    while True:
        json_response = requests.get(
            url, headers=st.session_state.headers, params=params
        ).json()
        success = is_success(json_response)
        if not success:
            st.error(
                f"Application encountered an error making a request: {json_response}"
            )
            st.stop()

        if isinstance(json_response["data"], dict):
            return json_response["data"]

        response_list.extend(json_response["data"])
        params["offset"] += limit
        if (
            "extra" not in json_response
            or params["offset"] > json_response["extra"]["pagination"]["total_count"]
        ):
            break

    return response_list


def initialize_app():
    # Get plan information
    try:
        plan_data = admin_api_request("billing/plans")
    except ConnectionError as e:
        st.error(
            f"An error occurred.  Most likely your host is misconfigured.  Error: {e}"
        )
        st.stop()
    st.session_state.plan_data = plan_data

    # Get all projects
    projects = admin_api_request("projects")
    st.session_state.projects_list = [
        {"project_id": p["id"], "project_name": p["name"]} for p in projects
    ]

    # Get all environments
    environments = admin_api_request("environments")
    st.session_state.environments_list = [
        {
            "environment_id": e["id"],
            "environment_name": e["name"],
            "project_id": e["project_id"],
            "deployment_type": e["deployment_type"],
        }
        for e in environments
    ]
    st.session_state.environment_ids = [
        e["id"]
        for e in environments
        if e["deployment_type"] in ["staging", "production"]
    ]

    # Get all jobs
    jobs = admin_api_request("jobs")
    st.session_state.jobs_list = [
        {
            "job_id": j["id"],
            "job_name": j["name"],
            "environment_id": j["environment_id"],
        }
        for j in jobs
    ]

    # Merge all information together
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
            "deployment_type",
            "project_id",
            "project_name",
        ]
    ]


def get_plan_information():
    current_credits = st.session_state.plan_data["current_credits"]
    if current_credits:
        available = current_credits.get("available_cents", 0) / 100
        total = current_credits.get("total_cents", 0) / 100
        remaining = total - available
    subscription = st.session_state.plan_data["subscription"]
    if subscription:
        plan_id = subscription["plan_id"]
        if plan_id == "enterprise" and total > 0:
            progress_text = f"\${remaining:,.2f} used of \${total:,.0f} commit"
            st.progress(remaining / total, text=progress_text)


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

    json_response = requests.get(
        BILLING_URL, params=params, headers=st.session_state.headers
    ).json()
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


@st.fragment
def create_model_chart(df: pd.DataFrame):
    st.selectbox(
        label="Select Y Grouping",
        options=["Project", "Environment", "Job"],
        key="y_grouping",
    )
    grouping = st.session_state.y_grouping.lower() + "_name"
    fig = px.bar(
        df,
        x=grouping,
        y="total_executions",
        color="total_executions",
        hover_data=["uniqueId", "total_executions"],
        color_continuous_scale="inferno_r",
    )
    st.plotly_chart(fig, use_container_width=True)


st.title("Usage Metrics")

if init_app:
    if st.session_state.dbt_cloud_account_id == "":
        st.sidebar.error("Please enter your dbt Cloud account ID")

    elif st.session_state.dbt_cloud_service_token == "":
        st.sidebar.error("Please enter your dbt Cloud service token")

    elif st.session_state.dbt_cloud_host == "":
        st.sidebar.error("Please enter your dbt Cloud host")

    else:
        initialize_app()

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
    
    **It's important to note that the service token you use needs to either have
    Account Admin or Billing Admin permissions; otherwise this WILL NOT work!.**
    
    """)
    st.warning("Please initialize the app to get started.")
    st.stop()

get_plan_information()

col1, col2, col3, col4, col5 = st.columns([0.35, 0.2, 0.15, 0.15, 0.15])

col1.selectbox(
    label="Billable Metric",
    options=BILLABLE_METRICS,
    key="billable_metric",
)

group_by_options = GROUPS.copy()
if st.session_state.billable_metric == "Semantic Layer Metrics Request":
    group_by_options.remove("Job")
    group_by_options.remove("Model")

col2.selectbox(
    label="Group By",
    options=group_by_options,
    key="group_by",
)
col3.date_input(label="Start Date", value=START_DATE, key="start_date")
if st.session_state.start_date < datetime(2023, 7, 1).date():
    st.error("Start date must be greater than or equal to 2023-07-01")
    st.stop()

col4.date_input(
    label="End Date",
    value=END_DATE,
    key="end_date",
)

window_size_options = WINDOW_SIZES.copy()
if st.session_state.group_by != "Model":
    col5.selectbox(
        label="Grain",
        options=window_size_options,
        key="window_size",
        index=window_size_options.index("day"),
    )

group_key_value = st.session_state.group_by.lower() + "_id"
group_key_name = st.session_state.group_by.lower() + "_name"
# group_values = sorted(list(st.session_state.user_df[group_key_name].unique()))
# col5.multiselect(
#     label="Select Group Values",
#     options=group_values,
#     key="group_values",
# )

if st.session_state.group_by == "Model":
    st.warning(
        "This will most likely not equal the results for other group by options.  "
        "The data you see here will only be for environments you've configured as "
        "either 'staging' or 'production' within dbt Cloud.  Any models run in "
        "environments not configured with those deployment types will not show up "
        "in the results."
    )

get_data = st.button(label="Get Data", key="get_data")

if get_data and st.session_state.group_by != "Model":
    billing_df = get_billing_data(
        st.session_state.billable_metric.replace(" ", "_").lower(),
        st.session_state.start_date,
        st.session_state.end_date,
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
elif get_data and st.session_state.group_by == "Model":
    models_df = discovery_api_request()
    if models_df.empty:
        st.warning("No data available for the selected filters")
        st.stop()

    tab1, tab2 = st.tabs(["Chart", "Data"])
    with tab2:
        st.dataframe(models_df, use_container_width=True)
    with tab1:
        create_model_chart(models_df)
