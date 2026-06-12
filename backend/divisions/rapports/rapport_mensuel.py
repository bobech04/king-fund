"""Rapport mensuel automatique — 1er du mois, Claude API narrative, PDF + Telegram."""
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_RAPPORTS_DIR = Path.home() / "rapports" / "mensuel"
_AUDIT_FILE   = Path(__file__).resolve().parents[3] / "logs" / "audit_agd01.jsonl"


def generer_rapport(engine) -> str:
    """Génère le rapport mensuel. Retourne le chemin absolu du fichier créé."""
    _RAPPORTS_DIR.mkdir(parents=True, exist_ok=True)
    mois = datetime.now().strftime("%Y-%m")

    donnees = _collecter_donnees(engine)
    narrative = _generer_narrative(donnees)

    try:
        from fpdf import FPDF
        chemin = _RAPPORTS_DIR / f"rapport_mensuel_{mois}.pdf"
        _generer_pdf(chemin, donnees, narrative)
        fmt = "PDF"
    except ImportError:
        chemin = _RAPPORTS_DIR / f"rapport_mensuel_{mois}.json"
        _generer_json(chemin, donnees, narrative)
        fmt = "JSON"

    logger.info("[RAPPORT MENSUEL %s] ✓ Généré : %s", fmt, chemin)
    _send_telegram_resume(donnees, narrative, str(chemin))
    return str(chemin)


def _collecter_donnees(engine) -> dict:
    """Collecte toutes les données nécessaires au rapport."""
    now = datetime.now()
    mois_label = now.strftime("%B %Y")

    # ── Engine state ──────────────────────────────────────────────────────────
    state = engine.get_state() if engine else {}
    board = state.get("leaderboard", state.get("traders", []))
    battle_day = state.get("battle_day", 0)
    nav_total  = sum(t.get("value", t.get("portfolio_value", 0)) for t in board)
    pnl_total  = sum(t.get("pnl", 0) for t in board)

    from config import STARTING_CAPITAL, TARGET_CAPITAL, BATTLE_DAYS
    perf_pct = (nav_total / (STARTING_CAPITAL * max(1, len(board))) - 1) * 100 if board else 0
    gagnants = sum(1 for t in board if t.get("value", t.get("portfolio_value", 0)) >= TARGET_CAPITAL)

    top5  = sorted(board, key=lambda t: t.get("pnl", 0), reverse=True)[:5]
    flop5 = sorted(board, key=lambda t: t.get("pnl", 0))[:5]

    # ── Benchmark CAC40 / SP500 ───────────────────────────────────────────────
    benchmark = {}
    try:
        from divisions.gerant_delegue.agent_benchmark import get_agent_benchmark
        benchmark = get_agent_benchmark().analyser(forcer=False)
    except Exception as e:
        logger.debug("Benchmark: %s", e)

    alpha_cac = benchmark.get("alpha_vs_cac40")
    alpha_sp  = benchmark.get("alpha_vs_sp500")

    # ── AGD-01 audit — décisions du mois ─────────────────────────────────────
    decisions_agd = []
    try:
        if _AUDIT_FILE.exists():
            lignes = _AUDIT_FILE.read_text(encoding="utf-8").splitlines()
            mois_prefix = now.strftime("%Y-%m")
            for ligne in lignes:
                try:
                    entry = json.loads(ligne)
                    ts = entry.get("timestamp", "")
                    if ts.startswith(mois_prefix):
                        decisions_agd.append({
                            "ts":      ts[:16],
                            "type":    entry.get("type", ""),
                            "decision": entry.get("decision", entry.get("summary", "")),
                        })
                except Exception:
                    pass
    except Exception as e:
        logger.debug("Audit AGD: %s", e)

    # ── Alpha Lab verdict ─────────────────────────────────────────────────────
    alpha_lab = {}
    try:
        from divisions.alpha_lab.valide_signaux import generer_rapport as _al_rapport
        alpha_lab = _al_rapport(force=False) or {}
    except Exception as e:
        logger.debug("Alpha Lab: %s", e)

    # ── Patrimoine / projection retraite ─────────────────────────────────────
    patrimoine = {}
    try:
        from data.patrimoine import get_patrimoine
        patrimoine = get_patrimoine()
    except Exception as e:
        logger.debug("Patrimoine: %s", e)

    return {
        "mois":         mois_label,
        "ts":           now.isoformat(),
        "battle_day":   battle_day,
        "nav_total":    nav_total,
        "pnl_total":    pnl_total,
        "perf_pct":     perf_pct,
        "gagnants":     gagnants,
        "nb_traders":   len(board),
        "top5":         top5,
        "flop5":        flop5,
        "alpha_cac40":  alpha_cac,
        "alpha_sp500":  alpha_sp,
        "decisions_agd": decisions_agd,
        "alpha_lab":    alpha_lab,
        "patrimoine":   patrimoine,
        "benchmark_raw": benchmark,
        "config":       {"starting": STARTING_CAPITAL, "target": TARGET_CAPITAL, "days": BATTLE_DAYS},
    }


def _generer_narrative(donnees: dict) -> str:
    """Génère la narrative Claude pour le rapport mensuel."""
    try:
        from config import ANTHROPIC_API_KEY
        import anthropic
        if not ANTHROPIC_API_KEY:
            return _narrative_fallback(donnees)

        cfg_ret = donnees.get("patrimoine", {}).get("config", {})
        val_ret = donnees.get("patrimoine", {}).get("valeur_retraite", 0)
        total_pat = donnees.get("patrimoine", {}).get("total_eur", 0)
        annee_ret = (cfg_ret.get("annee_base", 2026) +
                     (cfg_ret.get("age_retraite", 56) - cfg_ret.get("age_actuel", 35)))

        al = donnees.get("alpha_lab", {})
        valides  = ", ".join(al.get("valides",  []) or ["aucun"])
        bruits   = ", ".join(al.get("bruits",   []) or ["aucun"])
        overfits = ", ".join(al.get("overfits", []) or ["aucun"])

        decisions_resume = ""
        for d in donnees["decisions_agd"][:5]:
            decisions_resume += f"  - [{d['ts']}] {d['type']} : {d['decision'][:80]}\n"

        prompt = f"""Rédige le résumé exécutif du rapport mensuel King Fund pour {donnees['mois']}.

DONNÉES DU MOIS :
- NAV totale : {donnees['nav_total']:,.0f}€ | PnL : {donnees['pnl_total']:+,.0f}€ | Perf moy : {donnees['perf_pct']:+.1f}%
- Jour de bataille J{donnees['battle_day']} | Gagnants (≥10k€) : {donnees['gagnants']}/{donnees['nb_traders']}
- Alpha vs CAC40 : {donnees['alpha_cac40']}% | Alpha vs SP500 : {donnees['alpha_sp500']}%
- Top traders : {', '.join(f"TRD{t.get('id',0):02d}({t.get('pnl',0):+.0f}€)" for t in donnees['top5'][:3])}
- Flop traders : {', '.join(f"TRD{t.get('id',0):02d}({t.get('pnl',0):+.0f}€)" for t in donnees['flop5'][:3])}

ALPHA LAB :
- Signaux VALIDES : {valides}
- Bruit : {bruits}
- Overfittés : {overfits}

DÉCISIONS AGD-01 ce mois :
{decisions_resume or '  Aucune décision enregistrée'}

PATRIMOINE & RETRAITE :
- Patrimoine actuel : {total_pat:,.0f}€
- Objectif retraite 56 ans ({annee_ret}) : {val_ret:,.0f}€

Rédige 3-4 paragraphes en français, ton institutionnel. Inclus : verdict performance, analyse alpha, recommandation AGD-01 pour le mois suivant, évolution vers l'objectif retraite 2041."""

        try:
            from agents.formation import enrichir_systeme
            system = enrichir_systeme("Tu es le gérant délégué du King Fund. Rédige des rapports mensuels précis et orientés décision.")
        except Exception:
            system = "Tu es le gérant délégué du King Fund. Rédige des rapports mensuels précis et orientés décision."

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        logger.warning("[RAPPORT MENSUEL] Claude narrative: %s", e)
        return _narrative_fallback(donnees)


def _narrative_fallback(donnees: dict) -> str:
    cfg_ret = donnees.get("patrimoine", {}).get("config", {})
    annee_ret = (cfg_ret.get("annee_base", 2026) +
                 (cfg_ret.get("age_retraite", 56) - cfg_ret.get("age_actuel", 35)))
    return (
        f"Rapport mensuel {donnees['mois']} — NAV {donnees['nav_total']:,.0f}€, "
        f"PnL {donnees['pnl_total']:+,.0f}€ ({donnees['perf_pct']:+.1f}%). "
        f"Alpha CAC40 : {donnees['alpha_cac40']}% | Alpha SP500 : {donnees['alpha_sp500']}%. "
        f"Gagnants : {donnees['gagnants']}/{donnees['nb_traders']}. "
        f"Objectif retraite {annee_ret} : {donnees['patrimoine'].get('valeur_retraite',0):,.0f}€."
    )


def _s(text: str) -> str:
    """Assainit un texte pour les polices Helvetica fpdf2 (ISO-8859-1)."""
    return (text.replace("—", "-").replace("–", "-")
                .replace("€", "EUR").replace("≥", ">=").replace("≤", "<=")
                .replace("→", "->").replace("←", "<-").replace("•", "*")
                .encode("latin-1", "replace").decode("latin-1"))


def _generer_pdf(chemin: Path, donnees: dict, narrative: str) -> None:
    from fpdf import FPDF
    ts  = datetime.now().strftime("%d/%m/%Y %H:%M")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # ── En-tête
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "KING FUND - Rapport Mensuel", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _s(f"Genere le {ts} | {donnees['mois']} | J{donnees['battle_day']}"), ln=True, align="C")
    pdf.ln(6)

    # ── Narrative
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Resume Executif AGD-01", ln=True)
    pdf.set_font("Helvetica", "", 10)
    for ligne in narrative.replace("\r", "").split("\n"):
        safe = _s(ligne.strip())
        if safe:
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(0, 5, safe)
        else:
            pdf.ln(3)
    pdf.ln(4)

    # ── KPIs performance
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Performance du Mois", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _s(f"  NAV totale : {donnees['nav_total']:,.0f}EUR  |  PnL : {donnees['pnl_total']:+,.0f}EUR  |  Perf moy : {donnees['perf_pct']:+.1f}%"), ln=True)
    pdf.cell(0, 6, _s(f"  Alpha vs CAC40 : {donnees['alpha_cac40']}%  |  Alpha vs SP500 : {donnees['alpha_sp500']}%"), ln=True)
    pdf.cell(0, 6, _s(f"  Gagnants (>=10 000 EUR) : {donnees['gagnants']}/{donnees['nb_traders']}"), ln=True)
    pdf.ln(4)

    # ── Top 5 / Flop 5
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Top 5 Traders", ln=True)
    pdf.set_font("Helvetica", "", 10)
    for t in donnees["top5"]:
        pdf.cell(0, 6, _s(f"  TRD{t.get('id',0):02d} - {t.get('name','?')[:25]} - PnL {t.get('pnl',0):+,.0f}EUR"), ln=True)
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Flop 5 Traders", ln=True)
    pdf.set_font("Helvetica", "", 10)
    for t in donnees["flop5"]:
        pdf.cell(0, 6, _s(f"  TRD{t.get('id',0):02d} - {t.get('name','?')[:25]} - PnL {t.get('pnl',0):+,.0f}EUR"), ln=True)
    pdf.ln(4)

    # ── Décisions AGD-01
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Decisions AGD-01 ce mois", ln=True)
    pdf.set_font("Helvetica", "", 9)
    if donnees["decisions_agd"]:
        for d in donnees["decisions_agd"][:10]:
            pdf.cell(0, 5, _s(f"  [{d['ts']}] {d['type']} : {d['decision'][:60]}"), ln=True)
    else:
        pdf.cell(0, 5, "  Aucune decision enregistree ce mois", ln=True)
    pdf.ln(4)

    # ── Alpha Lab
    al = donnees.get("alpha_lab", {})
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Verdict Alpha Lab", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _s(f"  Signaux VALIDES : {', '.join(al.get('valides', []) or ['aucun'])}"), ln=True)
    pdf.cell(0, 6, _s(f"  Bruit : {', '.join(al.get('bruits', []) or ['aucun'])}"), ln=True)
    pdf.cell(0, 6, _s(f"  Overfites : {', '.join(al.get('overfits', []) or ['aucun'])}"), ln=True)
    pdf.ln(4)

    # ── Retraite
    pat = donnees.get("patrimoine", {})
    cfg_ret = pat.get("config", {})
    val_ret = pat.get("valeur_retraite", 0)
    total_pat = pat.get("total_eur", 0)
    annee_ret = (cfg_ret.get("annee_base", 2026) +
                 (cfg_ret.get("age_retraite", 56) - cfg_ret.get("age_actuel", 35)))
    pct_ret = min(100, total_pat / max(1, val_ret) * 100)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, f"Evolution vers Retraite 56 ans ({annee_ret})", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _s(f"  Patrimoine actuel : {total_pat:,.0f}EUR"), ln=True)
    pdf.cell(0, 6, _s(f"  Objectif retraite : {val_ret:,.0f}EUR"), ln=True)
    pdf.cell(0, 6, _s(f"  Progression : {pct_ret:.1f}%"), ln=True)

    pdf.output(str(chemin))


def _generer_json(chemin: Path, donnees: dict, narrative: str) -> None:
    chemin.write_text(
        json.dumps({"narrative": narrative, **donnees}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _send_telegram_resume(donnees: dict, narrative: str, chemin: str) -> None:
    try:
        from divisions.gerant_delegue.notifier import send
        al = donnees.get("alpha_lab", {})
        valides = ", ".join(al.get("valides", []) or ["aucun"])
        msg = (
            f"📅 <b>Rapport Mensuel King Fund — {donnees['mois']}</b>\n\n"
            f"💰 NAV : <b>{donnees['nav_total']:,.0f}€</b> | PnL : <b>{donnees['pnl_total']:+,.0f}€</b> ({donnees['perf_pct']:+.1f}%)\n"
            f"📊 Alpha CAC40 : {donnees['alpha_cac40']}% | SP500 : {donnees['alpha_sp500']}%\n"
            f"🏆 Gagnants : {donnees['gagnants']}/{donnees['nb_traders']}\n"
            f"🔬 Alpha Lab — VALIDES : {valides}\n"
            f"🎯 Patrimoine : {donnees['patrimoine'].get('total_eur',0):,.0f}€\n\n"
            f"<i>{narrative[:300]}...</i>\n\n"
            f"📄 PDF : {Path(chemin).name}"
        )
        send(msg)
    except Exception as e:
        logger.debug("Telegram rapport mensuel: %s", e)
