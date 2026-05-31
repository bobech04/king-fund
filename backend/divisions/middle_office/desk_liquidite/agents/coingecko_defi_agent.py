"""Agent 7 — CoinGecko DeFi: TVL, volumes DEX, protocoles DeFi majeurs."""
import asyncio
from datetime import datetime
from typing import Any

import requests

from desk_liquidite.config import COINGECKO_BASE_URL, COINGECKO_PRO_URL, COINGECKO_API_KEY, COINGECKO_DEFI, coingecko_is_demo_key


class CoinGeckoDeFiAgent:
    name = "CoinGecko_DeFi"

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

    def _fetch_defi_tokens(self) -> list[dict]:
        url = f"{self._base_url()}/coins/markets"
        params = {
            "vs_currency": "usd",
            "ids": ",".join(COINGECKO_DEFI),
            "order": "market_cap_desc",
            "per_page": 10,
            "page": 1,
            "sparkline": False,
            "price_change_percentage": "24h,7d",
        }
        resp = requests.get(url, params=params, headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _fetch_defi_global(self) -> dict:
        url = f"{self._base_url()}/global/decentralized_finance_defi"
        resp = requests.get(url, headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return resp.json().get("data", {})

    async def run(self) -> dict[str, Any]:
        loop = asyncio.get_event_loop()
        try:
            tokens_raw, defi_global = await asyncio.gather(
                loop.run_in_executor(None, self._fetch_defi_tokens),
                loop.run_in_executor(None, self._fetch_defi_global),
            )
        except Exception as exc:
            return {"agent": self.name, "error": str(exc)}

        tokens = {}
        for coin in tokens_raw:
            cid = coin.get("id", "unknown")
            tokens[cid] = {
                "price_usd": coin.get("current_price"),
                "market_cap_usd": coin.get("market_cap"),
                "volume_24h_usd": coin.get("total_volume"),
                "change_24h_pct": coin.get("price_change_percentage_24h"),
                "change_7d_pct": coin.get("price_change_percentage_7d_in_currency"),
            }

        global_defi = {
            "defi_market_cap_usd": self._to_float(defi_global.get("defi_market_cap")),
            "eth_market_cap_usd": self._to_float(defi_global.get("eth_market_cap")),
            "defi_to_eth_ratio": self._to_float(defi_global.get("defi_to_eth_ratio")),
            "trading_volume_24h_usd": self._to_float(defi_global.get("trading_volume_24h")),
            "top_coin_name": defi_global.get("top_coin_name"),
            "top_coin_defi_dominance": self._to_float(defi_global.get("top_coin_defi_dominance")),
        }

        score = self._compute_score(tokens, global_defi)
        defi_vol = global_defi.get("trading_volume_24h_usd")
        uni_chg = tokens.get("uniswap", {}).get("change_24h_pct")

        return {
            "agent": self.name,
            "timestamp": datetime.utcnow().isoformat(),
            "tokens": tokens,
            "global_defi": global_defi,
            "liquidity_score": score,
            "summary": (
                f"DeFi_vol_24h={defi_vol:.0f}$ | "
                f"UNI_24h={uni_chg:+.2f}% | score={score}/10"
                if defi_vol and uni_chg else f"DeFi data | score={score}/10"
            ),
        }

    @staticmethod
    def _to_float(val) -> float | None:
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    def _compute_score(self, tokens: dict, global_defi: dict) -> float:
        score = 5.0
        vol = global_defi.get("trading_volume_24h_usd")
        uni_chg = tokens.get("uniswap", {}).get("change_24h_pct")
        aave_chg = tokens.get("aave", {}).get("change_24h_pct")

        if vol is not None:
            if vol > 3e9:
                score += 1.5
            elif vol > 1e9:
                score += 0.5
            elif vol < 3e8:
                score -= 1.0

        if uni_chg is not None:
            if uni_chg > 5:
                score += 1.0
            elif uni_chg < -8:
                score -= 1.5

        if aave_chg is not None and aave_chg < -5:
            score -= 0.5

        return round(max(0.0, min(10.0, score)), 2)
