from distributed.DistributedOrchestrator import DistributedOrchestrator


def dummy_node(msg):
    dummy_node.last_msg = msg


def test_distributed_orchestrator():
    do = DistributedOrchestrator()
    do.register_node(dummy_node)
    status = do.orchestrate("ping")
    assert dummy_node.last_msg == "ping"
    assert any("ok" in s for s in status)
