"""desk_liquidite — package Python exportant run_async pour le LiquidityDesk service."""
import asyncio
from typing import Any


async def run_async() -> dict[str, Any]:
    from desk_liquidite.agents import (
        FREDMacroAgent, FREDCreditAgent,
        YahooEquityAgent, YahooETFAgent, YahooForexAgent,
        CoinGeckoMarketAgent, CoinGeckoDeFiAgent,
        BertezEnergyAgent,
    )
    from desk_liquidite.agents.aggregator_agent import LiquidityAggregatorAgent

    agents = [
        FREDMacroAgent(), FREDCreditAgent(),
        YahooEquityAgent(), YahooETFAgent(), YahooForexAgent(),
        CoinGeckoMarketAgent(), CoinGeckoDeFiAgent(),
        BertezEnergyAgent(),
    ]
    raw = await asyncio.gather(*[a.run() for a in agents], return_exceptions=True)
    results = []
    for agent, res in zip(agents, raw):
        results.append({"agent": agent.name, "error": str(res)} if isinstance(res, Exception) else res)

    return LiquidityAggregatorAgent().run(results)
