# CRITERES_SUCCES.md — Phase test (2-3 mois)

## 1. Opérationnel (le plus important — GO/NO-GO réel)

- Le système tourne sans crash bloquant pendant la phase test
- Les alertes Telegram/email arrivent correctement, sans spam excessif ni silence sur du critique
- Le dashboard reste accessible (local + mobile + Algérie)
- Les sauvegardes/persistance SQLite fonctionnent (pas de perte de données après redémarrage)

> **→ NO-GO sur MODE=RÉEL si un de ces points échoue de façon répétée.**

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

---

## 5. AGD-01 (vétos)

- Chaque véto loggé avec justification
- Revue manuelle en fin de phase : le véto a-t-il évité une perte ou raté un gain ? (apprentissage, pas sanction)

---

## 6. Le critère final — toi

- Comprends-tu ce que fait le système à tout moment ?
- Fais-tu confiance pour basculer MODE=RÉEL avec de l'argent qui compte pour ta retraite ?

> **Si non → identifier précisément ce qui manque en confiance, et le traiter avant de basculer.**
