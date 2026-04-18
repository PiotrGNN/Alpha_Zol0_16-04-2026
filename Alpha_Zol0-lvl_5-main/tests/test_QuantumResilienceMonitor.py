from core.QuantumResilienceMonitor import QuantumResilienceMonitor


def test_quantum_resilience_monitor():
    qrm = QuantumResilienceMonitor()
    qrm.update_metric("mod1", 0.95)
    qrm.log_event("mod1", "recovered")
    assert abs(qrm.get_metric("mod1") - 0.95) < 1e-6
    assert qrm.get_event("mod1") == "recovered"
    qrm.update_metric("mod2", 0.5)
    summary = qrm.summary()
    assert summary["mod1"]["metric"] == 0.95
    assert summary["mod2"]["metric"] == 0.5
    assert summary["mod1"]["event"] == "recovered"
