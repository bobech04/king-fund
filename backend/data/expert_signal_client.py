"""
Expert signal aggregator for traders.

Combines:
  - desk_liquidite agent scores (sectoral experts: Yahoo_Equity, CoinGecko_Market, FRED_*)
  - banques_centrales sentiments (FED, BCE, BOJ … from RSS feeds)

Produces a per-symbol trading signal in [-1.0, +1.0] that the engine injects
into each trader's decision.  All underlying data is read from existing caches
(LiquidityDesk at 15 min, RSSClient at 1 h, FredClient at 24 h) — no new
network calls are made here.
"""
import threading
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain routing — which agents and central banks matter for each asset class
# ---------------------------------------------------------------------------

# liq_weights must sum to 1.0 per domain.
# cb_weight:     fraction of the final combined signal given to CB sentiment.
# bertez_weight: fraction given to the Bertez energy/GDP macro-structural signal.
#   equity_us — Bertez modère via le ratio énergie/PIB et la dette productive
#   crypto    — Bertez est moins direct (risque-on/off > structure énergétique)
_DOMAINS: dict[str, dict] = {
    "equity_us": {
        "liq_agents":    ["Yahoo_Equity", "FRED_Macro", "FRED_Credit"],
        "liq_weights":   [0.45,            0.35,         0.20],
        "cb_codes":      ["FED", "BCE"],
        "cb_weight":     0.25,
        "bertez_weight": 0.15,
        # combined = liq*(1-cb_w-bertez_w) + cb*cb_w + bertez*bertez_w
        # → liq poids effectif = 0.60
    },
    "equity_eu": {
        "liq_agents":    ["Yahoo_Equity", "FRED_Macro", "Bertez_Energy"],
        "liq_weights":   [0.40,            0.35,         0.25],
        "cb_codes":      ["BCE", "NORGES"],
        "cb_weight":     0.20,
        "bertez_weight": 0.20,
        # BCE + Norges pilotent les taux EU ; Bertez reflète l'exposition énergie/infrastructure
        # → liq poids effectif = 0.60
    },
    "crypto": {
        "liq_agents":    ["CoinGecko_Market", "CoinGecko_DeFi", "FRED_Macro"],
        "liq_weights":   [0.50,               0.25,              0.25],
        "cb_codes":      ["FED"],
        "cb_weight":     0.15,
        "bertez_weight": 0.05,
        # → liq poids effectif = 0.80
    },
}

_SYMBOL_DOMAIN: dict[str, str] = {
    "AAPL":    "equity_us",
    "MSFT":    "equity_us",
    "TSLA":    "equity_us",
    "AMZN":    "equity_us",
    "GOOGL":   "equity_us",
    "NVDA":    "equity_us",
    "META":    "equity_us",
    "NFLX":    "equity_us",
    "SPY":     "equity_us",
    "QQQ":     "equity_us",
    "GLD":     "equity_us",
    "BTC-USD": "crypto",
    "ETH-USD": "crypto",
    # Actifs européens — BCE + Norges + Bertez énergie
    "VPK.AS":  "equity_eu",
    "GTT.PA":  "equity_eu",
    "TTE.PA":  "equity_eu",
    "SU.PA":   "equity_eu",
    "TEL.OL":  "equity_eu",
    "DNB.OL":  "equity_eu",
}


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class ExpertSignalClient:
    """
    Read-only aggregator.  Thread-safe (relies on thread-safe underlying caches).

    Usage in traders:
        sig = self._experts.get_signal(self._symbol)   # [-1.0, +1.0]
    """

    def get_signal(self, symbol: str | None) -> float:
        """
        Composite expert signal for *symbol* in [-1.0, +1.0].

          +1.0  all sectoral experts, CBs and Bertez strongly bullish
          -1.0  all experts strongly bearish
           0.0  neutral / data not yet available

        Three-source blend:
          liq_sig    × (1 - cb_weight - bertez_weight)
          cb_sig     × cb_weight
          bertez_sig × bertez_weight
        """
        if not symbol:
            return 0.0
        domain_name = _SYMBOL_DOMAIN.get(symbol)
        if not domain_name:
            return 0.0
        domain = _DOMAINS[domain_name]

        liq_sig    = self._liq_signal(domain)
        cb_sig     = self._cb_signal(domain["cb_codes"])
        bertez_sig = self._bertez_signal()

        cb_w      = domain["cb_weight"]
        bertez_w  = domain["bertez_weight"]
        combined  = (
            liq_sig    * (1.0 - cb_w - bertez_w)
            + cb_sig   * cb_w
            + bertez_sig * bertez_w
        )
        return round(max(-1.0, min(1.0, combined)), 3)

    def get_breakdown(self, symbol: str) -> dict:
        """Detailed per-agent breakdown — useful for the UI or debugging."""
        domain_name = _SYMBOL_DOMAIN.get(symbol, "")
        if not domain_name:
            return {"symbol": symbol, "signal": 0.0, "domain": "unknown"}
        domain = _DOMAINS[domain_name]

        agent_sigs  = self._liq_agent_signals(domain)
        cb_sigs     = self._cb_agent_signals(domain["cb_codes"])
        bertez_sig  = self._bertez_signal()
        final       = self.get_signal(symbol)

        return {
            "symbol":         symbol,
            "domain":         domain_name,
            "signal":         final,
            "liq_signal":     round(self._liq_signal(domain), 3),
            "cb_signal":      round(self._cb_signal(domain["cb_codes"]), 3),
            "bertez_signal":  round(bertez_sig, 3),
            "bertez_mode":    self._bertez_mode(),
            "agent_signals":  agent_sigs,
            "cb_signals":     cb_sigs,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _liq_signal(self, domain: dict) -> float:
        signals = self._liq_agent_signals(domain)
        total_w = weighted = 0.0
        for agent, w in zip(domain["liq_agents"], domain["liq_weights"]):
            sig = signals.get(agent)
            if sig is not None:
                weighted += sig * w
                total_w  += w
        return (weighted / total_w) if total_w > 0 else 0.0

    def _liq_agent_signals(self, domain: dict) -> dict[str, float]:
        """Converts liquidity desk 0-10 scores to [-1, +1] signals."""
        try:
            from divisions.middle_office import get_liquidity_desk
            data = get_liquidity_desk().get_data_cached_only()
        except Exception:
            return {}
        if not data:
            return {}
        raw = data.get("agent_scores", {})
        return {
            agent: round((raw[agent] - 5.0) / 5.0, 3)
            for agent in domain["liq_agents"]
            if agent in raw
        }

    def _cb_signal(self, cb_codes: list[str]) -> float:
        signals = self._cb_agent_signals(cb_codes)
        return round(sum(signals.values()) / len(signals), 3) if signals else 0.0

    def _bertez_signal(self) -> float:
        """Signal macro-structurel Bertez en [-1, +1] (lecture cache — aucun I/O)."""
        try:
            from divisions.middle_office.desk_liquidite.agents.agent_bertez import (
                get_bertez_signal,
            )
            return get_bertez_signal()
        except Exception:
            return 0.0

    def _bertez_mode(self) -> str:
        """Mode courant Bertez : 'DEFENSIF', 'NEUTRE' ou 'OFFENSIF'."""
        try:
            from divisions.middle_office.desk_liquidite.agents.agent_bertez import (
                get_bertez_mode,
            )
            return get_bertez_mode()
        except Exception:
            return "NEUTRE"

    def _cb_agent_signals(self, cb_codes: list[str]) -> dict[str, float]:
        """Returns {cb_code: sentiment} in [-1, +1] from central bank RSS feeds."""
        if not cb_codes:
            return {}
        try:
            from divisions.banques_centrales import REGISTRY
        except Exception:
            return {}
        result = {}
        for code in cb_codes:
            bank = REGISTRY.get(code)
            if not bank:
                continue
            try:
                result[code] = round(bank.sentiment(), 3)
            except Exception:
                pass
        return result


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_instance: ExpertSignalClient | None = None
_lock = threading.Lock()


def get_expert_signal_client() -> ExpertSignalClient:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = ExpertSignalClient()
    return _instance
