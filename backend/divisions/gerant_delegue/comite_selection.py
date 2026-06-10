"""
Comité de Sélection — Division Gérant Délégué
Préside : AGD-01 (Dr Alexandre Redon)
Séance : 23:00 chaque soir de trading

Votants (3 membres) :
  1. Research     — AgentDueDiligence + AgentRapport (score pipeline + EDGAR + thèse)
  2. CIO          — CIOAllocationMacro + AgentBertez (macro alignment, WTI, thèse Bertez)
  3. Fiscaliste   — FiscalisteAgent (flat tax 30%, DZD 15k€/an, convention DZ-FR, CERFA 3916)

Règle de décision :
  3/3 OUI → BUY CONFIRMÉ — alerte Telegram critique
  2/3 OUI → BUY CONDITIONNEL — alerte Telegram warning
  1/3 OUI → HOLD AVEC REVUE
  0/3     → VETO — alerte Telegram critique

Résultats persistés dans rapports/comite/YYYY-MM-DD.json
"""
from __future__ import annotations

import json
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

_RAPPORTS_DIR = Path(__file__).resolve().parents[4] / "rapports" / "comite"

_SYSTEM_FISCALISTE = """\
Tu es le Fiscaliste du King Fund.
Spécialité : fiscalité des investissements France + Algérie.
Contraintes à vérifier pour chaque titre :
  - Flat Tax PFU 30% (12.8% IR + 17.2% prélèvements sociaux) sur dividendes et PV mobilières
  - Or physique : taxe forfaitaire 11.5% ou régime PV exonéré après 22 ans de détention
  - Stellantis (déjà en portefeuille) : ~0.74€/an PFU
  - Épargne DZD rapatriement : max 15 000€/an, frais 3-7%, CERFA 3916 obligatoire
  - Convention fiscale DZ-FR du 17/10/1999 : éviter double imposition
  - Banques agréées pour transfert DZD : CPA/BEA/BNA/BADR uniquement
Réponds en JSON valide uniquement. Pas de texte libre."""

_PROMPT_FISCALISTE = """\
Analyse fiscale pour l'achat de {ticker} ({nom}).
Montant envisagé : {montant} €
Dividende annuel estimé : {div_yield}%
Plus-value estimée sur 3 ans : {pv_estimee}%
Pays de domiciliation du titre : {pays}
Score pipeline : {score}/10

Contexte portefeuille Zoubida :
  - Apports mensuels 500€
  - Objectif retraite 56 ans (2041), 500 000€ cible
  - DZD épargne 17 000€ — rapatriement partiel prévu

Donne ton vote fiscal en JSON :
{{
  "vote": "OUI" | "NON" | "ABSTENTION",
  "motif": "raison fiscale principale (max 60 mots)",
  "impact_flat_tax_annuel": euros_estimés,
  "conditions": ["condition 1 si applicable", ...],
  "cerfa_3916_requis": true | false,
  "risque_double_imposition": true | false
}}"""

_PROMPT_CIO = """\
Tu es le CIO du King Fund (allocation macro, thèse Bertez WTI/dollar, DSPX dispersion).
Analyse l'opportunité d'investissement pour {ticker} ({nom}).

Contexte macro actuel :
  Howell signal : {howell_regime}
  VIX : {vix}
  DXY : {dxy}
  Régime Bertez : {bertez_regime}
  Allocation CIO actuelle : {cio_allocation}
  DSPX dispersion : {dspx_regime}

Données titre :
  Score pipeline : {score}/10
  Signal : {signal}
  Secteur : {secteur}
  Pays : {pays}

Donne ton vote CIO en JSON :
{{
  "vote": "OUI" | "NON" | "ABSTENTION",
  "motif": "raison macro principale (max 60 mots)",
  "alignement_macro": 0.0-1.0,
  "conditions": ["condition 1 si applicable", ...],
  "horizon_recommande": "court_terme" | "moyen_terme" | "long_terme"
}}"""


class ComiteSelection:
    """
    Orchestre le vote des 3 membres du Comité de Sélection.
    Thread-safe. Singleton.
    """

    def __init__(self) -> None:
        self._lock      = threading.Lock()
        self._historique: list[dict] = []
        self._client    = None
        self._init_claude()
        _RAPPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Claude
    # ------------------------------------------------------------------

    def _init_claude(self) -> None:
        try:
            from config import ANTHROPIC_API_KEY
            import anthropic
            if ANTHROPIC_API_KEY:
                self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
                logger.info("[Comite] Claude initialisé")
        except Exception as e:
            logger.warning("[Comite] Claude non disponible: %s", e)

    def _claude(self, system: str, prompt: str, max_tokens: int = 300) -> dict:
        if self._client is None:
            return {"vote": "ABSTENTION", "motif": "Agent indisponible", "conditions": []}
        try:
            from agents.formation import enrichir_systeme
            sys_enrichi = enrichir_systeme(system)
        except Exception:
            sys_enrichi = system
        try:
            msg = self._client.messages.create(
                model      = "claude-sonnet-4-6",
                max_tokens = max_tokens,
                system     = sys_enrichi,
                messages   = [{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            return json.loads(raw)
        except Exception as e:
            logger.warning("[Comite] Claude erreur: %s", e)
            return {"vote": "ABSTENTION", "motif": f"Erreur Claude: {e}", "conditions": []}

    # ------------------------------------------------------------------
    # Vote Research (pipeline + rapport)
    # ------------------------------------------------------------------

    def _vote_research(self, ticker: str, donnees: dict) -> dict:
        score  = donnees.get("score_final") or donnees.get("score_pipeline") or 0
        signal = donnees.get("signal", "N/A")
        marge  = donnees.get("marge_securite_analyste") or donnees.get("marge_securite_dcf") or 0

        if isinstance(score, (int, float)) and score >= 7.0 and "BUY" in str(signal):
            vote   = "OUI"
            motif  = f"Score pipeline {score:.1f}/10, signal {signal}, marge sécurité {marge:.0%}"
            cond   = []
        elif isinstance(score, (int, float)) and score >= 5.0:
            vote   = "OUI"
            motif  = f"Score acceptable {score:.1f}/10 — signal {signal}"
            cond   = [f"Surveiller marge sécurité ({marge:.0%} actuelle)"]
        else:
            vote   = "NON"
            motif  = f"Score insuffisant {score}/10 — pipeline reject"
            cond   = []

        rapport = donnees.get("rapport", "")
        if rapport:
            motif  += f" | Extrait rapport: {rapport[:80]}…"

        return {
            "votant":     "Research",
            "vote":       vote,
            "motif":      motif,
            "score":      score,
            "signal":     signal,
            "conditions": cond,
        }

    # ------------------------------------------------------------------
    # Vote CIO (macro + Bertez)
    # ------------------------------------------------------------------

    def _vote_cio(self, ticker: str, donnees: dict) -> dict:
        # Contexte macro
        howell_regime = "N/A"
        vix = dxy = "N/A"
        bertez_regime = "N/A"
        cio_allocation = "N/A"
        dspx_regime   = "N/A"

        try:
            from divisions.gerant_delegue.agd_01 import get_gerant_delegue
            h = get_gerant_delegue().howell_signal()
            howell_regime = h["regime"]
            vix = h.get("vix", "N/A")
            dxy = h.get("dxy", "N/A")
        except Exception:
            pass

        try:
            from divisions.investissement.agent_bertez import get_agent_bertez
            b = get_agent_bertez().analyser()
            bertez_regime = b.get("regime", "N/A")
        except Exception:
            pass

        try:
            from divisions.cio.allocation_macro import get_cio_allocation
            c = get_cio_allocation().analyser()
            cio_allocation = c.get("regime", "N/A")
        except Exception:
            pass

        prompt = _PROMPT_CIO.format(
            ticker         = ticker,
            nom            = donnees.get("nom", ticker),
            howell_regime  = howell_regime,
            vix            = vix,
            dxy            = dxy,
            bertez_regime  = bertez_regime,
            cio_allocation = cio_allocation,
            dspx_regime    = dspx_regime,
            score          = donnees.get("score_final", "N/A"),
            signal         = donnees.get("signal", "N/A"),
            secteur        = donnees.get("secteur", "N/A"),
            pays           = donnees.get("pays", "N/A"),
        )

        result = self._claude(_PROMPT_CIO, prompt, max_tokens=300)
        return {"votant": "CIO", **result}

    # ------------------------------------------------------------------
    # Vote Fiscaliste
    # ------------------------------------------------------------------

    def _vote_fiscaliste(self, ticker: str, donnees: dict) -> dict:
        prompt = _PROMPT_FISCALISTE.format(
            ticker      = ticker,
            nom         = donnees.get("nom", ticker),
            montant     = donnees.get("montant_envisage", 200),
            div_yield   = f"{(donnees.get('dividende') or 0) * 100:.1f}" if donnees.get("dividende") else "N/A",
            pv_estimee  = donnees.get("pv_estimee_3ans_pct", "N/A"),
            pays        = donnees.get("pays", "France"),
            score       = donnees.get("score_final", "N/A"),
        )
        result = self._claude(_SYSTEM_FISCALISTE, prompt, max_tokens=300)
        return {"votant": "Fiscaliste", **result}

    # ------------------------------------------------------------------
    # Décision finale
    # ------------------------------------------------------------------

    @staticmethod
    def _compiler_decision(votes: list[dict]) -> tuple[str, str]:
        """Retourne (decision, niveau_alerte)."""
        nb_oui = sum(1 for v in votes if v.get("vote") == "OUI")
        if nb_oui == 3:
            return "BUY CONFIRMÉ",     "critique"
        elif nb_oui == 2:
            return "BUY CONDITIONNEL", "warning"
        elif nb_oui == 1:
            return "HOLD AVEC REVUE",  "info"
        return "VETO",                 "critique"

    # ------------------------------------------------------------------
    # Public : voter
    # ------------------------------------------------------------------

    def voter(self, ticker: str, donnees: dict) -> dict:
        """
        Lance le vote des 3 membres pour un ticker.
        Envoie alerte Telegram et persiste le résultat.
        """
        ts = datetime.now(timezone.utc)
        logger.info("[Comite] Ouverture séance — %s", ticker)

        v_research   = self._vote_research(ticker, donnees)
        v_cio        = self._vote_cio(ticker, donnees)
        v_fiscaliste = self._vote_fiscaliste(ticker, donnees)

        votes    = [v_research, v_cio, v_fiscaliste]
        decision, niveau = self._compiler_decision(votes)

        resume_votes = " | ".join(
            f"{v['votant']}: {v['vote']}" for v in votes
        )
        conditions_all = []
        for v in votes:
            conditions_all.extend(v.get("conditions", []))

        # Alerte Telegram
        icon_dec = {"BUY CONFIRMÉ": "✅", "BUY CONDITIONNEL": "🟡", "HOLD AVEC REVUE": "🔵", "VETO": "🛑"}
        msg = (
            f"🏛️ <b>COMITÉ SÉLECTION — {ticker}</b>\n"
            f"{'─' * 30}\n"
            f"{icon_dec.get(decision, '•')} <b>{decision}</b>\n\n"
            f"<b>Votes</b> : {resume_votes}\n\n"
            f"<b>Research</b> : {v_research.get('motif', '')[:80]}\n"
            f"<b>CIO</b>      : {v_cio.get('motif', '')[:80]}\n"
            f"<b>Fiscaliste</b>: {v_fiscaliste.get('motif', '')[:80]}\n"
        )
        if conditions_all:
            msg += f"\n<i>Conditions : {' / '.join(conditions_all[:3])}</i>\n"
        msg += f"\n<i>Séance : {ts.strftime('%d/%m/%Y %H:%M')} UTC | Gérant Délégué AGD-01</i>"
        send(msg)

        verdict = {
            "ticker":    ticker,
            "decision":  decision,
            "votes":     votes,
            "nb_oui":    sum(1 for v in votes if v.get("vote") == "OUI"),
            "conditions":conditions_all,
            "timestamp": ts.isoformat(),
            "donnees":   {k: v for k, v in donnees.items() if k not in ("rapport",)},
        }

        self._persister(verdict)
        with self._lock:
            self._historique.append(verdict)
            if len(self._historique) > 200:
                self._historique.pop(0)

        logger.info("[Comite] %s → %s (%s)", ticker, decision, resume_votes)
        return verdict

    def _persister(self, verdict: dict) -> None:
        try:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            chemin   = _RAPPORTS_DIR / f"comite_{date_str}.json"
            records  = []
            if chemin.exists():
                records = json.loads(chemin.read_text(encoding="utf-8"))
            records.append(verdict)
            chemin.write_text(
                json.dumps(records, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug("[Comite] Persistance: %s", e)

    def historique(self, n: int = 20) -> list[dict]:
        with self._lock:
            return list(reversed(self._historique))[:n]

    def etat(self) -> dict:
        return {
            "nb_seances":  len(self._historique),
            "dernieres":   self.historique(5),
            "timestamp":   datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_instance: ComiteSelection | None = None
_lock = threading.Lock()


def get_comite_selection() -> ComiteSelection:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = ComiteSelection()
    return _instance
