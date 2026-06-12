"""
Suivi PRU (Prix de Revient Unitaire) des positions réelles.

PRU = moyenne pondérée des achats.
PV/MV latente = (prix_actuel - PRU) × quantité.
Alerte Telegram si objectif ou stop_loss atteint (1 alerte/ticker/jour).
"""
from __future__ import annotations
import json
import threading
import uuid
from datetime import date, datetime
from pathlib import Path

_DATA_DIR  = Path(__file__).parent.parent.parent / "data" / "patrimoine"
_DATA_FILE = _DATA_DIR / "suivi_pru.json"
_lock      = threading.Lock()

_DEFAULTS: dict = {
    "positions": {},      # ticker → {ticker, nom, quantite, pru, objectif, stop_loss, note}
    "transactions": [],   # [{id, ticker, date, type, quantite, prix_unitaire, pru_reference, compte, note}]
    "alertes_envoyees": {},  # ticker → {objectif: date_str, stop_loss: date_str}
}


# ── I/O ──────────────────────────────────────────────────────────────────────

def _load() -> dict:
    with _lock:
        if _DATA_FILE.exists():
            try:
                return json.loads(_DATA_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return json.loads(json.dumps(_DEFAULTS))


def _save(data: dict) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        _DATA_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# ── PRU calculation ───────────────────────────────────────────────────────────

def _recalculer_pru(ticker: str, transactions: list[dict]) -> tuple[float, float]:
    """Retourne (pru, quantite) en rejouant toutes les transactions d'un ticker."""
    txs = sorted(
        [t for t in transactions if t["ticker"] == ticker],
        key=lambda t: t.get("date", ""),
    )
    qty = 0.0
    pru = 0.0
    for tx in txs:
        q = tx.get("quantite", 0)
        p = tx.get("prix_unitaire", 0)
        if tx["type"] == "achat":
            pru = (qty * pru + q * p) / (qty + q) if (qty + q) > 0 else p
            qty += q
        elif tx["type"] == "vente":
            qty = max(0.0, qty - q)
            # PRU inchangé à la vente
    return round(pru, 4), round(qty, 6)


# ── Prix actuels ─────────────────────────────────────────────────────────────

def _prix_actuels(tickers: list[str]) -> dict[str, float]:
    """Retourne {ticker: prix} via yfinance."""
    prix = {}
    if not tickers:
        return prix
    try:
        import yfinance as yf
        data = yf.download(tickers, period="1d", auto_adjust=True, progress=False)
        if hasattr(data, "columns") and hasattr(data.columns, "get_level_values"):
            # Multi-ticker
            for ticker in tickers:
                try:
                    close = data["Close"][ticker].dropna()
                    if not close.empty:
                        prix[ticker] = round(float(close.iloc[-1]), 4)
                except Exception:
                    pass
        else:
            # Single ticker
            if tickers and not data.empty:
                close = data["Close"].dropna()
                if not close.empty:
                    prix[tickers[0]] = round(float(close.iloc[-1]), 4)
    except Exception:
        pass
    return prix


# ── API publique ──────────────────────────────────────────────────────────────

def get_suivi_pru() -> dict:
    """Retourne l'état complet avec PV/MV latentes calculées."""
    data = _load()
    positions = data.get("positions", {})
    transactions = data.get("transactions", [])

    # Recalcule PRU/quantite depuis les transactions (source of truth)
    for ticker in list(positions.keys()):
        pru, qty = _recalculer_pru(ticker, transactions)
        positions[ticker]["pru"] = pru
        positions[ticker]["quantite"] = qty
        if qty <= 0:
            positions[ticker]["quantite"] = 0.0

    # Prix actuels
    tickers_actifs = [t for t, p in positions.items() if p.get("quantite", 0) > 0]
    prix = _prix_actuels(tickers_actifs)

    for ticker, pos in positions.items():
        qty = pos.get("quantite", 0)
        pru = pos.get("pru", 0)
        prix_actuel = prix.get(ticker)
        pos["prix_actuel"] = prix_actuel
        if prix_actuel and qty > 0:
            pos["pv_latente"] = round((prix_actuel - pru) * qty, 2)
            pos["pv_pct"]     = round((prix_actuel / pru - 1) * 100, 2) if pru > 0 else 0
        else:
            pos["pv_latente"] = None
            pos["pv_pct"]     = None

    return {
        "positions":    {t: p for t, p in positions.items() if p.get("quantite", 0) > 0},
        "transactions": list(reversed(transactions[-50:])),
        "timestamp":    datetime.utcnow().isoformat(),
    }


def ajouter_transaction(
    ticker: str,
    type_tx: str,       # "achat" | "vente"
    quantite: float,
    prix_unitaire: float,
    compte: str = "cto",
    note: str = "",
    date_tx: str | None = None,
) -> dict:
    """Enregistre un achat ou une vente et met à jour la position."""
    if type_tx not in ("achat", "vente"):
        raise ValueError("type doit être 'achat' ou 'vente'")
    if quantite <= 0 or prix_unitaire <= 0:
        raise ValueError("quantite et prix_unitaire doivent être positifs")

    data = _load()
    transactions = data.setdefault("transactions", [])
    positions    = data.setdefault("positions", {})

    # PRU de référence avant la transaction (pour calcul PV réalisée à la vente)
    old_pru, old_qty = _recalculer_pru(ticker, transactions)

    tx = {
        "id":            str(uuid.uuid4())[:8],
        "ticker":        ticker.upper(),
        "date":          date_tx or date.today().isoformat(),
        "type":          type_tx,
        "quantite":      round(quantite, 6),
        "prix_unitaire": round(prix_unitaire, 4),
        "pru_reference": old_pru,   # PRU avant la vente (pour calcul PV fiscale)
        "pv_realisee":   round((prix_unitaire - old_pru) * quantite, 2) if type_tx == "vente" else None,
        "compte":        compte,
        "note":          note[:200],
    }
    transactions.append(tx)

    # Synchronise la position
    new_pru, new_qty = _recalculer_pru(ticker.upper(), transactions)
    if ticker.upper() not in positions:
        positions[ticker.upper()] = {
            "ticker":    ticker.upper(),
            "nom":       ticker.upper(),
            "objectif":  None,
            "stop_loss": None,
            "note":      note,
        }
    positions[ticker.upper()]["pru"]      = new_pru
    positions[ticker.upper()]["quantite"] = new_qty

    _save(data)
    return tx


def configurer_position(
    ticker: str,
    nom: str | None = None,
    objectif: float | None = None,
    stop_loss: float | None = None,
    note: str | None = None,
) -> dict:
    """Met à jour les paramètres d'alerte d'une position."""
    data = _load()
    positions = data.setdefault("positions", {})
    t = ticker.upper()
    if t not in positions:
        positions[t] = {"ticker": t, "nom": t, "quantite": 0, "pru": 0}

    if nom       is not None: positions[t]["nom"]       = nom
    if objectif  is not None: positions[t]["objectif"]  = objectif
    if stop_loss is not None: positions[t]["stop_loss"] = stop_loss
    if note      is not None: positions[t]["note"]      = note[:200]

    _save(data)
    return positions[t]


def supprimer_position(ticker: str) -> bool:
    """Supprime la position et ses transactions (soft: garde l'historique dans transactions)."""
    data = _load()
    t = ticker.upper()
    if t in data.get("positions", {}):
        del data["positions"][t]
        _save(data)
        return True
    return False


def verifier_alertes() -> list[dict]:
    """Vérifie objectifs et stop-loss. Envoie Telegram si atteint (1x/jour/ticker/type)."""
    data = _load()
    positions    = data.get("positions", {})
    alertes_sent = data.setdefault("alertes_envoyees", {})
    today        = date.today().isoformat()

    tickers = [t for t, p in positions.items() if p.get("quantite", 0) > 0
               and (p.get("objectif") or p.get("stop_loss"))]
    if not tickers:
        return []

    prix = _prix_actuels(tickers)
    alertes_declenchees = []

    for ticker, pos in positions.items():
        if pos.get("quantite", 0) <= 0:
            continue
        prix_actuel = prix.get(ticker)
        if not prix_actuel:
            continue

        sent = alertes_sent.setdefault(ticker, {})
        pru  = pos.get("pru", 0)
        nom  = pos.get("nom", ticker)
        qty  = pos.get("quantite", 0)
        pv   = round((prix_actuel - pru) * qty, 2)
        pct  = round((prix_actuel / pru - 1) * 100, 2) if pru > 0 else 0

        # Objectif
        objectif = pos.get("objectif")
        if objectif and prix_actuel >= objectif and sent.get("objectif") != today:
            sent["objectif"] = today
            alertes_declenchees.append({"ticker": ticker, "type": "objectif", "prix": prix_actuel, "objectif": objectif})
            _send_alerte_telegram(
                f"🎯 <b>OBJECTIF ATTEINT — {nom} ({ticker})</b>\n"
                f"Prix actuel : {prix_actuel:.3f} ≥ Objectif : {objectif:.3f}\n"
                f"PV latente : {pv:+.2f}€ ({pct:+.1f}%) | Qté : {qty}"
            )

        # Stop-loss
        stop_loss = pos.get("stop_loss")
        if stop_loss and prix_actuel <= stop_loss and sent.get("stop_loss") != today:
            sent["stop_loss"] = today
            alertes_declenchees.append({"ticker": ticker, "type": "stop_loss", "prix": prix_actuel, "stop_loss": stop_loss})
            _send_alerte_telegram(
                f"🛑 <b>STOP LOSS ATTEINT — {nom} ({ticker})</b>\n"
                f"Prix actuel : {prix_actuel:.3f} ≤ Stop : {stop_loss:.3f}\n"
                f"MV latente : {pv:+.2f}€ ({pct:+.1f}%) | Qté : {qty}"
            )

    if alertes_declenchees:
        _save(data)

    return alertes_declenchees


def _send_alerte_telegram(msg: str) -> None:
    try:
        from divisions.gerant_delegue.notifier import alerte
        alerte(msg)
    except Exception:
        try:
            from divisions.gerant_delegue.notifier import send
            send(msg)
        except Exception:
            pass
