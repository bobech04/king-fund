"""
Garde-fou anti-hallucination — Division Investissement.

Règle absolue : toute donnée financière (prix, market cap, P/E, etc.)
DOIT provenir de yfinance ou du pipeline réel. Jamais de mémoire Claude.

Ce module :
- Vérifie la fraîcheur du prix yfinance (< 1h ou DONNÉES STALE)
- Injecte un disclaimer horodaté dans chaque rapport
- Marque la source comme "pipeline_reel" pour audit
"""
from __future__ import annotations
import yfinance as yf
from datetime import datetime, timezone
from typing import Any

FRAICHEUR_MAX_HEURES = 1


def verifier_fraicheur_prix(ticker: str) -> dict[str, Any]:
    """
    Interroge yfinance et vérifie que le dernier prix a moins d'1h.
    Statut retourné : "OK" | "DONNÉES STALE" | "INDISPONIBLE"
    """
    now_utc = datetime.now(timezone.utc)
    try:
        t = yf.Ticker(ticker)
        fi = t.fast_info
        prix = getattr(fi, "last_price", None)
        trade_time_raw = getattr(fi, "regular_market_time", None)

        if prix is None:
            return _resultat(ticker, None, None, "INDISPONIBLE", False, now_utc)

        # regular_market_time : Unix timestamp int ou datetime
        dt_marche: datetime | None = None
        if isinstance(trade_time_raw, (int, float)):
            dt_marche = datetime.fromtimestamp(trade_time_raw, tz=timezone.utc)
        elif isinstance(trade_time_raw, datetime):
            dt_marche = (
                trade_time_raw
                if trade_time_raw.tzinfo
                else trade_time_raw.replace(tzinfo=timezone.utc)
            )

        if dt_marche is None:
            statut, ok = "DONNÉES STALE", False
        else:
            age_h = (now_utc - dt_marche).total_seconds() / 3600
            if age_h <= FRAICHEUR_MAX_HEURES:
                statut, ok = "OK", True
            else:
                statut, ok = "DONNÉES STALE", False

        return _resultat(ticker, prix, dt_marche, statut, ok, now_utc)

    except Exception as exc:
        return {
            "ticker": ticker,
            "prix": None,
            "statut": "INDISPONIBLE",
            "fraicheur_ok": False,
            "timestamp_marche": None,
            "timestamp_verif": now_utc.isoformat(),
            "erreur": str(exc),
        }


def _resultat(
    ticker: str,
    prix: float | None,
    dt_marche: datetime | None,
    statut: str,
    ok: bool,
    now_utc: datetime,
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "prix": prix,
        "statut": statut,
        "fraicheur_ok": ok,
        "timestamp_marche": dt_marche.isoformat() if dt_marche else None,
        "timestamp_verif": now_utc.isoformat(),
    }


def ajouter_disclaimer(rapport: dict[str, Any], fraicheur: dict[str, Any]) -> dict[str, Any]:
    """
    Injecte le bloc _garde_fou dans le rapport du pipeline.
    Si données stale, préfixe la recommandation finale.
    """
    statut = fraicheur.get("statut", "INDISPONIBLE")
    ts_verif = fraicheur.get("timestamp_verif", datetime.now(timezone.utc).isoformat())

    try:
        ts_lisible = datetime.fromisoformat(ts_verif).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        ts_lisible = ts_verif

    disclaimer = (
        f"Prix vérifié le {ts_lisible} via yfinance | "
        f"Statut données : {statut} | "
        "Si ce disclaimer est absent, l'analyse est suspecte"
    )

    rapport["_garde_fou"] = {
        "disclaimer": disclaimer,
        "statut_donnees": statut,
        "fraicheur_ok": fraicheur.get("fraicheur_ok", False),
        "timestamp_verif": ts_verif,
        "timestamp_marche": fraicheur.get("timestamp_marche"),
        "prix_verifie": fraicheur.get("prix"),
        "generee_par": "pipeline_reel",
    }

    if statut != "OK":
        reco = rapport.get("recommandation_finale", "N/A")
        rapport["recommandation_finale"] = f"[{statut}] {reco}"

    return rapport
