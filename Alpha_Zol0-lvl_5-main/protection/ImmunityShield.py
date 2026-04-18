# ImmunityShield.py – wykrywanie anomalii danych i manipulacji feeda
import logging

import numpy as np
from sklearn.ensemble import IsolationForest


class ImmunityShield:
    def retrain_if_needed(self, X_new, cycle, retrain_interval=100):
        if cycle % retrain_interval == 0:
            self.retrain(X_new)
            logging.info(f"ImmunityShield: retrained at cycle {cycle}")

    def __init__(self, contamination=0.05):
        self.model = IsolationForest(contamination=contamination)
        self.trained = False

    def hyperparameter_tune(self, X):
        from sklearn.model_selection import GridSearchCV

        param_grid = {"contamination": [0.01, 0.05, 0.1]}
        grid = GridSearchCV(IsolationForest(), param_grid, cv=3)
        grid.fit(X)
        self.model = grid.best_estimator_
        self.trained = True
        return grid.best_params_

    def retrain(self, X_new):
        self.model.fit(X_new)
        self.trained = True

    def fit(self, data):
        self.model.fit(np.array(data))
        self.trained = True
        logging.info("ImmunityShield: model trained")

    def detect_anomaly(self, sample):
        if not self.trained:
            logging.warning("ImmunityShield: model not trained")
            return False
        pred = self.model.predict([sample])[0]
        logging.info(f"ImmunityShield: anomaly detected={pred == -1}")
        return pred == -1
