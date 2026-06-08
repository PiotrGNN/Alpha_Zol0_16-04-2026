from pathlib import Path


def test_paid_beta_app_has_no_public_live_endpoint():
    source = Path("paid_beta/app.py").read_text(encoding="utf-8")
    assert '"/start-live"' not in source
    assert '"/panic"' not in source


def test_docker_starts_paid_beta_app_without_masking_install_errors():
    dockerfile = Path("Dockerfile.paid-beta").read_text(encoding="utf-8")
    assert "paid_beta.app:app" in dockerfile
    assert "|| true" not in dockerfile
