# CRITERES_SUCCES.md — Phase test (prolongée jusqu'au 30 juillet 2026)

> **Prolongation J30 → J60 (mise à jour 30/06/2026)** — raisons : bugs critiques corrigés le 30/06/2026,
> Raspberry Pi pas encore en place, régime macro CRISE_LIQUIDITE actif. Détail dans `PHASE_TEST.md`.

## 1. Opérationnel (le plus important — GO/NO-GO réel)

- Le système tourne sans crash bloquant pendant la phase test
- Les alertes Telegram/email arrivent correctement, sans spam excessif ni silence sur du critique
- Le dashboard reste accessible (local + mobile + Algérie)
- Les sauvegardes/persistance SQLite fonctionnent (pas de perte de données après redémarrage)

> **→ NO-GO sur MODE=RÉEL si un de ces points échoue de façon répétée.**

### Conditions Go/No-Go MODE=RÉEL — mises à jour au 30/06/2026 (toutes requises)

1. **Raspberry Pi stable 7 jours consécutifs** — hébergement cible en place et fiable
2. **Régime macro repassé à SEREIN** — sortie confirmée du régime CRISE_LIQUIDITE (Agent Flux Macro)
3. **0 bug critique pendant 30 jours consécutifs**

---

## 2. Cohérence macro (qualitatif)

- Le CIO reste-t-il aligné avec la thèse MMT/actifs réels (Bertez) tout en restant capable de réagir si le contexte change (ex: signal de retournement sur l'or comme évoqué par Seb) ?
- Le signal Bertez se calcule-t-il en continu sans erreur ? (la validation prédictive elle-même vient de l'Alpha-Lab 1973-2022, pas de ces 2-3 mois)
- Les régimes détectés (MMT_INFLATION, etc.) changent-ils de façon cohérente avec l'actualité macro réelle ?

---

## 3. Traders algorithmiques (30) — indicateurs à observer, pas de seuil GO/NO-GO

- Sharpe ratio et PnL sur 30j : utilisés pour la sélection naturelle (déjà automatisée), mais pas comme verdict définitif sur 2-3 mois
- Groupe C (barbell Taleb) : jugé sur le drawdown évité en cas de choc, pas sur le PnL
- Si un groupe entier (A/B/C) dérive massivement négatif sans raison macro identifiable → investiguer le code, pas juste éliminer les traders

---

## 4. Division Investissement & Agents — qualitatif

- Les recommandations BUY/SELL semblent-elles raisonnables a posteriori ? (revue manuelle, pas de calcul statistique sur si peu de données)
- Chaque agent (Actualités, Dividendes, Risk Parity, Benchmark) a-t-il produit au moins une alerte/décision qui t'a semblé utile sur la période ?
- Si un agent reste totalement silencieux et inutile → passer en mode silencieux (pas suppression)

### Agent Flux Macro ("Le Détective de Capitaux")

- Les **régimes marché** détectés (NORMAL / ROTATION / CRISE_LIQUIDITE / EFFONDREMENT) changent-ils de façon cohérente avec l'actualité réelle ?
- La **détection d'anomalies** (2σ sur 48h vs moyenne 30j) déclenche-t-elle des alertes crédibles ou génère-t-elle du bruit excessif ?
- Les **checklist anti-biais** (10 items, 7 bloquants) font-elles baisser la confiance quand c'est justifié, sans paralyser le signal ?
- Le job tourne-t-il bien 2× par jour (10h00 et 18h00 Paris) sans échec silencieux ?

### Alpha-Lab — Backtests Signaux & Facteurs Académiques

- **Signal TrendFollow** : verdict VALIDE attendu (t-stat ≥ 2.0, Sharpe OOS ≥ 0.50). Si passage en BRUIT → investiguer les données Fama-French, pas le signal.
- **Signal Bertez** : verdict OVERFITTE attendu (t-stat ≥ 2.0 mais Sharpe OOS < 0.25 sur le proxy HML+CAPE). Normal — valeur dans la thèse macro, pas dans la mécanique statistique.
- Les **4 facteurs** (Value, Momentum, Quality, LowVol) produisent-ils des classements cross-sectionnels stables sur la watchlist 13 actifs ?
- Le rapport mensuel (1er du mois 07h00) arrive-t-il sur Telegram sans erreur ?

### Screener mondial (02h30 UTC — nuit)

- Le job `screener_mondial` tourne-t-il chaque nuit à 02h30 UTC sans timeout ni crash silencieux ?
- Les top 50 Graham issus des 120 titres (Euronext Paris/Amsterdam, Oslo, NYSE) semblent-ils cohérents avec les valorisations réelles ?
- Les signaux BUY auto (score ≥ 7 + marge ≥ 30%) sont-ils cross-validés par le Comité Sélection avant toute action réelle ?

---

## 5. AGD-01 (vétos)

- Chaque véto loggé avec justification
- Revue manuelle en fin de phase : le véto a-t-il évité une perte ou raté un gain ? (apprentissage, pas sanction)

---

## 6. Le critère final — toi

- Comprends-tu ce que fait le système à tout moment ?
- Fais-tu confiance pour basculer MODE=RÉEL avec de l'argent qui compte pour ta retraite ?

> **Si non → identifier précisément ce qui manque en confiance, et le traiter avant de basculer.**
