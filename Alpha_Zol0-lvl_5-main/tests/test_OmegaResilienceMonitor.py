from core.OmegaResilienceMonitor import OmegaResilienceMonitor


def test_omega_resilience_monitor():
    orm = OmegaResilienceMonitor()
    orm.update_metric("mod1", 0.95)
    orm.update_status("mod1", "stable")
    assert abs(orm.get_metric("mod1") - 0.95) < 1e-6
    assert orm.get_status("mod1") == "stable"
    orm.update_metric("mod2", 0.5)
    orm.update_status("mod2", "unstable")
    summary = orm.summary()
    assert summary["mod1"]["metric"] == 0.95
    assert summary["mod2"]["status"] == "unstable"
