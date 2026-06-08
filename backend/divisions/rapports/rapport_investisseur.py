"""Rapport PDF investisseur — généré chaque lundi 09:00 (Europe/Paris)."""
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Dossier de sortie : king-fund/rapports/investisseur/
_RAPPORTS_DIR = Path(__file__).resolve().parents[3] / "rapports" / "investisseur"


def generer_rapport(engine) -> str:
    """
    Génère le rapport hebdomadaire. Retourne le chemin absolu du fichier créé.
    Essaie de produire un PDF (fpdf2) ; repli JSON si fpdf2 est absent.
    """
    _RAPPORTS_DIR.mkdir(parents=True, exist_ok=True)
    semaine = datetime.now().strftime("W%W-%Y")

    try:
        from fpdf import FPDF
        chemin = _RAPPORTS_DIR / f"rapport_{semaine}.pdf"
        _generer_pdf(chemin, engine)
        fmt = "PDF"
    except ImportError:
        chemin = _RAPPORTS_DIR / f"rapport_{semaine}.json"
        _generer_json(chemin, engine)
        fmt = "JSON"

    logger.info("[RAPPORT %s] ✓ Généré : %s", fmt, chemin)
    return str(chemin)


# ---------------------------------------------------------------------------
# PDF — fpdf2
# ---------------------------------------------------------------------------

def _generer_pdf(chemin: Path, engine) -> None:
    from fpdf import FPDF
    from config import STARTING_CAPITAL, TARGET_CAPITAL, BATTLE_DAYS

    state       = engine.get_state()
    post_market = engine.get_post_market()
    board       = state.get("leaderboard", [])
    battle_day  = state.get("battle_day", 0)
    ts          = datetime.now().strftime("%d/%m/%Y %H:%M")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # ── En-tête ──────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "KING FUND — Rapport Investisseur", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Généré le {ts} | Semaine {datetime.now().strftime('W%W-%Y')} | Jour de bataille J{battle_day}/{BATTLE_DAYS}", ln=True, align="C")
    pdf.ln(6)

    # ── KPIs globaux ─────────────────────────────────────────────────────────
    total_nav    = sum(t["value"] for t in board)
    total_pnl    = sum(t["pnl"]   for t in board)
    winners      = sum(1 for t in board if t["value"] >= TARGET_CAPITAL)
    avg_pnl_pct  = (total_nav / (STARTING_CAPITAL * len(board)) - 1) * 100 if board else 0

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "KPIs Globaux", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"  NAV totale : {total_nav:,.0f} € | PnL total : {total_pnl:+,.0f} € | Perf moy : {avg_pnl_pct:+.1f}%", ln=True)
    pdf.cell(0, 6, f"  Gagnants (≥{TARGET_CAPITAL}€) : {winners}/30 | Capital de départ : {STARTING_CAPITAL}€/trader", ln=True)
    pdf.ln(4)

    # ── Top 10 leaderboard ───────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Top 10 Leaderboard", ln=True)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(12, 6, "Rang", border=1)
    pdf.cell(20, 6, "TRD", border=1)
    pdf.cell(50, 6, "Nom", border=1)
    pdf.cell(35, 6, "Division", border=1)
    pdf.cell(30, 6, "Valeur (€)", border=1)
    pdf.cell(25, 6, "PnL %", border=1, ln=True)
    pdf.set_font("Helvetica", "", 9)
    for t in board[:10]:
        pdf.cell(12, 6, str(t["rank"]), border=1)
        pdf.cell(20, 6, f"TRD{t['id']:02d}", border=1)
        pdf.cell(50, 6, t["name"][:22], border=1)
        pdf.cell(35, 6, t.get("division", "")[:18], border=1)
        pdf.cell(30, 6, f"{t['value']:,.0f}", border=1)
        pdf.cell(25, 6, f"{t['pnl_pct']:+.1f}%", border=1, ln=True)
    pdf.ln(4)

    # ── Top 5 / Bottom 5 ─────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Sélection naturelle", ln=True)
    pdf.set_font("Helvetica", "", 10)
    top5 = post_market.get("top5", [])
    bot5 = post_market.get("bottom5", [])
    pdf.cell(0, 6, "TOP 5 : " + ", ".join(f"TRD{t['id']:02d}({t['value']:.0f}€)" for t in top5[:5]), ln=True)
    pdf.cell(0, 6, "BOT 5 : " + ", ".join(f"TRD{t['id']:02d}({t['value']:.0f}€)" for t in bot5[:5]), ln=True)

    # ── Divisions ─────────────────────────────────────────────────────────────
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Performance par Division", ln=True)
    pdf.set_font("Helvetica", "", 10)
    for div in post_market.get("divisions_ranked", []):
        pdf.cell(0, 6, f"  {div['name']} : {div.get('avg_pnl_pct', 0):+.1f}% moy", ln=True)

    pdf.output(str(chemin))


# ---------------------------------------------------------------------------
# JSON fallback
# ---------------------------------------------------------------------------

def _generer_json(chemin: Path, engine) -> None:
    data = {
        "timestamp":  datetime.now().isoformat(),
        "state":      engine.get_state(),
        "post_market": engine.get_post_market(),
    }
    chemin.write_text(json.dumps(data, indent=2, ensure_ascii=False))
