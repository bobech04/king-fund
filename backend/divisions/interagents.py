"""
Inter-Agent Communication Hub — King Fund.

4 flux de communication branchés sur le MessageBus :

  1. CBPublisher        — Banques Centrales → traders Division Banque Centrale (04,07,17,23,29)
                          MACRO_UPDATE quand |sentiment| ≥ 0.30 ou biais hawkish/dovish fort
  2. ExpertPublisher    — ExpertSignalClient → Division Investissement (01,05,08,13,16,20,24,25,27,28,30)
                          SIGNAL_MARCHE quand |signal composite| ≥ 0.55 pour equity_us/crypto
  3. DeskLiqBudget      — LiquidityDesk global_liquidity_score → budget_factor [0.50, 1.50]
                          SIGNAL_MARCHE avec le facteur → engine ajuste tous les trades
  4. BlackSwanAgent     — Surveille VIX (^VIX via yfinance) toutes les N ticks
                          ALERTE_CRITIQUE si VIX > 35 → engine stoppe tous les traders
                          Reset automatique si VIX redescend < 30

Usage dans engine.py :
    from divisions.interagents import get_interagent_hub
    self._hub = get_interagent_hub()
    self._hub.connect_engine(self)          # enregistre les callbacks engine
    ...
    # Dans tick() :
    if self._hub.black_swan_halt:
        ... # skip tous les traders
    ...
    # Toutes les N ticks :
    if self._tick_count % 60 == 0:
        self._hub.run_cycle_cb()
    if self._tick_count % 30 == 0:
        self._hub.run_cycle_experts()
    if self._tick_count % 20 == 0:
        self._hub.run_cycle_vix()
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # avoid circular imports

logger = logging.getLogger(__name__)

# ── Traders par groupe (IDs formatés pour le bus) ─────────────────────────────

_TRADERS_GROUPE_A: list[str] = [
    "TRD001", "TRD002", "TRD003", "TRD004", "TRD005",
    "TRD006", "TRD007", "TRD008", "TRD009", "TRD010",
]

_TRADERS_GROUPE_B: list[str] = [
    "TRD011", "TRD012", "TRD013", "TRD014", "TRD015",
    "TRD016", "TRD017", "TRD018", "TRD019", "TRD020",
]

_TRADERS_GROUPE_C: list[str] = [
    "TRD021", "TRD022", "TRD023", "TRD024", "TRD025",
    "TRD026", "TRD027", "TRD028", "TRD029", "TRD030",
]

_ALL_TRADERS: list[str] = [f"TRD{i:03d}" for i in range(1, 31)]

# Division Banque Centrale : traders 04, 07, 17, 23, 29
_TRADERS_BANQUE_CENTRALE: list[str] = [
    "TRD004", "TRD007", "TRD017", "TRD023", "TRD029",
]

# ── Seuils ────────────────────────────────────────────────────────────────────

_CB_SEUIL_INFO    = 0.30   # |sentiment| ≥ → publie info
_CB_SEUIL_WARNING = 0.50   # |sentiment| ≥ → publie warning
_CB_SEUIL_CRIT    = 0.70   # |sentiment| ≥ → publie critique

_EXPERT_SEUIL     = 0.55   # |signal composite| ≥ → publie vers investissement

_VIX_HALT         = 35.0   # VIX ≥ → HALT tous les traders
_VIX_RESET        = 30.0   # VIX ≤ → reset HALT (marché stabilisé)

_LIQ_SCORE_NEUTRE = 5.0    # score 5/10 → factor 1.00


# ─────────────────────────────────────────────────────────────────────────────
# 1. CB Publisher
# ─────────────────────────────────────────────────────────────────────────────

class CBPublisher:
    """
    Lit les sentiments de toutes les banques centrales du REGISTRY
    et publie les signaux significatifs sur le bus en ciblant
    les 5 traders Division Banque Centrale.
    """

    def __init__(self, bus) -> None:
        pass  # publisher only — pas d'abonnement

    def publish(self, bus) -> None:
        """Scanne les 20 CB et publie les signaux significatifs."""
        try:
            from divisions.banques_centrales import REGISTRY
        except Exception as e:
            logger.debug("CBPublisher: REGISTRY indisponible — %s", e)
            return

        published = 0
        for code, bank in REGISTRY.items():
            try:
                sig = bank.sentiment()
                if abs(sig) < _CB_SEUIL_INFO:
                    continue
                rate = bank.rate()
                headline = bank.latest_headline()[:120] if hasattr(bank, "latest_headline") else ""

                niveau = (
                    "critique" if abs(sig) >= _CB_SEUIL_CRIT else
                    "warning"  if abs(sig) >= _CB_SEUIL_WARNING else
                    "info"
                )
                orientation = "dovish (haussier)" if sig > 0 else "hawkish (baissier)"
                bus.publier(_make_message(
                    categorie="macro_update",
                    niveau=niveau,
                    source="banques_centrales",
                    titre=f"{code} — signal {orientation} ({sig:+.2f})",
                    contenu={
                        "code": code,
                        "sentiment": round(sig, 3),
                        "taux": rate,
                        "headline": headline,
                        "orientation": orientation,
                    },
                    entite=code,
                    traders_cibles=_TRADERS_BANQUE_CENTRALE,
                ))
                published += 1
            except Exception as e:
                logger.debug("CBPublisher %s: %s", code, e)

        if published:
            logger.info("[CBPublisher] %d signaux CB publiés → %s",
                        published, _TRADERS_BANQUE_CENTRALE)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Expert Publisher
# ─────────────────────────────────────────────────────────────────────────────

class ExpertPublisher:
    """
    Lit les signaux de l'ExpertSignalClient pour chaque symbole.
    Publie les signaux forts (|sig| ≥ 0.55) vers la Division Investissement.
    """

    # Groupe A — EU Valeurs Sous-suivies
    SYMBOLS = [
        "VPK.AS", "GTT.PA", "TEL.OL", "DNB.OL", "TTE.PA",
        "SU.PA", "AIR.PA", "DSY.PA", "BIPC", "ADC",
        # Groupe B — ETF Macro (pour signaux cross-group)
        "SPY", "QQQ", "GLD", "TLT", "XLE", "XLU",
    ]

    def publish(self, bus) -> None:
        try:
            from data.expert_signal_client import get_expert_signal_client
            client = get_expert_signal_client()
        except Exception as e:
            logger.debug("ExpertPublisher: ExpertSignalClient indisponible — %s", e)
            return

        signaux_forts = []
        for symbol in self.SYMBOLS:
            try:
                breakdown = client.get_breakdown(symbol)
                sig = breakdown.get("signal", 0.0)
                if abs(sig) < _EXPERT_SEUIL:
                    continue
                signaux_forts.append(breakdown)
                niveau = "critique" if abs(sig) >= 0.80 else "warning"
                direction = "haussier" if sig > 0 else "baissier"
                bus.publier(_make_message(
                    categorie="signal_marche",
                    niveau=niveau,
                    source="experts_sectoriels",
                    titre=f"Signal expert fort {symbol} ({sig:+.2f} — {direction})",
                    contenu={
                        "symbol":       symbol,
                        "signal":       sig,
                        "liq_signal":   breakdown.get("liq_signal"),
                        "cb_signal":    breakdown.get("cb_signal"),
                        "bertez_signal":breakdown.get("bertez_signal"),
                        "domain":       breakdown.get("domain"),
                        "direction":    direction,
                    },
                    entite=symbol,
                    traders_cibles=_TRADERS_GROUPE_A,
                    divisions_cibles=["groupe_a"],
                ))
            except Exception as e:
                logger.debug("ExpertPublisher %s: %s", symbol, e)

        if signaux_forts:
            logger.info("[ExpertPublisher] %d signaux forts → Division Investissement",
                        len(signaux_forts))


# ─────────────────────────────────────────────────────────────────────────────
# 3. Bertez Publisher — Groupe C Protecteurs Taleb
# ─────────────────────────────────────────────────────────────────────────────

class BertezPublisher:
    """
    Lit le signal AgentBertez (WTI + USD → régime STAGFLATION/REFLATION/NEUTRE)
    et publie vers le Groupe C (TRD021-030) quand le mode est défensif.
    """

    def publish(self, bus) -> None:
        try:
            from divisions.investissement.agent_bertez import get_agent_bertez
            analyse = get_agent_bertez().analyse()
        except Exception as e:
            logger.debug("BertezPublisher: AgentBertez indisponible — %s", e)
            return

        mode = analyse.get("mode", "NEUTRE")
        if mode not in ("STAGFLATION", "REFLATION", "DEFENSIF"):
            return

        niveau = "critique" if mode in ("STAGFLATION", "DEFENSIF") else "warning"
        bus.publier(_make_message(
            categorie="signal_marche",
            niveau=niveau,
            source="agent_bertez",
            titre=f"Bertez — régime {mode} → Groupe C Protecteurs",
            contenu={
                "mode":       mode,
                "wti":        analyse.get("wti"),
                "dxy":        analyse.get("dxy"),
                "conclusion": analyse.get("conclusion", ""),
            },
            entite="BERTEZ",
            traders_cibles=_TRADERS_GROUPE_C,
            divisions_cibles=["groupe_c"],
        ))
        logger.info("[BertezPublisher] mode=%s → Groupe C (%d traders)", mode, len(_TRADERS_GROUPE_C))


# ─────────────────────────────────────────────────────────────────────────────
# 4. Desk Liquidité Budget Adjuster
# ─────────────────────────────────────────────────────────────────────────────

class DeskLiqBudget:
    """
    Lit le global_liquidity_score du LiquidityDesk (0-10) et calcule
    un budget_factor [0.50, 1.50] que l'engine applique sur tous les trades.

    score=0  → factor=0.50  (marché très illiquide — taille moitié)
    score=5  → factor=1.00  (neutre)
    score=10 → factor=1.50  (très liquide — taille amplifiée)
    """

    def publish_and_get_factor(self, bus) -> float:
        try:
            from divisions.middle_office import get_liquidity_desk
            score = get_liquidity_desk().get_score()
        except Exception as e:
            logger.debug("DeskLiqBudget: score indisponible — %s", e)
            return 1.0

        if score is None:
            return 1.0

        # Linéaire : score 0→0.50, 5→1.00, 10→1.50
        factor = round(0.50 + (score / 10.0), 3)
        factor = max(0.50, min(1.50, factor))

        niveau = "warning" if factor < 0.70 or factor > 1.40 else "info"
        bus.publier(_make_message(
            categorie="signal_marche",
            niveau=niveau,
            source="desk_liquidite",
            titre=f"Budget ajustement liquidité — factor={factor:.2f} (score={score:.1f}/10)",
            contenu={
                "global_liquidity_score": score,
                "budget_factor": factor,
                "regime": _score_to_regime(score),
            },
            entite="GLOBAL_LIQUIDITY",
            divisions_cibles=["engine", "investissement", "middle_office"],
        ))
        logger.info("[DeskLiqBudget] score=%.1f/10 → budget_factor=%.2f", score, factor)
        return factor


def _score_to_regime(score: float) -> str:
    if score >= 7.5:
        return "HAUTE_LIQUIDITE"
    if score >= 5.0:
        return "NORMALE"
    if score >= 2.5:
        return "BASSE_LIQUIDITE"
    return "CRISE_LIQUIDITE"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Black Swan Agent (VIX)
# ─────────────────────────────────────────────────────────────────────────────

class BlackSwanAgent:
    """
    Surveille le VIX (^VIX) via yfinance.
    VIX ≥ 35 → ALERTE_CRITIQUE → engine._black_swan_halt = True (stoppe tous les traders).
    VIX ≤ 30 → reset automatique → reprise des trades.
    """

    def __init__(self) -> None:
        self._last_vix: float | None = None
        self._halted = False

    def check_and_publish(self, bus) -> bool:
        """Retourne True si HALT actif après la vérification."""
        vix = self._fetch_vix()
        if vix is None:
            return self._halted   # garde l'état précédent si fetch échoue

        self._last_vix = vix

        if not self._halted and vix >= _VIX_HALT:
            self._halted = True
            logger.critical("[BlackSwan] VIX=%.2f ≥ %.0f — HALT GÉNÉRAL", vix, _VIX_HALT)
            bus.publier(_make_message(
                categorie="alerte_critique",
                niveau="critique",
                source="black_swan",
                titre=f"BLACK SWAN — VIX={vix:.2f} ≥ {_VIX_HALT:.0f} — HALT TRADING",
                contenu={
                    "vix": vix,
                    "seuil_halt": _VIX_HALT,
                    "seuil_reset": _VIX_RESET,
                    "action": "HALT_ALL_TRADERS",
                    "timestamp": datetime.utcnow().isoformat(),
                },
                entite="VIX",
                traders_cibles=_ALL_TRADERS,
                divisions_cibles=["engine", "investissement", "middle_office",
                                  "banques_centrales", "experts_sectoriels"],
            ))

        elif self._halted and vix <= _VIX_RESET:
            self._halted = False
            logger.warning("[BlackSwan] VIX=%.2f ≤ %.0f — REPRISE TRADING", vix, _VIX_RESET)
            bus.publier(_make_message(
                categorie="alerte_warning",
                niveau="warning",
                source="black_swan",
                titre=f"BLACK SWAN LEVÉ — VIX={vix:.2f} ≤ {_VIX_RESET:.0f} — reprise",
                contenu={
                    "vix": vix,
                    "action": "RESUME_TRADING",
                    "timestamp": datetime.utcnow().isoformat(),
                },
                entite="VIX",
                traders_cibles=_ALL_TRADERS,
            ))

        elif self._halted:
            # VIX toujours > 30 mais < 35 — on logue sans republier
            logger.warning("[BlackSwan] VIX=%.2f — HALT maintenu (seuil reset=%.0f)",
                           vix, _VIX_RESET)

        return self._halted

    def _fetch_vix(self) -> float | None:
        try:
            import yfinance as yf
            ticker = yf.Ticker("^VIX")
            hist = ticker.history(period="1d", interval="1m")
            if hist.empty:
                return None
            return float(hist["Close"].iloc[-1])
        except Exception as e:
            logger.debug("[BlackSwan] VIX fetch error: %s", e)
            return None

    @property
    def last_vix(self) -> float | None:
        return self._last_vix

    @property
    def halted(self) -> bool:
        return self._halted


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrateur principal
# ─────────────────────────────────────────────────────────────────────────────

class InterAgentHub:
    """
    Orchestre les 4 flux de communication inter-agents.
    L'engine l'initialise au démarrage et l'appelle à des intervalles réguliers.
    """

    def __init__(self) -> None:
        from divisions.bus import get_bus
        self._bus          = get_bus()
        self._cb_pub       = CBPublisher(self._bus)
        self._expert_pub   = ExpertPublisher()
        self._bertez_pub   = BertezPublisher()
        self._liq_budget   = DeskLiqBudget()
        self._black_swan   = BlackSwanAgent()

        self._lock               = threading.Lock()
        self._black_swan_halt    = False
        self._liq_budget_factor  = 1.0
        self._cb_last_signals:   dict[str, dict] = {}    # code → {sentiment, ...}
        self._expert_last_sigs:  dict[str, float] = {}   # symbol → signal

        # L'engine s'abonne aux ALERTE_CRITIQUE pour réagir au Black Swan
        self._bus.souscrire(
            division="engine",
            categories=[
                _cat("alerte_critique"),
                _cat("alerte_warning"),
                _cat("signal_marche"),
                _cat("macro_update"),
            ],
            callback=self._on_bus_message,
            niveaux=["info", "warning", "critique"],
        )
        logger.info("[InterAgentHub] Initialisé — 5 flux actifs (+ BertezPublisher)")

    # ── Callbacks bus ─────────────────────────────────────────────────────────

    def _on_bus_message(self, msg) -> None:
        source = msg.source
        contenu = msg.contenu

        if source == "black_swan":
            action = contenu.get("action")
            if action == "HALT_ALL_TRADERS":
                with self._lock:
                    self._black_swan_halt = True
                logger.critical("[Hub] HALT activé — Black Swan VIX=%.2f",
                                contenu.get("vix", 0))
            elif action == "RESUME_TRADING":
                with self._lock:
                    self._black_swan_halt = False
                logger.warning("[Hub] HALT levé — VIX=%.2f", contenu.get("vix", 0))

        elif source == "desk_liquidite" and "budget_factor" in contenu:
            factor = contenu["budget_factor"]
            with self._lock:
                self._liq_budget_factor = factor
            logger.info("[Hub] Liq budget factor → %.2f", factor)

        elif source == "banques_centrales":
            code = contenu.get("code", "?")
            sig  = contenu.get("sentiment", 0.0)
            with self._lock:
                self._cb_last_signals[code] = contenu
            logger.debug("[Hub] CB signal reçu %s=%.3f", code, sig)

        elif source == "experts_sectoriels":
            symbol = contenu.get("symbol", "?")
            sig    = contenu.get("signal", 0.0)
            with self._lock:
                self._expert_last_sigs[symbol] = sig
            logger.debug("[Hub] Expert signal reçu %s=%.3f", symbol, sig)

    # ── Propriétés lues par l'engine ─────────────────────────────────────────

    @property
    def black_swan_halt(self) -> bool:
        with self._lock:
            return self._black_swan_halt

    @property
    def last_vix(self) -> float | None:
        return self._black_swan.last_vix

    @property
    def liq_budget_factor(self) -> float:
        with self._lock:
            return self._liq_budget_factor

    def get_cb_signal(self, cb_code: str) -> float:
        """Sentiment de la CB (code FED, BCE, …) depuis le dernier cycle."""
        with self._lock:
            return self._cb_last_signals.get(cb_code, {}).get("sentiment", 0.0)

    def get_expert_signal(self, symbol: str) -> float:
        """Signal expert pour un symbole depuis le dernier cycle."""
        with self._lock:
            return self._expert_last_sigs.get(symbol, 0.0)

    # ── Cycles appelés par l'engine dans tick() ───────────────────────────────

    def run_cycle_cb(self) -> None:
        """Flux 1 — CB → traders Division Banque Centrale. Appeler toutes les 60 ticks."""
        threading.Thread(
            target=self._cb_pub.publish,
            args=(self._bus,),
            daemon=True,
            name="hub-cb",
        ).start()

    def run_cycle_experts(self) -> None:
        """Flux 2 — Experts → Division Investissement. Appeler toutes les 30 ticks."""
        threading.Thread(
            target=self._expert_pub.publish,
            args=(self._bus,),
            daemon=True,
            name="hub-experts",
        ).start()

    def run_cycle_liq(self) -> None:
        """Flux 3 — Desk Liquidité → budgets. Appeler toutes les 15 ticks."""
        def _run():
            self._liq_budget.publish_and_get_factor(self._bus)
            # Le callback _on_bus_message mettra à jour self._liq_budget_factor
        threading.Thread(target=_run, daemon=True, name="hub-liq").start()

    def run_cycle_bertez(self) -> None:
        """Flux 5 — Bertez → Groupe C Protecteurs. Appeler toutes les 30 ticks."""
        threading.Thread(
            target=self._bertez_pub.publish,
            args=(self._bus,),
            daemon=True,
            name="hub-bertez",
        ).start()

    def run_cycle_vix(self) -> None:
        """Flux 5 (ex-4) — VIX Black Swan check. Appeler toutes les 20 ticks."""
        threading.Thread(
            target=self._black_swan.check_and_publish,
            args=(self._bus,),
            daemon=True,
            name="hub-vix",
        ).start()

    # ── État pour l'API ───────────────────────────────────────────────────────

    def get_etat(self) -> dict:
        with self._lock:
            halt    = self._black_swan_halt
            factor  = self._liq_budget_factor
            cb_sigs = dict(self._cb_last_signals)
            ex_sigs = dict(self._expert_last_sigs)

        return {
            "black_swan": {
                "halt":    halt,
                "vix":     self._black_swan.last_vix,
                "seuil":   _VIX_HALT,
                "reset":   _VIX_RESET,
            },
            "desk_liquidite": {
                "budget_factor": factor,
                "regime":        _score_to_regime((factor - 0.5) * 10),
            },
            "banques_centrales": {
                "nb_signaux": len(cb_sigs),
                "signaux":    {k: v.get("sentiment", 0) for k, v in cb_sigs.items()},
            },
            "experts_sectoriels": {
                "nb_signaux": len(ex_sigs),
                "signaux":    ex_sigs,
            },
            "bus": self._bus.etat(),
            "timestamp": datetime.utcnow().isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _cat(name: str):
    from divisions.bus.message_bus import CategorieMessage
    return CategorieMessage(name)


def _make_message(
    categorie: str,
    niveau: str,
    source: str,
    titre: str,
    contenu: dict,
    entite: str = "",
    traders_cibles: list[str] | None = None,
    divisions_cibles: list[str] | None = None,
):
    from divisions.bus.message_bus import BusMessage, CategorieMessage
    return BusMessage(
        categorie=CategorieMessage(categorie),
        niveau=niveau,
        source=source,
        titre=titre,
        contenu=contenu,
        entite=entite,
        traders_cibles=traders_cibles or [],
        divisions_cibles=divisions_cibles or [],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_hub_instance: InterAgentHub | None = None
_hub_lock = threading.Lock()


def get_interagent_hub() -> InterAgentHub:
    global _hub_instance
    if _hub_instance is None:
        with _hub_lock:
            if _hub_instance is None:
                _hub_instance = InterAgentHub()
    return _hub_instance
