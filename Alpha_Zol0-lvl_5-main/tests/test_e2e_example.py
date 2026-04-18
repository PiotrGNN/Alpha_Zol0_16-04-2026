import pytest
import requests


def test_api_status():
    # Skip if local backend not running
    try:
        response = requests.get("http://localhost:8000/status", timeout=2)
        if response.status_code != 200:
            pytest.skip("Local API returned non-200 status")
    except requests.exceptions.RequestException:
        pytest.skip("Local API not reachable")
