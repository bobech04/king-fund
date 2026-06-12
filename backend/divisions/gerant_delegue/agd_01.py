"""
AGD-01 — Agent Gérant Délégué
PhD Finance (MIT), CFA, FRM — 20 ans : Bridgewater · Goldman Sachs · Scion Capital · Berkshire

Responsabilités :
  • Rapport hebdomadaire lundi 08:00 → Telegram
  • Préside Comité Sélection 23:00 (veto 3/3)
  • Intègre signal Howell (liquidité mondiale, dollar, EM)
  • Peut opposer un VETO aux décisions émotionnelles de Zoubida
  • Calcule multiplicateur SITG selon performance annualisée
  • Objectif retraite Zoubida à 56 ans (2041) — non négociable
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from divisions.gerant_delegue.notifier import alerte, send

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
OBJECTIF_RETRAITE_ANNEE = 2041          # Zoubida 56 ans
OBJECTIF_RETRAITE_MONTANT = 500_000.0   # € patrimoine cible
SITG_SEUILS = [                         # (perf_min%, multiplicateur)
    (25.0, 2.00),
    (15.0, 1.50),
    (10.0, 1.25),
]
HOWELL_DXY_SEUIL  = 103.0   # dollar fort si DXY ≥ 103
HOWELL_VIX_SOMMET = 28.0    # appétit risque au sommet si VIX < 15 + spread serré

_SYSTEM_AGD = """\
Tu es le Dr Alexandre Redon, Gérant Délégué du King Fund.
Profil : PhD Finance MIT, CFA Level 3, FRM.
Expérience : 20 ans — Bridgewater Associates (Senior Portfolio Manager),
Goldman Sachs (Head of Macro Risk), Scion Capital Michael Burry (Quant Lead),
Berkshire Hathaway (Investment Analyst sous Warren Buffett).
Valeurs : sérénité absolue, rigueur sans concession, humilité intellectuelle, discipline de fer.
Objectif non négociable : préserver et faire croître le patrimoine de Zoubida
pour lui permettre de prendre sa retraite à 56 ans en 2041 avec 500 000 €.
Tu peux et dois opposer un VETO à toute décision émotionnelle ou irrationnelle.
Réponds toujours en JSON valide. Pas de markdown."""

_PROMPT_VETO = """\
Zoubida propose la décision suivante :
Ticker : {ticker}
Action  : {action}
Montant : {montant} €
Contexte fourni : {contexte}

Contexte de marché (signal Howell) :
{howell}

Performance annualisée King Fund : {perf_annualisee:.1f}%
Patrimoine actuel : {patrimoine:.0f} €
Objectif retraite : {objectif:.0f} € en {annee_retraite}

Évalue si cette décision est rationnelle ou émotionnelle.
Réponds en JSON :
{{
  "decision": "VALIDE" | "VETO",
  "confiance": 0.0-1.0,
  "raison": "courte explication factuelle",
  "recommandation": "ce que tu conseilles à la place si VETO",
  "regles_violees": ["règle 1", ...]
}}"""

_PROMPT_RAPPORT = """\
Rédige le rapport hebdomadaire du Gérant Délégué King Fund — semaine {semaine} {annee}.

Données de la semaine :
{donnees}

Signal Howell liquidité mondiale :
{howell}

Performance vs objectif retraite 2041 :
{projection}

Structure du rapport (max 400 mots, institutionnel, sans markdown) :
1. SYNTHÈSE DE LA SEMAINE (3 phrases max)
2. POSITIONNEMENT ACTUEL (allocation, biais directionnel)
3. RISQUES MAJEURS IDENTIFIÉS (3 maximum)
4. DÉCISIONS COMITÉ SÉLECTION (résumé votes)
5. ACTIONS POUR LA SEMAINE PROCHAINE (2-3 actions concrètes)
6. INDICATEUR RETRAITE (écart entre trajectoire actuelle et objectif 2041)
7. MOT DU GÉRANT (1 phrase sobre, sans formule creuse)"""


class AgentGerantDelegue:
    """
    Agent orchestrateur — Gérant Délégué du King Fund.
    Singleton. Thread-safe.
    """

    def __init__(self) -> None:
        self._lock   = threading.Lock()
        self._client = None
        self._howell_cache: dict = {}
        self._howell_ts: float  = 0.0
        self._dernier_rapport:  str = ""
        self._claude_down_alerted_at: float = 0.0  # anti-spam : 1 alerte/heure max
        self._init_claude()

    # ------------------------------------------------------------------
    # Claude API
    # ------------------------------------------------------------------

    def _init_claude(self) -> None:
        try:
            from config import ANTHROPIC_API_KEY
            import anthropic
            if ANTHROPIC_API_KEY:
                self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
                logger.info("[AGD-01] Claude Opus initialisé")
        except Exception as e:
            logger.warning("[AGD-01] Claude non disponible: %s", e)

    def _claude_unavailable_alert(self, reason: str) -> None:
        """Envoie une alerte Telegram si Claude est down, au plus 1 fois par heure."""
        now = time.time()
        if now - self._claude_down_alerted_at < 3600:
            return
        self._claude_down_alerted_at = now
        try:
            alerte(
                "AGD-01 HORS LIGNE",
                f"⚠️ Claude Opus indisponible — les évaluations VETO sont suspendues.\n"
                f"Raison : {reason}\n"
                f"Les décisions ne sont PAS analysées tant que l'API est inaccessible.",
                niveau="warning",
            )
        except Exception:
            pass

    def _claude(self, prompt: str, max_tokens: int = 600) -> str:
        if self._client is None:
            logger.warning("[AGD-01] _client is None — Claude non initialisé")
            self._claude_unavailable_alert("ANTHROPIC_API_KEY absent ou invalide")
            return "{}"
        try:
            from agents.formation import enrichir_systeme
            system = enrichir_systeme(_SYSTEM_AGD)
        except Exception:
            system = _SYSTEM_AGD
        try:
            msg = self._client.messages.create(
                model      = "claude-opus-4-8",
                max_tokens = max_tokens,
                system     = system,
                messages   = [{"role": "user", "content": prompt}],
            )
            return msg.content[0].text.strip()
        except Exception as e:
            logger.warning("[AGD-01] Erreur Claude: %s", e)
            self._claude_unavailable_alert(str(e)[:120])
            return "{}"

    # ------------------------------------------------------------------
    # SITG — Skin In The Game multiplicateur
    # ------------------------------------------------------------------

    @staticmethod
    def sitg_multiplicateur(perf_annualisee: float) -> float:
        """Retourne le multiplicateur SITG selon la performance annualisée."""
        for seuil, mult in SITG_SEUILS:
            if perf_annualisee >= seuil:
                return mult
        return 1.0

    @staticmethod
    def sitg_label(perf_annualisee: float) -> str:
        mult = AgentGerantDelegue.sitg_multiplicateur(perf_annualisee)
        if mult == 2.0:
            return f"SITG ×2.0 — EXCEPTIONNEL (+{perf_annualisee:.1f}% ≥ +25%/an)"
        if mult == 1.5:
            return f"SITG ×1.5 — TRÈS BON (+{perf_annualisee:.1f}% entre +15% et +25%/an)"
        if mult == 1.25:
            return f"SITG ×1.25 — BON (+{perf_annualisee:.1f}% entre +10% et +15%/an)"
        return f"SITG ×1.0 — NEUTRE (+{perf_annualisee:.1f}% < +10%/an)"

    # ------------------------------------------------------------------
    # Signal Howell — liquidité mondiale
    # ------------------------------------------------------------------

    def howell_signal(self, forcer: bool = False) -> dict:
        """
        Signal Michael Howell / CrossBorderCapital.
        Indicateurs : DXY, VIX, spreads EM, liquidité globale via LiquidityClient.
        Cache 4h.
        """
        now = time.monotonic()
        if not forcer and self._howell_cache and (now - self._howell_ts) < 14_400:
            return self._howell_cache

        signal = {
            "liquidite_fragile":      False,
            "sommet_appetit_risque":  False,
            "dollar_fort":            False,
            "emergents_pression":     False,
            "dxy":                    None,
            "vix":                    None,
            "score_liquidite_global": None,
            "regime":                 "NEUTRE",
            "resume":                 "",
        }

        try:
            import yfinance as yf

            dxy_tick = yf.Ticker("DX-Y.NYB")
            dxy_hist = dxy_tick.history(period="2d", interval="1d")
            if not dxy_hist.empty:
                signal["dxy"] = round(float(dxy_hist["Close"].iloc[-1]), 2)
                signal["dollar_fort"] = signal["dxy"] >= HOWELL_DXY_SEUIL

            vix_tick = yf.Ticker("^VIX")
            vix_hist = vix_tick.history(period="2d", interval="1d")
            if not vix_hist.empty:
                signal["vix"] = round(float(vix_hist["Close"].iloc[-1]), 2)
                signal["sommet_appetit_risque"] = signal["vix"] < 15.0

            # Pression EM : EEM (ETF marchés émergents) vs SPY rolling 20j
            eem = yf.download("EEM SPY", period="30d", interval="1d",
                              progress=False, auto_adjust=True)
            if "Close" in eem.columns and not eem["Close"].empty:
                ratio = eem["Close"]["EEM"] / eem["Close"]["SPY"]
                perf_ratio_20j = (ratio.iloc[-1] / ratio.iloc[0] - 1) * 100
                signal["emergents_pression"] = perf_ratio_20j < -3.0
        except Exception as e:
            logger.debug("[AGD-01] Howell market data: %s", e)

        try:
            from data.liquidity_client import get_liquidity_client
            liq = get_liquidity_client()
            score = liq.global_score()
            signal["score_liquidite_global"] = score
            signal["liquidite_fragile"] = score < 4.0
        except Exception:
            pass

        # Régime global
        alertes = sum([
            signal["liquidite_fragile"],
            signal["dollar_fort"],
            signal["emergents_pression"],
            signal["sommet_appetit_risque"],
        ])
        if alertes >= 3:
            signal["regime"] = "HOWELL_DANGER"
        elif alertes >= 2:
            signal["regime"] = "HOWELL_VIGILANCE"
        elif alertes == 1:
            signal["regime"] = "HOWELL_ATTENTION"
        else:
            signal["regime"] = "HOWELL_SEREIN"

        parties = []
        if signal["liquidite_fragile"]:
            parties.append("liquidité mondiale fragile")
        if signal["dollar_fort"]:
            parties.append(f"dollar fort (DXY {signal['dxy']})")
        if signal["emergents_pression"]:
            parties.append("marchés émergents sous pression")
        if signal["sommet_appetit_risque"]:
            parties.append(f"sommet appétit risque (VIX {signal['vix']})")
        signal["resume"] = " | ".join(parties) if parties else "Environnement favorable"

        self._howell_cache = signal
        self._howell_ts    = now
        logger.info("[AGD-01] Howell: %s — %s", signal["regime"], signal["resume"])
        return signal

    # ------------------------------------------------------------------
    # VETO Décision Émotionnelle
    # ------------------------------------------------------------------

    def evaluer_decision(
        self,
        ticker:           str,
        action:           str,
        montant:          float,
        contexte:         str  = "",
        perf_annualisee:  float = 0.0,
        patrimoine:       float = 18_082.0,
    ) -> dict:
        """
        Le Gérant Délégué évalue si la décision de Zoubida est rationnelle.
        Retourne dict: {decision, confiance, raison, recommandation, regles_violees}
        """
        howell = self.howell_signal()
        prompt = _PROMPT_VETO.format(
            ticker            = ticker,
            action            = action,
            montant           = montant,
            contexte          = contexte or "(aucun contexte fourni)",
            howell            = howell["resume"],
            perf_annualisee   = perf_annualisee,
            patrimoine        = patrimoine,
            objectif          = OBJECTIF_RETRAITE_MONTANT,
            annee_retraite    = OBJECTIF_RETRAITE_ANNEE,
        )
        raw = self._claude(prompt, max_tokens=800)
        try:
            import json
            result = json.loads(raw)
        except Exception:
            result = {"decision": "VALIDE", "raison": "⚠️ AGD-01 hors ligne — décision non analysée (Claude indisponible)",
                      "confiance": 0.0, "recommandation": "Vérifier la disponibilité de l'API Anthropic avant d'agir.",
                      "regles_violees": ["API_INDISPONIBLE"]}

        if result.get("decision") == "VETO":
            alerte(
                "VETO GÉRANT DÉLÉGUÉ",
                f"<b>{ticker}</b> — {action.upper()} {montant:.0f}€\n"
                f"Raison : {result.get('raison', '?')}\n"
                f"Conseil : {result.get('recommandation', '?')}",
                niveau="veto",
            )
            logger.warning("[AGD-01] VETO émis sur %s %s %s€", ticker, action, montant)
        else:
            logger.info("[AGD-01] Décision VALIDÉE : %s %s %s€", ticker, action, montant)

        try:
            from divisions.gerant_delegue.audit_agd import log_decision as _audit
            _audit(
                "evaluer_decision",
                ticker=ticker,
                action=action,
                montant=round(montant, 2),
                decision=result.get("decision"),
                confiance=result.get("confiance"),
                raison=result.get("raison"),
                regles_violees=result.get("regles_violees"),
                howell_regime=howell.get("regime"),
                perf_annualisee=round(perf_annualisee, 2),
            )
        except Exception as _ae:
            logger.debug("[AGD-01] Audit write error: %s", _ae)

        return result

    # ------------------------------------------------------------------
    # Rapport hebdomadaire — lundi 08:00
    # ------------------------------------------------------------------

    def generer_rapport_lundi(self, donnees: dict | None = None) -> str:
        """Génère et envoie le rapport hebdomadaire via Telegram."""
        now    = datetime.now(timezone.utc)
        semaine = now.strftime("W%W")
        annee   = now.year
        howell  = self.howell_signal()

        perf_str    = donnees.get("perf_semaine", "N/A") if donnees else "N/A"
        nav_str     = donnees.get("nav", "N/A")          if donnees else "N/A"
        top5_str    = donnees.get("top5", "")             if donnees else ""
        comite_str  = donnees.get("comite_decisions", "") if donnees else ""

        # Projection retraite
        annes_restantes = OBJECTIF_RETRAITE_ANNEE - annee
        try:
            patrimoine_actuel = float(donnees.get("patrimoine", 18_082)) if donnees else 18_082.0
            taux_croissance   = float(donnees.get("taux_annualise", 10.0)) if donnees else 10.0
            projection        = patrimoine_actuel * ((1 + taux_croissance / 100) ** annes_restantes)
            ecart_projection  = projection - OBJECTIF_RETRAITE_MONTANT
            projection_str = (
                f"Patrimoine actuel : {patrimoine_actuel:.0f}€\n"
                f"Taux annualisé : {taux_croissance:.1f}%\n"
                f"Projection 2041 : {projection:.0f}€\n"
                f"Écart objectif 500k€ : {ecart_projection:+.0f}€"
            )
        except Exception:
            projection_str = "Données insuffisantes pour projection"

        donnees_str = (
            f"Semaine : {semaine} {annee}\n"
            f"NAV : {nav_str}\n"
            f"Performance semaine : {perf_str}\n"
            f"Top 5 positions : {top5_str or '(données manquantes)'}\n"
            f"Décisions Comité : {comite_str or '(aucune décision cette semaine)'}"
        )

        prompt = _PROMPT_RAPPORT.format(
            semaine    = semaine,
            annee      = annee,
            donnees    = donnees_str,
            howell     = howell["resume"],
            projection = projection_str,
        )

        rapport = self._claude(prompt, max_tokens=600)
        if not rapport or rapport == "{}":
            rapport = (
                f"RAPPORT {semaine} {annee} — Gérant Délégué\n"
                f"NAV : {nav_str} | Perf : {perf_str}\n"
                f"Howell : {howell['regime']} — {howell['resume']}\n"
                f"[Rapport Claude indisponible — données brutes]"
            )

        self._dernier_rapport = rapport
        sitg = self.sitg_label(float(donnees.get("perf_annualisee", 0)) if donnees else 0)
        message = (
            f"📋 <b>RAPPORT GÉRANT DÉLÉGUÉ — {semaine} {annee}</b>\n"
            f"────────────────────────────\n"
            f"{rapport}\n"
            f"────────────────────────────\n"
            f"<i>Howell : {howell['regime']}</i>\n"
            f"<i>{sitg}</i>\n"
            f"<i>Objectif retraite 2041 : 500 000€ — NON NÉGOCIABLE</i>"
        )
        send(message)
        logger.info("[AGD-01] Rapport lundi envoyé Telegram (%d car.)", len(message))

        try:
            from divisions.gerant_delegue.audit_agd import log_decision as _audit
            _audit(
                "rapport_lundi",
                semaine=semaine,
                annee=annee,
                howell_regime=howell.get("regime"),
                howell_resume=howell.get("resume"),
                nav=str(donnees.get("nav", "N/A") if donnees else "N/A"),
                perf_semaine=str(donnees.get("perf_semaine", "N/A") if donnees else "N/A"),
            )
        except Exception as _ae:
            logger.debug("[AGD-01] Audit rapport error: %s", _ae)

        return rapport

    # ------------------------------------------------------------------
    # Préside le Comité Sélection
    # ------------------------------------------------------------------

    def presider_comite(self, ticker: str, donnees_ticker: dict | None = None) -> dict:
        """
        Lance le Comité Sélection pour un ticker donné.
        Retourne le verdict final.
        """
        from divisions.gerant_delegue.comite_selection import get_comite_selection
        comite = get_comite_selection()
        verdict = comite.voter(ticker, donnees_ticker or {})
        logger.info("[AGD-01] Comité Sélection %s → %s", ticker, verdict.get("decision"))
        return verdict

    # ------------------------------------------------------------------
    # Etat
    # ------------------------------------------------------------------

    def etat(self) -> dict:
        howell = self.howell_signal()
        return {
            "agent":              "AGD-01",
            "nom":                "Dr Alexandre Redon",
            "qualifications":     "PhD Finance MIT · CFA · FRM",
            "experience":         "Bridgewater · Goldman Sachs · Scion Capital · Berkshire",
            "howell_regime":      howell["regime"],
            "howell_resume":      howell["resume"],
            "objectif_retraite":  {"annee": OBJECTIF_RETRAITE_ANNEE, "montant": OBJECTIF_RETRAITE_MONTANT},
            "sitg_grille":        [{"perf_min": s, "mult": m} for s, m in SITG_SEUILS],
            "dernier_rapport":    self._dernier_rapport[:200] if self._dernier_rapport else None,
            "timestamp":          datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_instance: AgentGerantDelegue | None = None
_lock = threading.Lock()


def get_gerant_delegue() -> AgentGerantDelegue:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = AgentGerantDelegue()
    return _instance
