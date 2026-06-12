# Guide d'utilisation — King Fund
## Family Office · Tableau de bord personnel

---

## Accéder au dashboard

### Sur votre ordinateur (réseau local)

1. Ouvrez un terminal et lancez le serveur :
   ```
   python -X utf8 backend/app.py
   ```
2. Ouvrez votre navigateur à l'adresse :
   ```
   http://localhost:5000
   ```
3. Entrez votre mot de passe et appuyez sur **Connexion**.

---

### Sur votre téléphone (même réseau Wi-Fi)

1. Trouvez l'adresse IP de votre ordinateur  
   *(Windows : tapez `ipconfig` dans un terminal, notez l'adresse du type `192.168.1.X`)*
2. Sur votre téléphone, ouvrez le navigateur et tapez :
   ```
   http://192.168.1.X:5000
   ```
   *(remplacez X par votre numéro réel)*
3. Connectez-vous avec votre mot de passe.

> **Astuce :** Appuyez sur **« Ajouter à l'écran d'accueil »** dans votre navigateur pour avoir une icône King Fund comme une vraie application.

---

### Depuis n'importe où (GitHub Pages)

Le dashboard est aussi disponible en ligne sur GitHub Pages.  
Pour qu'il se connecte à votre serveur, ajoutez `?api=http://192.168.1.X:5000/api` à la fin de l'URL.

---

## Lire le Morning Brief

Le Morning Brief est un rapport automatique généré chaque matin à **06h30**.  
Il résume les conditions de marché de la journée et vous indique la direction à prendre.

### Où le trouver

Cliquez sur l'onglet **🌅 Brief** dans la barre du bas.

### Comment l'interpréter

| Ce que vous voyez | Ce que ça veut dire |
|---|---|
| **HAUSSIER** (fond vert) | Les marchés sont orientés à la hausse. Conditions favorables pour les achats. |
| **BAISSIER** (fond rouge) | Les marchés sont orientés à la baisse. Prudence, évitez d'acheter. |
| **NEUTRE** (fond gris) | Pas de tendance claire. Restez sur vos positions actuelles. |
| **Confiance 85%** | Le système est très sûr de son analyse. En dessous de 50%, prenez-le avec précaution. |

Le texte qui suit explique en détail pourquoi : indices asiatiques, décisions des banques centrales, actualités importantes.

> **En pratique :** lisez le Brief chaque matin avant de prendre une décision d'achat ou de vente. Si le Brief dit BAISSIER avec 80% de confiance, ce n'est pas le moment d'acheter.

---

## Répondre aux alertes Telegram

Le système vous envoie des alertes sur Telegram à différents niveaux d'urgence.  
Voici comment reconnaître chaque type et ce que vous devez faire.

---

### 🚨 Alerte CRITIQUE — Action immédiate

**Exemples de messages :**
- `🚨 BLACK SWAN HALT — VIX à 38 : tous les traders sont mis en pause`
- `🚨 VPK.AS sous 44€ — seuil d'entrée atteint`
- `🚨 COMITÉ : BUY CONFIRMÉ 3/3 — GTT.PA`

**Que faire :**
- Ouvrez le dashboard immédiatement.
- Pour un **arrêt Black Swan** : ne paniquez pas, c'est une protection automatique. Les traders reprennent quand le VIX redescend sous 30. Vous n'avez rien à faire.
- Pour un **seuil de prix atteint** : c'est une opportunité d'achat identifiée. Consultez l'onglet **🧠 Intelligence** > section *Alertes prix* pour les détails.
- Pour un **BUY CONFIRMÉ** du Comité : voir section *Valider une décision AGD-01* ci-dessous.

---

### ⚠️ Alerte WARNING — À surveiller

**Exemples de messages :**
- `⚠️ COMITÉ : BUY CONDITIONNEL 2/3 — BIPC`
- `⚠️ Sentiment BCE hawkish élevé (0.72)`
- `⚠️ Trader TRD-07 en zone d'élimination (J15, portefeuille < 300€)`

**Que faire :**
- Pas d'urgence immédiate, mais consultez le dashboard dans la journée.
- Pour un **BUY CONDITIONNEL** : le Comité n'est pas unanime. Attendez une prochaine séance ou demandez un nouveau vote via l'onglet Intelligence.
- Pour un **sentiment hawkish** (banque centrale qui veut monter les taux) : les marchés obligataires vont souffrir, les marchés actions pourraient baisser. Renforcez l'or si votre allocation le permet.

---

### 🛑 VETO d'AGD-01 — Décision bloquée

**Exemple de message :**
```
🛑 VETO — AGD-01
Décision : ACHAT TSLA 500€
Raison : décision émotionnelle — TSLA en hausse de 15% sur 3 jours,
prix déjà au-dessus de la valeur intrinsèque.
Recommandation : attendre une consolidation à -10% minimum.
```

**Que faire :**
- Lisez attentivement la raison du veto.
- AGD-01 (Dr Alexandre Redon) a analysé votre décision et l'a jugée irrationnelle ou risquée.
- Vous pouvez **passer outre** en allant dans l'onglet **🧠 Intelligence** > *Décisions AGD-01* et en forçant la décision — mais cela sera enregistré dans le journal d'audit.
- Conseil : dans 80% des cas, le veto est justifié. Prenez le temps de relire la recommandation avant d'insister.

---

### 🏛️ Alerte COMITÉ — Résultat du vote

Le Comité de Sélection se réunit chaque soir à **23h00** et vote sur les meilleures opportunités d'achat de la watchlist.

**Exemple de message :**
```
🏛️ COMITÉ DE SÉLECTION — 12 juin 2026
VPK.AS (Vopak) : 3/3 OUI → BUY CONFIRMÉ
  Research : score 8.2/10 ✅
  CIO : aligné macro DEFENSIF (actifs réels) ✅
  Fiscaliste : Flat Tax 30% appliquée, traitement standard ✅
Montant conseillé : 200€
```

**Que faire :**
| Vote | Signification | Action recommandée |
|---|---|---|
| **3/3 OUI — BUY CONFIRMÉ** | Les 3 experts sont d'accord | Achetez si vous avez le cash disponible |
| **2/3 OUI — BUY CONDITIONNEL** | Un expert a des réserves | Attendez ou achetez une petite part |
| **1/3 OUI — HOLD** | Désaccord important | Ne faites rien pour l'instant |
| **0/3 — VETO** | Tous les experts s'y opposent | N'achetez pas |

> Le montant conseillé tient compte de votre budget SITG (bonus de performance) et de votre allocation actuelle.

---

### 💰 Alerte DIVIDENDE

**Exemple :**
```
💰 Dividende reçu : O (Realty Income) — 0.26$ le 15 juin
Revenus passifs cumulés ce mois : 18.40€
```

Rien à faire, c'est de l'information. Notez-le dans votre suivi si besoin.

---

### 📋 Rapport hebdomadaire (lundi matin)

Chaque lundi à **08h00**, AGD-01 envoie un rapport complet.  
Il contient : performance de la semaine, comparaison avec le CAC40 et le S&P500, décisions prises, et une projection de votre objectif retraite 2041.

Lisez-le tranquillement le lundi matin avant de commencer la semaine.

---

## Valider ou refuser une décision AGD-01

AGD-01 peut vous demander de valider une décision importante avant de l'exécuter, ou vous proposer un achat via le Comité de Sélection.

### Via le dashboard (recommandé)

1. Ouvrez l'onglet **🧠 Intelligence**.
2. Descendez jusqu'à la section **Comité Sélection — Historique des votes**.
3. Vous voyez la liste des décisions récentes avec leur verdict (BUY CONFIRMÉ, CONDITIONNEL, VETO).
4. Pour demander un nouveau vote sur un titre : entrez le ticker dans le champ prévu et appuyez sur **Voter**.

### Pour évaluer votre propre décision

Si vous avez une idée d'achat et voulez l'avis d'AGD-01 avant d'agir :

1. Onglet **🧠 Intelligence** > section **Veto émotionnel AGD-01**.
2. Remplissez le formulaire : ticker, action (ACHAT/VENTE), montant en €, contexte.
3. Appuyez sur **Évaluer**.
4. AGD-01 répond en quelques secondes avec VALIDE ou VETO + sa justification.

### Ce que signifient les réponses

| Réponse | Signification |
|---|---|
| **VALIDE** | La décision est rationnelle, vous pouvez procéder. |
| **VETO** | La décision est jugée risquée ou émotionnelle. Lisez la recommandation. |

> Le journal de toutes les décisions est enregistré dans l'onglet Intelligence > section *Journal Audit AGD-01* avec une empreinte cryptographique (vous pouvez vérifier qu'il n'a pas été modifié).

---

## Repères rapides

| Onglet | À consulter quand… |
|---|---|
| 📊 Bord | Tous les jours — vue globale du battle et de votre patrimoine |
| 🌅 Brief | Chaque matin — direction des marchés du jour |
| 🧠 Intelligence | Après une alerte Telegram — décisions, alertes prix, comité |
| 💎 Patrimoine | Une fois par semaine — apports, projection retraite, PRU |
| 📈 Croissance | Suivi des 30 traders IA — qui performe, qui est en difficulté |
| 💧 Liquidité | En cas d'alerte macro — état du marché mondial (Howell) |
| 🌍 Marchés | Pour un contexte de marché rapide (indices, crypto, forex) |

---

*Dernière mise à jour : juin 2026*
