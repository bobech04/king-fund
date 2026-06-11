import sys
import json
import re
import threading
import logging
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

try:
    import anthropic as _anthropic
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False
    logger.warning("anthropic package not installed — Morning Brief disabled")

def _extract_json(text: str) -> dict:
    """
    Parse a JSON object from Claude's response, tolerating:
    - markdown code fences  (```json … ```)
    - leading/trailing prose before or after the object
    Raises ValueError if no valid JSON object is found.
    """
    # 1. Strip markdown fences
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    text = re.sub(r"```", "", text).strip()

    # 2. Direct parse (happy path — text is already clean JSON)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 3. Extract the first {...} block (handles leading/trailing prose)
    match = re.search(r"\{.*?\}", text, re.DOTALL)
    if match:
        return json.loads(match.group())

    raise ValueError(f"No JSON object found in Claude response: {text!r}")


_PROMPT = """\
You are a concise sell-side analyst. Today is {date}.

Current market prices (USD):
{prices_block}
{liquidity_block}{bertez_block}
Generate an intraday market outlook as valid JSON only (no markdown fences):
{{
  "direction": "bullish" | "bearish" | "neutral",
  "confidence": 0.0-1.0,
  "summary": "<one sentence>"
}}"""


def _get_liquidity_block() -> str:
    """Retourne le contexte de liquidite si disponible, chaine vide sinon."""
    try:
        from divisions.middle_office import get_liquidity_desk
        desk = get_liquidity_desk()
        data = desk.get_data_cached_only()
        if data is None:
            return ""
        score = data.get("global_liquidity_score")
        regime = data.get("regime", "?")
        summaries = data.get("agent_scores", {})
        lines = [f"Liquidity conditions (score: {score}/10 — regime: {regime}):"]
        for agent, s in summaries.items():
            lines.append(f"  {agent}: {s}/10")
        return "\n".join(lines) + "\n"
    except Exception:
        return ""


def _get_bertez_block() -> str:
    """
    Contexte Bertez pour le Morning Brief et le Risk Committee.
    Lit le cache de BertezEnergyAgent (mis à jour à chaque run du desk liquidité).
    Injecte : mode, ratio énergie/PIB, dette productive, Bastiat flags, rotation si défensif.
    """
    try:
        from divisions.middle_office.desk_liquidite.agents.agent_bertez import (
            get_last_bertez_result,
        )
        r = get_last_bertez_result()
        if not r:
            return ""

        mode       = r.get("mode", "NEUTRE")
        score      = r.get("liquidity_score")
        data       = r.get("data", {})
        eg         = data.get("energy_gdp", {})
        pd_        = data.get("productive_debt", {})
        bastiat    = data.get("bastiat", {})
        rotation   = data.get("rotation", {})

        lines = [f"Bertez Energy Signal (score: {score}/10 — mode: {mode}):"]

        chg = eg.get("change_pct")
        if chg is not None:
            lines.append(f"  Energy/GDP ratio Δ12m: {chg:+.1f}%")

        wti = eg.get("wti_latest")
        if wti:
            lines.append(f"  WTI: {wti}$/b")

        pa = pd_.get("assessment")
        if pa:
            lines.append(f"  Productive debt: {pa} (ratio={pd_.get('ratio')})")

        b_level = bastiat.get("risk_level")
        if b_level:
            lines.append(f"  Bastiat off-balance-sheet risk: {b_level}")
        for flag in bastiat.get("flags", [])[:2]:
            lines.append(f"    • {flag}")

        if mode == "DEFENSIF" and rotation.get("active"):
            tickers = list(rotation.get("prices", {}).keys())[:6]
            if tickers:
                lines.append(f"  DEFENSIVE ROTATION: {', '.join(tickers)}")

        return "\n".join(lines) + "\n"
    except Exception:
        return ""


class MorningBrief:
    """
    Daily market outlook powered by Claude.
    Generates once per calendar day; result is cached until midnight.
    Thread-safe singleton — use get_morning_brief() to obtain the instance.
    """

    def __init__(self):
        self._lock       = threading.Lock()
        self._cache:      dict | None = None
        self._cache_date: date | None = None
        self._client = None
        if _AVAILABLE and ANTHROPIC_API_KEY:
            try:
                self._client = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            except Exception as e:
                logger.warning(f"Anthropic init error: {e}")

    def _call_claude(self, prices: dict) -> dict:
        if self._client is None:
            return {"direction": "neutral", "confidence": 0.5, "summary": "API unavailable"}
        prices_block = "\n".join(
            f"  {sym}: {price:.4f}" for sym, price in sorted(prices.items())
        )
        prompt = _PROMPT.format(
            date=date.today().isoformat(),
            prices_block=prices_block,
            liquidity_block=_get_liquidity_block(),
            bertez_block=_get_bertez_block(),
        )
        try:
            msg = self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text
            return _extract_json(raw)
        except Exception as e:
            raw_preview = locals().get("raw", "")[:120]
            logger.warning(f"Morning Brief error: {e} | raw: {raw_preview!r}")
            return {"direction": "neutral", "confidence": 0.5, "summary": str(e)}

    def get_brief(self, prices: dict) -> dict:
        """
        Returns today's brief dict: {direction, confidence, summary}.
        Refreshed once per calendar day.
        """
        today = date.today()
        with self._lock:
            if self._cache_date == today and self._cache is not None:
                return self._cache
        brief = self._call_claude(prices)
        with self._lock:
            self._cache      = brief
            self._cache_date = today
        logger.info(
            "Morning Brief: %s (conf=%.2f) — %s",
            brief.get("direction"),
            brief.get("confidence", 0.5),
            brief.get("summary", ""),
        )
        try:
            from data.signal_history import log_signal as _log_signal
            _log_signal(
                "morning_brief",
                brief.get("direction"),
                brief.get("confidence"),
                None, None,
            )
        except Exception:
            pass
        return brief

    def direction_signal(self, prices: dict) -> float:
        """
        Returns -1.0 (bearish), 0.0 (neutral), +1.0 (bullish).
        Scaled by confidence.
        """
        brief      = self.get_brief(prices)
        direction  = brief.get("direction", "neutral")
        confidence = float(brief.get("confidence", 0.5))
        if direction == "bullish":
            return confidence
        if direction == "bearish":
            return -confidence
        return 0.0


_instance: MorningBrief | None = None
_lock = threading.Lock()


def get_morning_brief() -> MorningBrief:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = MorningBrief()
    return _instance
