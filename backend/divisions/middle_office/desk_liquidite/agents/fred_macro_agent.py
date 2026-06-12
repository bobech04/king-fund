"""Agent 1 — FRED Macro Liquidity: M2, SOFR, Fed Funds, réserves bancaires."""
import asyncio
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from desk_liquidite.config import FRED_API_KEY, FRED_SERIES


class FREDMacroAgent:
    name = "FRED_Macro"

    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None:
            from fredapi import Fred
            if not FRED_API_KEY:
                raise ValueError("FRED_API_KEY manquant dans .env")
            self._client = Fred(api_key=FRED_API_KEY)
        return self._client

    def _fetch_series(self, series_id: str, periods: int = 12) -> dict[str, Any]:
        fred = self._get_client()
        end = datetime.today()
        start = end - timedelta(days=periods * 31)
        data = fred.get_series(series_id, observation_start=start.strftime("%Y-%m-%d"))
        if data.empty:
            return {"latest": None, "change_pct": None, "trend": "N/A"}
        latest = float(data.iloc[-1])
        prev = float(data.iloc[-2]) if len(data) >= 2 else latest
        change_pct = round((latest - prev) / abs(prev) * 100, 4) if prev != 0 else 0.0
        trend = "up" if change_pct > 0 else ("down" if change_pct < 0 else "flat")
        return {
            "latest": round(latest, 4),
            "date": str(data.index[-1].date()),
            "change_pct": change_pct,
            "trend": trend,
        }

    async def run(self) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        results = {}
        for name, series_id in FRED_SERIES.items():
            try:
                results[name] = await loop.run_in_executor(
                    None, self._fetch_series, series_id
                )
            except Exception as exc:
                results[name] = {"error": str(exc)}

        m2 = results.get("m2_money_supply", {}).get("latest")
        sofr = results.get("sofr", {}).get("latest")
        score = self._compute_score(results)

        return {
            "agent": self.name,
            "timestamp": datetime.utcnow().isoformat(),
            "data": results,
            "liquidity_score": score,
            "summary": f"M2={m2}B$ | SOFR={sofr}% | score={score}/10",
        }

    def _compute_score(self, data: dict) -> float:
        score = 5.0
        sofr = data.get("sofr", {}).get("latest")
        m2_trend = data.get("m2_money_supply", {}).get("trend")
        if sofr is not None:
            if sofr < 3.0:
                score += 1.5
            elif sofr > 5.5:
                score -= 2.0
        if m2_trend == "up":
            score += 1.0
        elif m2_trend == "down":
            score -= 1.0
        return round(max(0.0, min(10.0, score)), 2)
