# dbt Cloud Usage Dashboard

A Streamlit dashboard for visualizing dbt Cloud usage metrics

## Overview

This application provides visualization and analysis of dbt Cloud usage metrics, including:
- Successful model builds
- Semantic Layer metrics requests
- Model execution frequency across environments

The dashboard allows users to:
- Group data by project, environment, job, or model
- View metrics at different time intervals (hour, day, month)
- Download data as CSV
- Visualize usage patterns through interactive charts

## Requirements

- A service token with the following permissions:
  - Account Admin or Account Viewer permissions for usage metrics
  - Metadata Only permissions (minimum) for model-level data via Discovery API

## API Schema Validation

This repository includes automated schema validation to ensure stability of the dbt Cloud API responses. The validation:

- Runs daily via GitHub Actions
- Validates response structure and data types
- Creates GitHub issues automatically if schema changes are detected

The validation tests check for:
- Required fields (date, datetime, value, group_key, group_value)
- Correct data types for each field
- Proper date formatting with timezone information
- Expected `group_key` values

## Development

### Installation

1. Clone the repository
2. Install dependencies using `uv`:
    ```bash
    uv sync --all-extras
    ```

### Configuration

The application requires the following environment variables for API authentication:

- `DBT_CLOUD_ACCOUNT_ID`: Your dbt Cloud account ID
- `DBT_CLOUD_SERVICE_TOKEN`: Service token with appropriate permissions
- `DBT_CLOUD_HOST` (optional): Your dbt Cloud host (defaults to cloud.getdbt.com)

### Usage

Run the Streamlit application:

```bash
streamlit run app.py
```

### Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

[MIT License](LICENSE)

## Dependencies

Core dependencies:
- pandas >= 2.2.2
- plotly >= 5.23.0
- streamlit ~= 1.37.0
- requests >= 2.32.3

Development dependencies:
- pytest >= 8.3.4

For the complete list of dependencies, see `pyproject.toml`.
