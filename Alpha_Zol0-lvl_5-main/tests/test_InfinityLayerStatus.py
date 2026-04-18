from core.InfinityLayerStatus import InfinityLayerStatus


def test_infinity_layer_status():
    ils = InfinityLayerStatus()
    ils.update_status("mod1", "active")
    ils.update_health("mod1", 0.99)
    assert ils.get_status("mod1") == "active"
    assert abs(ils.get_health("mod1") - 0.99) < 1e-6
    ils.update_status("mod2", "inactive")
    ils.update_health("mod2", 0.5)
    summary = ils.summary()
    assert summary["mod1"]["status"] == "active"
    assert summary["mod2"]["health"] == 0.5
