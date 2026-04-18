from distributed.SwarmSync import SwarmSync


def dummy_agent(msg):
    dummy_agent.last_msg = msg


def test_swarm_sync():
    ss = SwarmSync()
    ss.register_agent(dummy_agent)
    ss.broadcast("hello")
    assert dummy_agent.last_msg == "hello"
    assert ss.sync() is True
