"""Rapport annuel automatique — 31 décembre, bilan année + fiscalité FSC-FRA-01, PDF + Telegram."""
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_RAPPORTS_DIR = Path(__file__).resolve().parents[3] / "rapports" / "annuel"


def generer_rapport(engine) -> str:
    """Génère le rapport annuel. Retourne le chemin absolu du fichier créé."""
    _RAPPORTS_DIR.mkdir(parents=True, exist_ok=True)
    annee = datetime.now().strftime("%Y")

    donnees = _collecter_donnees(engine)
    narrative = _generer_narrative(donnees)

    try:
        from fpdf import FPDF
        chemin = _RAPPORTS_DIR / f"rapport_annuel_{annee}.pdf"
        _generer_pdf(chemin, donnees, narrative)
        fmt = "PDF"
    except ImportError:
        chemin = _RAPPORTS_DIR / f"rapport_annuel_{annee}.json"
        _generer_json(chemin, donnees, narrative)
        fmt = "JSON"

    logger.info("[RAPPORT ANNUEL %s] ✓ Généré : %s", fmt, chemin)
    _send_telegram_resume(donnees, narrative, str(chemin))
    return str(chemin)


def _collecter_donnees(engine) -> dict:
    now = datetime.now()
    annee = now.year

    # ── Engine state
    state  = engine.get_state() if engine else {}
    board  = state.get("leaderboard", state.get("traders", []))
    nav    = sum(t.get("value", t.get("portfolio_value", 0)) for t in board)
    pnl    = sum(t.get("pnl", 0) for t in board)
    from config import STARTING_CAPITAL, TARGET_CAPITAL, BATTLE_DAYS
    perf   = (nav / (STARTING_CAPITAL * max(1, len(board))) - 1) * 100 if board else 0

    # ── Benchmark annuel
    benchmark = {}
    try:
        from divisions.gerant_delegue.agent_benchmark import get_agent_benchmark
        benchmark = get_agent_benchmark().analyser(forcer=False)
    except Exception as e:
        logger.debug("Benchmark annuel: %s", e)

    # ── Patrimoine + fiscalité
    patrimoine = {}
    try:
        from data.patrimoine import get_patrimoine
        patrimoine = get_patrimoine()
    except Exception as e:
        logger.debug("Patrimoine annuel: %s", e)

    # ── Suivi PRU — plus-values réalisées sur l'année
    pv_realisees = []
    try:
        from data.suivi_pru import get_suivi_pru
        suivi = get_suivi_pru()
        # Transactions de vente de l'année en cours
        txs = suivi.get("transactions", [])
        for tx in txs:
            if tx.get("type") == "vente" and str(tx.get("date", "")).startswith(str(annee)):
                pv_realisees.append(tx)
    except Exception as e:
        logger.debug("Suivi PRU annuel: %s", e)

    # ── Alpha Lab synthèse annuelle
    alpha_lab = {}
    try:
        from divisions.alpha_lab.valide_signaux import generer_rapport as _al
        alpha_lab = _al(force=False) or {}
    except Exception as e:
        logger.debug("Alpha Lab annuel: %s", e)

    # ── Calculer plus-value imposable (hors PEA)
    pv_totale_cto = sum(
        (tx.get("prix_unitaire", 0) - tx.get("pru_reference", 0)) * tx.get("quantite", 0)
        for tx in pv_realisees
        if tx.get("compte", "cto") == "cto"
    )
    flat_tax = round(pv_totale_cto * 0.30, 2) if pv_totale_cto > 0 else 0

    fsc = patrimoine.get("fiscalite", {}).get("fsc_fra_01", {})

    return {
        "annee":         annee,
        "ts":            now.isoformat(),
        "nav_total":     nav,
        "pnl_total":     pnl,
        "perf_pct":      perf,
        "benchmark":     benchmark,
        "patrimoine":    patrimoine,
        "fsc_fra_01":    fsc,
        "pv_realisees":  pv_realisees,
        "pv_totale_cto": pv_totale_cto,
        "flat_tax_estime": flat_tax,
        "alpha_lab":     alpha_lab,
        "config":        {"starting": STARTING_CAPITAL, "target": TARGET_CAPITAL, "days": BATTLE_DAYS},
    }


def _generer_narrative(donnees: dict) -> str:
    try:
        from config import ANTHROPIC_API_KEY
        import anthropic
        if not ANTHROPIC_API_KEY:
            return _narrative_fallback(donnees)

        pat = donnees.get("patrimoine", {})
        cfg_ret = pat.get("config", {})
        annee_ret = (cfg_ret.get("annee_base", 2026) +
                     (cfg_ret.get("age_retraite", 56) - cfg_ret.get("age_actuel", 35)))
        val_ret = pat.get("valeur_retraite", 0)
        total_pat = pat.get("total_eur", 0)

        fsc = donnees.get("fsc_fra_01", {})
        or_info = fsc.get("or", {})
        st_info = fsc.get("stellantis", {})

        prompt = f"""Rédige le bilan annuel {donnees['annee']} du King Fund, avec analyse fiscale pour la déclaration d'impôts.

PERFORMANCE ANNUELLE :
- NAV totale : {donnees['nav_total']:,.0f}€ | PnL : {donnees['pnl_total']:+,.0f}€ | Perf : {donnees['perf_pct']:+.1f}%
- Alpha vs CAC40 : {donnees['benchmark'].get('alpha_vs_cac40', 'N/A')}% | Alpha vs SP500 : {donnees['benchmark'].get('alpha_vs_sp500', 'N/A')}%

FISCALITÉ PLUS-VALUES (FSC-FRA-01) :
- Plus-values réalisées CTO : {donnees['pv_totale_cto']:+,.0f}€
- Flat Tax estimée (30%) : {donnees['flat_tax_estime']:,.0f}€
- Or physique — option A (taxe forfaitaire 11.5%) : {or_info.get('option_A', {}).get('impot', 'N/A')}€
- Or physique — abattement acquis : {or_info.get('option_B', {}).get('abattement_acquis', 'N/A')}
- Stellantis — PFU annuel estimé : {st_info.get('pfu_annuel', 'N/A')}€
- Conventions DZD-FR : rapatriement ≤ 15 000€/an, CERFA 3916 obligatoire

PATRIMOINE :
- Total : {total_pat:,.0f}€ → Objectif retraite {annee_ret} : {val_ret:,.0f}€

Rédige 4-5 paragraphes : bilan annuel de la battle, analyse alpha, éléments clés à déclarer pour les impôts (montants précis), recommandations patrimoniales pour l'année suivante."""

        try:
            from agents.formation import enrichir_systeme
            system = enrichir_systeme("Tu es le gérant délégué et fiscaliste du King Fund. Rédige le bilan annuel et la synthèse fiscale.")
        except Exception:
            system = "Tu es le gérant délégué et fiscaliste du King Fund. Rédige le bilan annuel et la synthèse fiscale."

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        logger.warning("[RAPPORT ANNUEL] Claude narrative: %s", e)
        return _narrative_fallback(donnees)


def _narrative_fallback(donnees: dict) -> str:
    pat = donnees.get("patrimoine", {})
    cfg_ret = pat.get("config", {})
    annee_ret = (cfg_ret.get("annee_base", 2026) +
                 (cfg_ret.get("age_retraite", 56) - cfg_ret.get("age_actuel", 35)))
    return (
        f"Bilan annuel {donnees['annee']} — NAV {donnees['nav_total']:,.0f}€, "
        f"PnL {donnees['pnl_total']:+,.0f}€ ({donnees['perf_pct']:+.1f}%). "
        f"Plus-values CTO imposables : {donnees['pv_totale_cto']:+,.0f}€ → Flat Tax 30% estimée : {donnees['flat_tax_estime']:,.0f}€. "
        f"Objectif retraite {annee_ret} : {pat.get('valeur_retraite',0):,.0f}€."
    )


def _generer_pdf(chemin: Path, donnees: dict, narrative: str) -> None:
    from fpdf import FPDF
    ts = datetime.now().strftime("%d/%m/%Y %H:%M")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # ── En-tête
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 12, f"KING FUND — Bilan Annuel {donnees['annee']}", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Généré le {ts} — Document fiscal à conserver", ln=True, align="C")
    pdf.ln(6)

    # ── Narrative
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Bilan Annuel & Analyse AGD-01", ln=True)
    pdf.set_font("Helvetica", "", 10)
    for ligne in narrative.split("\n"):
        safe = ligne.encode("latin-1", "replace").decode("latin-1")
        pdf.multi_cell(0, 5, safe)
    pdf.ln(4)

    # ── Performance annuelle
    bench = donnees.get("benchmark", {})
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, f"Performance Annuelle {donnees['annee']}", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"  NAV totale : {donnees['nav_total']:,.0f}€  |  PnL : {donnees['pnl_total']:+,.0f}€  |  Perf : {donnees['perf_pct']:+.1f}%", ln=True)
    pdf.cell(0, 6, f"  Alpha vs CAC40 : {bench.get('alpha_vs_cac40','N/A')}%  |  Alpha vs SP500 : {bench.get('alpha_vs_sp500','N/A')}%", ln=True)
    pdf.ln(4)

    # ── FISCALITÉ — section centrale
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "FISCALITÉ — FSC-FRA-01 — Déclaration Impôts", ln=True)
    pdf.set_fill_color(240, 240, 255)

    fsc = donnees.get("fsc_fra_01", {})
    or_info = fsc.get("or", {})
    st_info = fsc.get("stellantis", {})

    # Plus-values trading
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "1. Plus-values réalisées (CTO)", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"  Total plus-values CTO {donnees['annee']} : {donnees['pv_totale_cto']:+,.0f}€", ln=True)
    pdf.cell(0, 6, f"  Flat Tax PFU estimée (30%) : {donnees['flat_tax_estime']:,.0f}€", ln=True)
    pdf.cell(0, 6, "  → A reporter en case 3VG (gains) ou 3VH (pertes) de la déclaration 2042-C", ln=True)
    pdf.ln(2)

    # Or
    opt_a = or_info.get("option_A", {})
    opt_b = or_info.get("option_B", {})
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "2. Or physique", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"  Actif : {or_info.get('actif', 'Or physique')}", ln=True)
    pdf.cell(0, 6, f"  Option A — Taxe forfaitaire 11.5% sur cession : {opt_a.get('impot', 'N/A')}€", ln=True)
    pdf.cell(0, 6, f"  Option B — Abattement acquis : {opt_b.get('abattement_acquis', 'N/A')} (exonéré : {opt_b.get('exonere', False)})", ln=True)
    pdf.cell(0, 6, f"  Conseil : {or_info.get('conseil', '')[:80]}", ln=True)
    pdf.ln(2)

    # Stellantis
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "3. Actions Stellantis", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"  Dividendes estimés : {st_info.get('dividendes_estimes', 0):.2f}€  |  PFU annuel : {st_info.get('pfu_annuel', 0):.2f}€", ln=True)
    pdf.cell(0, 6, f"  Conseil : {st_info.get('conseil', '')[:80]}", ln=True)
    pdf.ln(2)

    # Convention DZD
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "4. Épargne DZD — Convention Franco-Algérienne", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, "  Rapatriement max : 15 000€/an — Banques agréées : CPA/BEA/BNA/BADR", ln=True)
    pdf.cell(0, 6, "  CERFA 3916 obligatoire — Déclaration compte bancaire étranger", ln=True)
    pdf.cell(0, 6, "  Convention DZ-FR 17/10/1999 Art.18 — Revenus imposés en France", ln=True)
    pdf.ln(4)

    # ── Retraite
    pat = donnees.get("patrimoine", {})
    cfg_ret = pat.get("config", {})
    annee_ret = (cfg_ret.get("annee_base", 2026) +
                 (cfg_ret.get("age_retraite", 56) - cfg_ret.get("age_actuel", 35)))
    total_pat = pat.get("total_eur", 0)
    val_ret   = pat.get("valeur_retraite", 0)
    pct_ret   = min(100, total_pat / max(1, val_ret) * 100)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, f"Patrimoine — Projection Retraite {annee_ret}", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"  Patrimoine {donnees['annee']} : {total_pat:,.0f}€", ln=True)
    pdf.cell(0, 6, f"  Objectif retraite 56 ans ({annee_ret}) : {val_ret:,.0f}€", ln=True)
    pdf.cell(0, 6, f"  Progression : {pct_ret:.1f}%", ln=True)

    pdf.output(str(chemin))


def _generer_json(chemin: Path, donnees: dict, narrative: str) -> None:
    chemin.write_text(
        json.dumps({"narrative": narrative, **donnees}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _send_telegram_resume(donnees: dict, narrative: str, chemin: str) -> None:
    try:
        from divisions.gerant_delegue.notifier import send
        msg = (
            f"📆 <b>Bilan Annuel King Fund {donnees['annee']}</b>\n\n"
            f"💰 NAV : {donnees['nav_total']:,.0f}€ | PnL : {donnees['pnl_total']:+,.0f}€ ({donnees['perf_pct']:+.1f}%)\n"
            f"🏦 <b>FISCALITÉ FSC-FRA-01</b>\n"
            f"  • PV CTO imposables : {donnees['pv_totale_cto']:+,.0f}€\n"
            f"  • Flat Tax 30% estimée : <b>{donnees['flat_tax_estime']:,.0f}€</b>\n"
            f"  • CERFA 3916 : compte DZD à déclarer\n\n"
            f"<i>{narrative[:400]}...</i>\n\n"
            f"📄 PDF : {Path(chemin).name}"
        )
        send(msg)
    except Exception as e:
        logger.debug("Telegram rapport annuel: %s", e)
