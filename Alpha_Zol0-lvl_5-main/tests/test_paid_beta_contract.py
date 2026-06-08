from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


def test_paid_beta_app_has_no_public_live_endpoint():
    source = (PROJECT_DIR / "paid_beta" / "app.py").read_text(encoding="utf-8")
    assert '"/start-live"' not in source
    assert '"/panic"' not in source


def test_docker_starts_paid_beta_app_without_masking_install_errors():
    dockerfile = (PROJECT_DIR / "Dockerfile.paid-beta").read_text(encoding="utf-8")
    assert "paid_beta.app:app" in dockerfile
    assert "|| true" not in dockerfile


def test_public_register_cannot_assign_admin_role():
    source = (PROJECT_DIR / "paid_beta" / "app.py").read_text(encoding="utf-8")
    register_block = source.split('@auth.post("/register"', 1)[1].split('@auth.post("/login"', 1)[0]
    assert 'role="user"' in register_block
    assert "bootstrap_admin_email" not in register_block
