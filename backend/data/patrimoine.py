"""
Patrimoine personnel — stockage JSON + calculs de projection + analyse fiscale.

Actifs par défaut :
  Cash        450 €
  Or          570 €
  Stellantis   62 €

Persistance : data/patrimoine/patrimoine.json (créé au premier accès).
"""
from __future__ import annotations
import json
import math
import threading
from datetime import datetime, date
from pathlib import Path

_DATA_DIR  = Path(__file__).parent.parent.parent / "data" / "patrimoine"
_DATA_FILE = _DATA_DIR / "patrimoine.json"
_lock      = threading.Lock()

_DEFAULTS: dict = {
    "actifs": [
        {"id": "cash",       "nom": "Cash",               "valeur_eur": 450.0, "categorie": "liquidites",  "couleur": "#00e5a0"},
        {"id": "or",         "nom": "Or physique",        "valeur_eur": 570.0, "categorie": "metaux",      "couleur": "#ffd700"},
        {"id": "epargne_dzd","nom": "Épargne Dinars DZD", "valeur_eur": 17000.0,"categorie": "epargne",    "couleur": "#b44cff"},
        {"id": "pea",        "nom": "PEA",                "valeur_eur": 0.0,   "categorie": "pea",         "couleur": "#ff6b35"},
        {"id": "immo",       "nom": "Immobilier",         "valeur_eur": 0.0,   "categorie": "immobilier",  "couleur": "#ff4488",
         "meta": {"type": "residence_principale", "annees_detention": 0, "credit_restant": 0.0}},
    ],
    "apports":  [],          # [{date, montant, note}, ...]
    "config": {
        "taux_annuel":   0.10,
        "age_actuel":    35,
        "age_retraite":  56,
        "apport_mensuel": 500.0,
        "annee_base":    2026,
    },
}

# ── I/O ──────────────────────────────────────────────────────────────────────

def _load() -> dict:
    with _lock:
        if _DATA_FILE.exists():
            try:
                return json.loads(_DATA_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return json.loads(json.dumps(_DEFAULTS))   # deep copy


def _save(data: dict) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        _DATA_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# ── Calculs ───────────────────────────────────────────────────────────────────

def _total_eur(actifs: list[dict]) -> float:
    return round(sum(a["valeur_eur"] for a in actifs), 2)


def _total_investissable(actifs: list[dict]) -> float:
    """Somme uniquement les actifs investissables (investissable != False)."""
    return round(sum(a["valeur_eur"] for a in actifs if a.get("investissable", True)), 2)


def _projection(
    patrimoine: float,
    apport_mensuel: float,
    taux_annuel: float,
    annees: int,
) -> list[dict]:
    """
    Projection année par année.
    FV(t) = PV × (1+r)^t + PMT_annuel × ((1+r)^t − 1) / r
    """
    r   = taux_annuel
    pmt = apport_mensuel * 12
    pts = []
    for t in range(annees + 1):
        growth  = patrimoine * ((1 + r) ** t)
        contrib = pmt * (((1 + r) ** t - 1) / r) if r > 0 and t > 0 else 0
        pts.append({
            "annee": _DEFAULTS["config"]["annee_base"] + t,
            "valeur": round(growth + contrib, 2),
            "croissance": round(growth, 2),
            "apports_cumules": round(contrib, 2),
        })
    return pts


def _fiscalite(actifs: list[dict]) -> dict:
    """Analyse fiscale pour tous les actifs présents en France."""
    actifs_map = {a["id"]: a for a in actifs}

    or_val  = actifs_map.get("or",  {}).get("valeur_eur", 0)
    st_val  = actifs_map.get("stellantis", {}).get("valeur_eur", 0)
    pea_val = actifs_map.get("pea", {}).get("valeur_eur", 0)
    immo    = actifs_map.get("immo", {})
    immo_val    = immo.get("valeur_eur", 0)
    immo_meta   = immo.get("meta", {})
    immo_type   = immo_meta.get("type", "residence_principale")
    immo_annees = immo_meta.get("annees_detention", 0)
    immo_credit = immo_meta.get("credit_restant", 0.0)
    immo_net    = max(0.0, immo_val - immo_credit)

    # ── Or ────────────────────────────────────────────────────────────
    or_taxe_forfaitaire     = round(or_val * 0.115, 2)
    or_abatt_pct            = min(100.0, 5.0 * 21)
    or_exonere              = or_abatt_pct >= 100

    # ── Stellantis ────────────────────────────────────────────────────
    st_div   = round(st_val * 0.04, 2)
    st_pfu   = round(st_div * 0.30, 2)
    st_pfu_pea = round(st_div * 0.172, 2)   # dans PEA après 5 ans : seulement PS

    # ── PEA ──────────────────────────────────────────────────────────
    pea_plafond   = 150_000.0
    pea_dispo     = max(0.0, pea_plafond - pea_val)
    pea_st_annuel_sans = round(st_div * 0.30, 2)
    pea_st_annuel_avec = round(st_div * 0.172, 2)
    pea_economie_an    = round(pea_st_annuel_sans - pea_st_annuel_avec, 2)

    # ── Immobilier — abattements PV ──────────────────────────────────
    def _abatt_ir(n: int) -> float:
        """Abattement IR sur PV immo : 6%/an de 6 à 21 ans, 4% à 22 ans."""
        if n < 6:  return 0.0
        if n < 22: return min(96.0, 6.0 * (n - 5))
        if n == 22: return 100.0
        return 100.0

    def _abatt_ps(n: int) -> float:
        """Abattement PS sur PV immo : 1.65%/an 6-21, 1.6% à 22, 9%/an 23-30."""
        if n < 6:  return 0.0
        if n < 22: return min(99.0, 1.65 * (n - 5))
        if n == 22: return (1.65 * 16) + 1.60
        if n <= 30: return min(100.0, (1.65 * 16) + 1.60 + 9.0 * (n - 22))
        return 100.0

    ab_ir = _abatt_ir(immo_annees)
    ab_ps = _abatt_ps(immo_annees)
    ir_net_pct = max(0.0, round(19.0 * (1 - ab_ir / 100), 2))
    ps_net_pct = max(0.0, round(17.2 * (1 - ab_ps / 100), 2))
    immo_taux_pv = round(ir_net_pct + ps_net_pct, 2)

    fsc_fra_01: dict = {
        "regime":    "Prélèvement Forfaitaire Unique (PFU) — Flat Tax 30%",
        "taux":      "12.8% IR + 17.2% PS = 30% total",
        "reference": "Art. 200 A CGI — Loi de finances 2018",
        "or": {
            "actif": f"Or physique ({or_val:.0f}€)",
            "option_A": {
                "nom":    "Taxe forfaitaire métaux précieux",
                "taux":   "11.5% sur le prix de cession (hors PV)",
                "impot":  or_taxe_forfaitaire,
                "detail": "Art. 150 VI CGI — s'applique à la vente brute",
            },
            "option_B": {
                "nom":               "Régime des PV (si justificatif d'achat)",
                "taux":              "36.2% sur la PV nette — abattement 5%/an après 2 ans",
                "abattement_acquis": f"{or_abatt_pct:.0f}%",
                "exonere":           or_exonere,
                "detail":            "Art. 150 UA CGI — exonération totale après 22 ans de détention",
            },
            "conseil": "Régime PV préférable si détenu > 22 ans (exonération totale)",
        },
        "cash": {
            "actif":  f"Cash ({actifs_map.get('cash', {}).get('valeur_eur', 0):.0f}€)",
            "detail": "Pas de fiscalité sur les liquidités. Livret A / LEP : exonéré d'IR",
        },
    }

    pea_fisc = {
        "valeur":       pea_val,
        "plafond":      pea_plafond,
        "dispo":        pea_dispo,
        "avant_5ans":   "Retrait = clôture du PEA + PFU 30% sur PV",
        "apres_5ans":   "PV et dividendes exonérés d'IR — seulement 17.2% PS",
        "economie_stellantis_an": pea_economie_an,
        "detail_economie": (
            f"Stellantis dans PEA → {st_pfu_pea}€ PS/an vs {st_pfu}€ PFU en CTO"
            f" = économie {pea_economie_an}€/an"
        ),
        "plafond_pea_pme": 75_000.0,
        "conseil": [
            "Ouvrir le PEA dès maintenant pour faire courir le délai de 5 ans",
            "Y loger en priorité Stellantis (STLAM) et les actions européennes",
            "Après 5 ans : rentes viagères issues du PEA exonérées d'IR",
            f"Capacité restante : {pea_dispo:,.0f}€ (plafond 150 000€)",
        ],
        "reference": "Art. 163 quinquies D CGI — Plan d'Épargne en Actions",
    }

    immo_fisc = {
        "valeur":          immo_val,
        "credit_restant":  immo_credit,
        "valeur_nette":    immo_net,
        "type":            immo_type,
        "annees_detention": immo_annees,
        "residence_principale": {
            "regime":  "Exonération totale de plus-value",
            "detail":  "Art. 150 U II CGI — RP exonérée à 100% (IR + PS)",
            "conseil": "Aucune fiscalité sur la PV à la vente de la résidence principale",
        },
        "locatif": {
            "taux_pv_applicable": immo_taux_pv,
            "abattement_ir_acquis": f"{ab_ir:.1f}%",
            "abattement_ps_acquis": f"{ab_ps:.1f}%",
            "ir_net_pct":  ir_net_pct,
            "ps_net_pct":  ps_net_pct,
            "exonere_ir":  ab_ir >= 100,
            "exonere_ps":  ab_ps >= 100,
            "detail_abattements": (
                "IR : 6%/an de la 6e à 21e année, 4% à 22 ans → exonération IR après 22 ans. "
                "PS : 1.65%/an de 6 à 21 ans, 9%/an de 23 à 30 ans → exonération PS après 30 ans"
            ),
            "micro_foncier": {
                "seuil":      "< 15 000€ de revenus locatifs bruts/an",
                "abattement": "30% forfaitaire sur les loyers",
                "detail":     "Régime micro-foncier : simple, mais pas de déduction des charges réelles",
            },
            "conseil": (
                "Si > 22 ans de détention : vendre sans IR. "
                "Si locatif avec travaux importants : opter pour le régime réel (déductions charges)."
            ),
        },
        "ifi": {
            "seuil": "IFI dû si patrimoine immobilier net > 1 300 000€",
            "detail": "Impôt sur la Fortune Immobilière — taux progressif de 0.5% à 1.5%",
        },
        "reference": "Art. 150 U à 150 VH CGI — Plus-values immobilières",
    }

    if st_val > 0:
        fsc_fra_01["stellantis"] = {
            "actif":              f"Actions Stellantis ({st_val:.0f}€)",
            "dividendes_estimes": st_div,
            "pfu_annuel":         st_pfu,
            "pfu_pea_annuel":     st_pfu_pea,
            "detail":             f"Dividende STLAM ~4%/an → PFU CTO : {st_pfu}€/an · dans PEA : {st_pfu_pea}€/an",
            "conseil":            "Loger dans le PEA — économie de 12.8% IR sur dividendes et PV",
        }

    return {"fsc_fra_01": fsc_fra_01, "pea": pea_fisc, "immo": immo_fisc}


# ── API publique ──────────────────────────────────────────────────────────────

def get_patrimoine() -> dict:
    data  = _load()
    cfg   = data.get("config", _DEFAULTS["config"])
    actifs = data.get("actifs", _DEFAULTS["actifs"])
    apports = data.get("apports", [])

    total     = _total_eur(actifs)
    total_inv = _total_investissable(actifs)
    # Actifs hors fonds (investissable = false)
    reserves  = [a for a in actifs if not a.get("investissable", True)]

    annees_horizon = cfg["age_retraite"] - cfg["age_actuel"]

    # Apport mensuel effectif = dernier apport mensuel ou valeur config
    apport_mensuel = cfg.get("apport_mensuel", 500.0)
    if apports:
        recents = sorted(apports, key=lambda x: x.get("date", ""))[-3:]
        apport_mensuel = sum(a.get("montant", 0) for a in recents) / len(recents)

    # Projection basée uniquement sur la base investissable
    projection = _projection(total_inv, apport_mensuel, cfg["taux_annuel"], max(0, annees_horizon))

    return {
        "actifs":                   actifs,
        "total_eur":                total,
        "total_investissable":      total_inv,
        "reserves":                 reserves,
        "apports":                  list(reversed(sorted(apports, key=lambda x: x.get("date", "")))),
        "apports_cumules_12m":      _apports_12m(apports),
        "config":                   cfg,
        "projection":               projection,
        "valeur_retraite":          projection[-1]["valeur"] if projection else 0,
        "apport_mensuel_effectif":  round(apport_mensuel, 2),
        "fiscalite":                _fiscalite(actifs),
        "timestamp":                datetime.utcnow().isoformat(),
    }


def update_actif(actif_id: str, valeur_eur: float) -> dict | None:
    """Met à jour la valeur d'un actif existant."""
    data = _load()
    for a in data.get("actifs", []):
        if a["id"] == actif_id:
            a["valeur_eur"] = round(max(0.0, valeur_eur), 2)
            _save(data)
            return a
    return None


def delete_actif(actif_id: str) -> bool:
    """Supprime un actif de la liste."""
    data = _load()
    actifs = data.get("actifs", [])
    new_actifs = [a for a in actifs if a["id"] != actif_id]
    if len(new_actifs) < len(actifs):
        data["actifs"] = new_actifs
        _save(data)
        return True
    return False


def add_apport(montant: float, note: str = "") -> dict:
    if montant <= 0:
        raise ValueError("Montant doit être positif")
    data = _load()
    apport = {
        "id":      _gen_id(),
        "date":    date.today().isoformat(),
        "montant": round(montant, 2),
        "note":    note[:200],
    }
    data.setdefault("apports", []).append(apport)
    _save(data)
    return apport


def update_config(taux: float | None, age: int | None, retraite: int | None,
                  apport_mensuel: float | None) -> dict:
    data = _load()
    cfg  = data.setdefault("config", dict(_DEFAULTS["config"]))
    if taux          is not None: cfg["taux_annuel"]    = max(0.01, min(0.30, taux))
    if age           is not None: cfg["age_actuel"]     = max(18, min(75, age))
    if retraite      is not None: cfg["age_retraite"]   = max(cfg.get("age_actuel", 18) + 1, min(80, retraite))
    if apport_mensuel is not None: cfg["apport_mensuel"] = max(0, apport_mensuel)
    _save(data)
    return cfg


# ── Helpers ───────────────────────────────────────────────────────────────────

def _apports_12m(apports: list[dict]) -> float:
    cutoff = str(date.today().replace(year=date.today().year - 1))
    return round(sum(a.get("montant", 0) for a in apports if a.get("date", "") >= cutoff), 2)


def _gen_id() -> str:
    import uuid
    return str(uuid.uuid4())[:8]
