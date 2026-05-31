"""Agent 6 — CoinGecko Market: BTC/ETH prix, volume, market cap, dominance."""
import asyncio
from datetime import datetime
from typing import Any

import requests

from desk_liquidite.config import COINGECKO_BASE_URL, COINGECKO_PRO_URL, COINGECKO_API_KEY, COINGECKO_TOP_COINS, coingecko_is_demo_key


class CoinGeckoMarketAgent:
    name = "CoinGecko_Market"

    def _base_url(self) -> str:
        if COINGECKO_API_KEY and not coingecko_is_demo_key():
            return COINGECKO_PRO_URL
        return COINGECKO_BASE_URL

    def _headers(self) -> dict:
        if not COINGECKO_API_KEY:
            return {}
        if coingecko_is_demo_key():
            return {"x-cg-demo-api-key": COINGECKO_API_KEY}
        return {"x-cg-pro-api-key": COINGECKO_API_KEY}

    def _fetch_market_data(self) -> list[dict]:
        url = f"{self._base_url()}/coins/markets"
        params = {
            "vs_currency": "usd",
            "ids": ",".join(COINGECKO_TOP_COINS),
            "order": "market_cap_desc",
            "per_page": 10,
            "page": 1,
            "sparkline": False,
            "price_change_percentage": "1h,24h,7d",
        }
        resp = requests.get(url, params=params, headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _fetch_global_data(self) -> dict:
        url = f"{self._base_url()}/global"
        resp = requests.get(url, headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return resp.json().get("data", {})

    async def run(self) -> dict[str, Any]:
        loop = asyncio.get_event_loop()
        try:
            market_raw, global_data = await asyncio.gather(
                loop.run_in_executor(None, self._fetch_market_data),
                loop.run_in_executor(None, self._fetch_global_data),
            )
        except Exception as exc:
            return {"agent": self.name, "error": str(exc)}

        coins = {}
        for coin in market_raw:
            cid = coin.get("id", "unknown")
            coins[cid] = {
                "price_usd": coin.get("current_price"),
                "market_cap_usd": coin.get("market_cap"),
                "volume_24h_usd": coin.get("total_volume"),
                "change_24h_pct": coin.get("price_change_percentage_24h"),
                "change_7d_pct": coin.get("price_change_percentage_7d_in_currency"),
                "market_cap_rank": coin.get("market_cap_rank"),
            }

        global_metrics = {
            "total_market_cap_usd": global_data.get("total_market_cap", {}).get("usd"),
            "total_volume_24h_usd": global_data.get("total_volume", {}).get("usd"),
            "btc_dominance_pct": round(global_data.get("market_cap_percentage", {}).get("btc", 0), 2),
            "eth_dominance_pct": round(global_data.get("market_cap_percentage", {}).get("eth", 0), 2),
            "active_cryptocurrencies": global_data.get("active_cryptocurrencies"),
        }

        score = self._compute_score(coins, global_metrics)
        btc_price = coins.get("bitcoin", {}).get("price_usd")
        btc_chg = coins.get("bitcoin", {}).get("change_24h_pct")

        return {
            "agent": self.name,
            "timestamp": datetime.utcnow().isoformat(),
            "coins": coins,
            "global": global_metrics,
            "liquidity_score": score,
            "summary": f"BTC={btc_price}$ ({btc_chg:+.2f}%) | dominance={global_metrics['btc_dominance_pct']}% | score={score}/10",
        }

    def _compute_score(self, coins: dict, global_data: dict) -> float:
        score = 5.0
        btc_chg = coins.get("bitcoin", {}).get("change_24h_pct")
        eth_chg = coins.get("ethereum", {}).get("change_24h_pct")
        btc_dom = global_data.get("btc_dominance_pct", 50)

        if btc_chg is not None:
            if btc_chg > 3:
                score += 1.0
            elif btc_chg < -5:
                score -= 2.0
            elif btc_chg < -3:
                score -= 1.0

        if eth_chg is not None and eth_chg < -5:
            score -= 0.5

        if btc_dom > 60:
            score -= 0.5
        elif btc_dom < 40:
            score += 0.5

        return round(max(0.0, min(10.0, score)), 2)
