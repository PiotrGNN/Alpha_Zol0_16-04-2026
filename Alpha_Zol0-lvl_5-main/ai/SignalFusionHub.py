# SignalFusionHub.py – dynamiczna fuzja sygnałów AI
import logging


class SignalFusionHub:
    def __init__(self):
        self.sources = {}
        self.weights = {}

    def add_source(self, name, func, weight=1.0):
        self.sources[name] = func
        self.weights[name] = weight
        logging.info(f"SignalFusionHub: added {name} with weight {weight}")

    def fuse(self, input_data):
        total = 0.0
        weight_sum = sum(self.weights.values())
        for name, func in self.sources.items():
            signal = func(input_data)
            total += signal * self.weights[name]
            logging.info(
                f"SignalFusionHub: {name} signal={signal} "
                f"weight={self.weights[name]}"
            )
        fused = total / weight_sum if weight_sum else 0.0
        logging.info(f"SignalFusionHub: fused signal={fused}")
        return fused

    def set_weight(self, name, weight):
        if name in self.weights:
            self.weights[name] = weight
            logging.info(f"SignalFusionHub: set weight {weight} for {name}")
