import asyncio

from distributed.SwarmSync_distributed import SwarmSyncDistributed


def dummy_agent(msg):

    dummy_agent.last_msg = msg


def test_swarm_sync_distributed():

    ss = SwarmSyncDistributed()
    ss.register_node(dummy_agent)
    ss.register_node(lambda m: None)
    # Use asyncio to run async broadcast and sync
    asyncio.run(ss.broadcast("test_message"))
    assert dummy_agent.last_msg == "test_message"
    asyncio.run(ss.sync())
