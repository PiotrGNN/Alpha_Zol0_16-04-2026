import json
import logging
from pathlib import Path


def get_logger(name=None):
    """Zwraca logger o podanej nazwie (domyślnie root)."""
    return logging.getLogger(name)


def setup_logger():
    """Konfiguruje logger zapisujący do logs/bot.log oraz logs/bot_ai.json."""
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        filename="logs/bot.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def log_ai_decision(decision_dict):
    """Loguje decyzję AI jako JSON (trend, sl/tp, ryzyko, explain,
    time_advantage, itp.)."""
    Path("logs").mkdir(exist_ok=True)
    with open("logs/bot_ai.json", "a", encoding="utf-8") as f:
        f.write(json.dumps(decision_dict, ensure_ascii=False) + "\n")
    # Dodatkowo log do standardowego loggera
    logging.info(f"AI_DECISION: {decision_dict}")
