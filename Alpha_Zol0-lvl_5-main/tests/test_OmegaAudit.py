from core.OmegaAudit import OmegaAudit


def test_omega_audit():
    audit = OmegaAudit()
    audit.log_decision("agent1", "buy", "success", {"price": 100})
    audit.log_decision("agent2", "sell", "fail", {"price": 90})
    entries = audit.get_entries()
    assert len(entries) == 2
    assert entries[0]["agent"] == "agent1"
    assert entries[1]["result"] == "fail"
    agent1_entries = audit.get_entries("agent1")
    assert len(agent1_entries) == 1
    assert agent1_entries[0]["decision"] == "buy"
    summary = audit.summary()
    assert summary["total"] == 2


def test_omega_audit_summary_empty_state():
    """
    P3-4: OmegaAudit() with no entries must return total=0 and
    agents=[] — not None, not a populated list.
    """
    audit = OmegaAudit()
    summary = audit.summary()
    assert summary["total"] == 0
    assert isinstance(summary["agents"], list)
    assert summary["agents"] == []


def test_omega_audit_get_entries_agent_filter_returns_empty_for_missing_agent():
    """get_entries(agent=<nonexistent>) must return an empty list, not raise."""
    audit = OmegaAudit()
    audit.log_decision("agent1", "buy", "success", {"price": 100})
    result = audit.get_entries("nonexistent_agent")
    assert result == []


def test_omega_audit_summary_lists_only_active_agents():
    """summary()['agents'] must contain exactly the agents that have logged."""
    audit = OmegaAudit()
    audit.log_decision("alpha", "buy", "success", {})
    audit.log_decision("beta", "sell", "success", {})
    audit.log_decision("alpha", "hold", "success", {})
    summary = audit.summary()
    assert summary["total"] == 3
    assert sorted(summary["agents"]) == ["alpha", "beta"]
