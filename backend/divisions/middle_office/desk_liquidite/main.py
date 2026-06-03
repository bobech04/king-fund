"""Desk Liquidité — point d'entrée principal. Lance les 8 agents en parallèle."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agents import (
    FREDMacroAgent,
    FREDCreditAgent,
    YahooEquityAgent,
    YahooETFAgent,
    YahooForexAgent,
    CoinGeckoMarketAgent,
    CoinGeckoDeFiAgent,
    BertezEnergyAgent,
    LiquidityAggregatorAgent,
)


async def run_desk() -> dict:
    agents = [
        FREDMacroAgent(),
        FREDCreditAgent(),
        YahooEquityAgent(),
        YahooETFAgent(),
        YahooForexAgent(),
        CoinGeckoMarketAgent(),
        CoinGeckoDeFiAgent(),
        BertezEnergyAgent(),
    ]

    print(f"Lancement de {len(agents)} agents en parallèle...")
    tasks = [agent.run() for agent in agents]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    cleaned = []
    for agent, res in zip(agents, results):
        if isinstance(res, Exception):
            cleaned.append({"agent": agent.name, "error": str(res)})
        else:
            cleaned.append(res)

    aggregator = LiquidityAggregatorAgent()
    final = aggregator.run(cleaned)

    print(final["report"])
    return final


if __name__ == "__main__":
    asyncio.run(run_desk())
