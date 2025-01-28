import os
from datetime import date, timedelta

import pytest
from streamlit.testing.v1 import AppTest


@pytest.fixture
def api_credentials():
    """Get API credentials from environment variables"""
    required_env_vars = [
        "DBT_CLOUD_ACCOUNT_ID",
        "DBT_CLOUD_SERVICE_TOKEN",
    ]

    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        pytest.skip(
            f"Missing required environment variables: {', '.join(missing_vars)}"
        )

    return {
        "account_id": os.getenv("DBT_CLOUD_ACCOUNT_ID"),
        "service_token": os.getenv("DBT_CLOUD_SERVICE_TOKEN"),
        "host": os.getenv("DBT_CLOUD_HOST", "cloud.getdbt.com"),
    }


def test_billing_api_schema_stability(api_credentials):
    """
    Test that validates the billing API schema hasn't changed.
    This test will:
    1. Make a real API call using the Streamlit testing framework
    2. Validate the response matches expected schema:
       - Contains required fields (date, datetime, value, group_key, group_value)
       - Fields are of correct type
       - group_key is 'project_id' when grouped by project
    """
    # Initialize app and run it first
    at = AppTest.from_file("app.py")

    at.run()

    # Set credentials
    at.sidebar.text_input(key="dbt_cloud_account_id").set_value(
        api_credentials["account_id"]
    )
    at.sidebar.text_input(key="dbt_cloud_service_token").set_value(
        api_credentials["service_token"]
    )
    at.sidebar.text_input(key="dbt_cloud_host").set_value(api_credentials["host"])

    # Initialize app
    at.sidebar.button(key="init_app").click().run()

    # Set test parameters
    at.selectbox[0].set_value("Successful Models Built")
    at.selectbox[1].set_value("Project")

    # Set date range (last 7 days)
    end_date = date.today()
    start_date = end_date - timedelta(days=7)
    at.date_input[0].set_value(start_date)
    at.date_input[1].set_value(end_date)

    # Trigger data fetch
    at.button(key="get_data").click().run()

    # Get the response data
    response_data = at.session_state["last_api_response"]

    # Validate response
    assert response_data is not None, "No API response found in session state"
    assert response_data["status"]["is_success"], f"API call failed: {response_data}"
    assert isinstance(response_data["data"], list), "Data is not a list"
    assert len(response_data["data"]) > 0, "No data returned from API"

    # Get first data point for schema validation
    sample_data = response_data["data"][0]

    # Required fields
    required_fields = {"date", "datetime", "value", "group_key", "group_value"}
    assert all(field in sample_data for field in required_fields), (
        f"Missing required fields. Expected {required_fields}, got {set(sample_data.keys())}"
    )

    # Type validation
    assert isinstance(sample_data["date"], str), "date field is not a string"
    assert isinstance(sample_data["datetime"], str), "datetime field is not a string"
    assert isinstance(sample_data["value"], (int, float)), "value field is not a number"
    assert isinstance(sample_data["group_key"], str), "group_key field is not a string"
    assert isinstance(sample_data["group_value"], str), (
        "group_value field is not a string"
    )

    # Validate date format (should be ISO format with timezone)
    for field in ["date", "datetime"]:
        assert sample_data[field].endswith("+00:00") or sample_data[field].endswith(
            "Z"
        ), f"{field} field does not have timezone information"

    # Validate group_key for project grouping
    assert sample_data["group_key"] == "project_id", (
        f"Expected group_key to be 'project_id', got '{sample_data['group_key']}'"
    )
