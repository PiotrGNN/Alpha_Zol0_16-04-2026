# start_worker.py
# Uruchamia główną pętlę bota jako osobny worker
# (Render.com: background worker)
from core.BotCore import run_bot

if __name__ == "__main__":
    run_bot(simulate=False)
