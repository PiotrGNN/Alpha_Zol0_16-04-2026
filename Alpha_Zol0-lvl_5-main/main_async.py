from fastapi import FastAPI
import asyncio
from core.DynamicStrategyRouter import DynamicStrategyRouter
from strategies.momentum import MomentumStrategy
from core.PositionManager import PositionManager
from core.BotCoreAsync import BotCoreAsync

app = FastAPI()
position_manager = PositionManager()


@app.on_event("startup")
async def startup_event():
    strategy = MomentumStrategy()
    strategy_router = DynamicStrategyRouter(strategies=[strategy])
    app.state.current_strategy_router = strategy_router
    app.state.bot = BotCoreAsync(
        strategy_router=strategy_router, position_manager=position_manager
    )
    loop = asyncio.get_event_loop()
    loop.create_task(app.state.bot.run_loop())
