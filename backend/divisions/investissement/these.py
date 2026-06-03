"""
Génération de thèses d'investissement via Claude API.
"""
from __future__ import annotations
import logging
import time
from typing import Any

try:
    import anthropic as _anthropic
    _AVAILABLE = True
except ImportError:
    _anthropic = None  # type: ignore[assignment]
    _AVAILABLE = False

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config import ANTHROPIC_API_KEY
from agents.formation import enrichir_systeme

logger = logging.getLogger(__name__)

CACHE_TTL   = 86_400   # 24 h
MODEL       = "claude-opus-4-8"
MAX_TOKENS  = 180

_SYSTEM = enrichir_systeme(
    "Tu es un analyste financier senior spécialisé en investissement value. "
    "Génère une thèse d'investissement synthétique en 2 phrases maximum (max 55 mots). "
    "Cite le principal moteur de valeur, la marge de sécurité, et le signal BUY/HOLD/SELL. "
    "Sois factuel, précis, sans formules creuses."
)


class TheseManager:
    def __init__(self) -> None:
        if not _AVAILABLE:
            raise ImportError("pip install anthropic>=0.40.0 requis")
        self._client    = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)  # type: ignore[union-attr]
        self._cache:    dict[str, str]   = {}
        self._cache_ts: dict[str, float] = {}

    def generer_theses(self, resultats: list[dict[str, Any]]) -> dict[str, str]:
        """Retourne {ticker: texte_these} pour chaque actif."""
        theses: dict[str, str] = {}
        for a in resultats:
            ticker = a.get("ticker", "")
            if not ticker or "erreur" in a:
                theses[ticker] = ""
                continue
            now = time.monotonic()
            if ticker in self._cache and (now - self._cache_ts.get(ticker, 0.0)) < CACHE_TTL:
                theses[ticker] = self._cache[ticker]
                continue
            try:
                texte = self._generer_une(a)
            except Exception as e:
                logger.warning("These %s: %s", ticker, e)
                texte = ""
            self._cache[ticker]    = texte
            self._cache_ts[ticker] = now
            theses[ticker]         = texte
        return theses

    def _generer_une(self, a: dict[str, Any]) -> str:
        score   = a.get("score")
        signal  = a.get("signal", "N/A")
        marge   = a.get("marge_securite")
        per     = a.get("per")
        pbr     = a.get("pbr")
        div     = a.get("dividende")
        secteur = a.get("secteur", "N/A")

        contexte = (
            f"Ticker: {a['ticker']} ({a['nom']}, {a['bourse']})\n"
            f"Secteur: {secteur}\n"
            f"Score pipeline 17 étapes: {f'{score:.1f}/10' if score is not None else 'N/A'}\n"
            f"Signal: {signal}\n"
            f"Marge de sécurité (vs cible analyste): {f'{marge*100:.1f}%' if marge is not None else 'N/A'}\n"
            f"PER: {f'{per:.1f}' if per else 'N/A'}  "
            f"PBR: {f'{pbr:.2f}' if pbr else 'N/A'}  "
            f"Dividende: {f'{div:.1%}' if div else 'N/A'}"
        )

        msg = self._client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_SYSTEM,
            messages=[{"role": "user", "content": contexte}],
        )
        return msg.content[0].text.strip()


_instance: TheseManager | None = None


def get_these_manager() -> TheseManager:
    global _instance
    if _instance is None:
        _instance = TheseManager()
    return _instance
