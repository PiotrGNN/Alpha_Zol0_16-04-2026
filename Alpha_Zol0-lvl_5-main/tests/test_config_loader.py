import pytest

from utils.config_loader import (
    _resolve_env_placeholder,
    _substitute_env,
    load_config,
)


def test_load_config_reads_valid_mapping(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "symbol: BTCUSDTM\n"
        "timeframe: 1\n"
        "sl_pct: 0.5\n"
        "tp_pct: 1.0\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config["symbol"] == "BTCUSDTM"
    assert config["timeframe"] == 1
    assert config["sl_pct"] == 0.5
    assert config["tp_pct"] == 1.0


def test_load_config_rejects_missing_file(tmp_path):
    missing_path = tmp_path / "missing.yaml"

    with pytest.raises(FileNotFoundError, match="Config file not found"):
        load_config(missing_path)


def test_load_config_rejects_empty_file(tmp_path):
    config_path = tmp_path / "empty.yaml"
    config_path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="Config file is empty"):
        load_config(config_path)


def test_load_config_rejects_non_mapping_top_level(tmp_path):
    config_path = tmp_path / "invalid.yaml"
    config_path.write_text("- BTCUSDTM\n- ETHUSDTM\n", encoding="utf-8")

    with pytest.raises(TypeError, match="must contain a mapping"):
        load_config(config_path)


def test_load_config_resolves_env_placeholders(monkeypatch, tmp_path):
    config_path = tmp_path / "env.yaml"
    config_path.write_text(
        "api_key: ${ZOL0_TEST_API_KEY}\n"
        "nested:\n"
        "  token: ${ZOL0_TEST_API_KEY}\n"
        "symbols:\n"
        "  - ${ZOL0_TEST_API_KEY}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ZOL0_TEST_API_KEY", "resolved-value")

    config = load_config(config_path)

    assert config["api_key"] == "resolved-value"
    assert config["nested"]["token"] == "resolved-value"
    assert config["symbols"] == ["resolved-value"]


def test_load_config_rejects_missing_env_placeholder(monkeypatch, tmp_path):
    config_path = tmp_path / "missing_env.yaml"
    config_path.write_text("api_key: ${ZOL0_MISSING_ENV}\n", encoding="utf-8")
    monkeypatch.delenv("ZOL0_MISSING_ENV", raising=False)

    with pytest.raises(KeyError, match="Missing required environment variable"):
        load_config(config_path)


def test_resolve_env_placeholder_rejects_empty_placeholder():
    with pytest.raises(ValueError, match="Empty environment variable placeholder"):
        _resolve_env_placeholder("${}")


def test_substitute_env_resolves_nested_tuple_and_list(monkeypatch):
    monkeypatch.setenv("ZOL0_TEST_TOKEN", "resolved-value")

    payload = (
        "${ZOL0_TEST_TOKEN}",
        {"nested": ["${ZOL0_TEST_TOKEN}", {"inner": "${ZOL0_TEST_TOKEN}"}]},
    )

    resolved = _substitute_env(payload)

    assert resolved == (
        "resolved-value",
        {"nested": ["resolved-value", {"inner": "resolved-value"}]},
    )
