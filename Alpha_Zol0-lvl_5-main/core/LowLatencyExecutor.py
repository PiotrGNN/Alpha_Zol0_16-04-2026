# LowLatencyExecutor.py – egzekutor z niskimi opóźnieniami i dynamicznym RTT
import logging
import time

import websocket

logger = logging.getLogger(__name__)


class LowLatencyExecutor:
    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.ws = None
        self.rtt = None
        self.connected = False

    def connect(self):
        self.ws = websocket.WebSocket()
        self.ws.connect(self.ws_url)
        self.connected = True
        logger.info(f"LowLatencyExecutor: connected to {self.ws_url}")

    def measure_rtt(self):
        if not self.connected:
            return None
        start = time.time()
        self.ws.send("ping")
        self.ws.recv()
        self.rtt = time.time() - start
        logger.info(f"LowLatencyExecutor: RTT={self.rtt:.4f}s")
        return self.rtt

    def execute_order(self, order):
        if not self.connected:
            self.connect()
        self.measure_rtt()
        self.ws.send(str(order))
        response = self.ws.recv()
        logging.info(f"LowLatencyExecutor: order sent, response={response}")
        return response

    def close(self):
        if self.ws:
            self.ws.close()
            self.connected = False
            logging.info("LowLatencyExecutor: connection closed")
