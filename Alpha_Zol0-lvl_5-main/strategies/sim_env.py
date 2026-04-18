"""Simulated trading environment for RL agent (OpenAI Gym style)."""

import numpy as np


class SimulatedTradingEnv:
    def __init__(self, price_series, initial_balance=1000):
        self.price_series = price_series
        self.initial_balance = initial_balance
        self.reset()

    def reset(self):
        self.current_step = 0
        self.balance = self.initial_balance
        self.position = 0  # 0: flat, 1: long, -1: short
        self.entry_price = 0
        self.done = False
        return self._get_state()

    def _get_state(self):
        # Example state: [price, position, balance]
        price = self.price_series[self.current_step]
        return np.array([price, self.position, self.balance], dtype=np.float32)

    def step(self, action):
        # Actions: 0 = hold, 1 = buy, 2 = sell
        price = self.price_series[self.current_step]
        reward = 0
        if action == 1 and self.position == 0:  # Buy
            self.position = 1
            self.entry_price = price
        elif action == 2 and self.position == 0:  # Sell (short)
            self.position = -1
            self.entry_price = price
        elif action == 0 and self.position != 0:  # Close position
            if self.position == 1:
                reward = price - self.entry_price
            elif self.position == -1:
                reward = self.entry_price - price
            self.balance += reward
            self.position = 0
            self.entry_price = 0
        self.current_step += 1
        if self.current_step >= len(self.price_series) - 1:
            self.done = True
        return self._get_state(), reward, self.done, {}
