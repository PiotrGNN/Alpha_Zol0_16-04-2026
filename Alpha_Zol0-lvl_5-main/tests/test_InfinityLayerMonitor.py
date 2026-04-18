from core.InfinityLayerMonitor import InfinityLayerMonitor


def test_infinity_layer_monitor():
    ilm = InfinityLayerMonitor()
    ilm.detect_anomaly("mod1", {"type": "error", "msg": "fail"})
    ilm.react("mod1", "restart")
    assert ilm.get_anomaly("mod1")["type"] == "error"
    assert ilm.get_action("mod1") == "restart"
    summary = ilm.summary()
    assert summary["mod1"]["anomaly"]["msg"] == "fail"
    assert summary["mod1"]["action"] == "restart"
