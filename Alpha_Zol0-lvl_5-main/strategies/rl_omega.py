"""
RL Omega Strategy for ZoL0: Deep Q-Learning agent for trading,
ready for federated learning.
"""

from typing import Any, Dict, List
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import random
import logging

logger = logging.getLogger(__name__)


# Wrapper strategy class for integration with BotCore and strategy manager
class RLOmegaStrategy:
    def __init__(self, sim_env=None, name="RLOmega", **kwargs):
        self.name = name
        self.agent = RLOmegaAgent(sim_env=sim_env, **kwargs)
        self.last_signal = None

    def analyze(
        self,
        state,
        sentiment_signal=None,
        technical_signal=None,
        extra_signals=None,
        use_sim_env=False,
        **kwargs,
    ):
        result = self.agent.analyze(
            state=state,
            sentiment_signal=sentiment_signal,
            technical_signal=technical_signal,
            extra_signals=extra_signals,
            use_sim_env=use_sim_env,
            **kwargs,
        )
        self.last_signal = result.get("signal")
        return result

    def get_policy(self):
        return self.agent.get_policy()

    def set_policy(self, state_dict):
        self.agent.set_policy(state_dict)

    def get_weights_for_federation(self):
        return self.agent.get_weights_for_federation()

    def federated_update(self, global_state_dict):
        self.agent.federated_update(global_state_dict)

    def add_to_federated_buffer(self, weights):
        self.agent.add_to_federated_buffer(weights)

    def aggregate_federated_weights(self):
        self.agent.aggregate_federated_weights()


class DQN(nn.Module):
    def __init__(self, state_dim, action_dim):
        super().__init__()
        self.fc1 = nn.Linear(state_dim, 64)
        self.fc2 = nn.Linear(64, 64)
        self.fc3 = nn.Linear(64, action_dim)

    def forward(self, x):
        x = torch.relu(self.fc1(x))
        x = torch.relu(self.fc2(x))
        return self.fc3(x)


class RLOmegaAgent:
    def __init__(
        self,
        state_dim=10,
        action_dim=3,
        gamma=0.99,
        lr=1e-3,
        epsilon=1.0,
        epsilon_min=0.05,
        epsilon_decay=0.995,
        memory_size=10000,
        batch_size=64,
        parameters=None,
        sim_env=None,
    ):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.gamma = gamma
        self.lr = lr
        self.epsilon = epsilon
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.memory = []
        self.memory_size = memory_size
        self.batch_size = batch_size
        self.model = DQN(state_dim, action_dim)
        self.optimizer = optim.Adam(self.model.parameters(), lr=lr)
        self.loss_fn = nn.MSELoss()
        self.last_signal = None
        self.parameters = parameters or {}
        self.sim_env = sim_env  # SimulatedTradingEnv instance
        self.federated_buffer = []  # For federated learning aggregation

    def remember(self, state, action, reward, next_state, done):
        if len(self.memory) >= self.memory_size:
            self.memory.pop(0)
        self.memory.append((state, action, reward, next_state, done))

    def act(self, state):
        if np.random.rand() < self.epsilon:
            return random.randrange(self.action_dim)
        state_tensor = torch.FloatTensor(state).unsqueeze(0)
        with torch.no_grad():
            q_values = self.model(state_tensor)
        return int(torch.argmax(q_values).item())

    def replay(self):
        if len(self.memory) < self.batch_size:
            return
        minibatch = random.sample(self.memory, self.batch_size)
        states, actions, rewards, next_states, dones = zip(*minibatch)
        states = torch.FloatTensor(states)
        next_states = torch.FloatTensor(next_states)
        actions = torch.LongTensor(actions).unsqueeze(1)
        rewards = torch.FloatTensor(rewards)
        dones = torch.FloatTensor(dones)
        q_values = self.model(states).gather(1, actions).squeeze()
        next_q = self.model(next_states).max(1)[0].detach()
        target = rewards + self.gamma * next_q * (1 - dones)
        loss = self.loss_fn(q_values, target)
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay

    def analyze(
        self,
        state: List[float],
        sentiment_signal=None,
        technical_signal=None,
        extra_signals=None,
        use_sim_env=False,
        **kwargs,
    ) -> Dict[str, Any]:
        # Hybrid state fusion: concatenate state with all provided signals
        fused_state = list(state)
        if sentiment_signal is not None:
            fused_state.append(sentiment_signal.get("score", 0.0))
        if technical_signal is not None:
            fused_state.append(technical_signal.get("value", 0.0))
        # Add all extra signals (from any strategy)
        if extra_signals is not None:
            for v in extra_signals.values():
                if isinstance(v, (int, float)):
                    fused_state.append(float(v))
                elif isinstance(v, dict) and "value" in v:
                    fused_state.append(float(v["value"]))
                else:
                    try:
                        fused_state.append(float(v))
                    except Exception:
                        fused_state.append(0.0)
        # Pad/truncate to state_dim
        if len(fused_state) < self.state_dim:
            fused_state += [0.0] * (self.state_dim - len(fused_state))
        elif len(fused_state) > self.state_dim:
            fused_state = fused_state[: self.state_dim]
        action = self.act(fused_state)
        signal = {0: "hold", 1: "buy", 2: "sell"}[action]
        self.last_signal = signal
        result = {"signal": signal, "action": action, "epsilon": self.epsilon}
        # If using simulation, step the environment
        if use_sim_env and self.sim_env is not None:
            next_state, reward, done, _ = self.sim_env.step(action)
            self.update(fused_state, action, reward, next_state, done)
            result["sim_reward"] = reward
            result["sim_done"] = done
        return result

    def update(self, state, action, reward, next_state, done):
        self.remember(state, action, reward, next_state, done)
        self.replay()

    def get_policy(self):
        return self.model.state_dict()

    def set_policy(self, state_dict):
        self.model.load_state_dict(state_dict)

    # Federated learning aggregation: collect local weights for aggregation
    def get_weights_for_federation(self):
        return self.model.state_dict()

    def federated_update(self, global_state_dict):
        self.set_policy(global_state_dict)

    def add_to_federated_buffer(self, weights):
        self.federated_buffer.append(weights)

    def aggregate_federated_weights(self):
        # Simple average aggregation (for demonstration)
        if not self.federated_buffer:
            return
        avg_state_dict = {}
        for key in self.federated_buffer[0].keys():
            avg_state_dict[key] = sum([w[key] for w in self.federated_buffer]) / len(
                self.federated_buffer
            )
        self.set_policy(avg_state_dict)
        self.federated_buffer = []
