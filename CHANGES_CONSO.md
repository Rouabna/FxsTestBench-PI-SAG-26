# Changements — Mesure de Consommation + Perte FXS1

Date : 2026-06-22

Ce document décrit les modifications apportées au banc de test FXS pour :
1. Appliquer une **perte de 1 dB** sur la mesure de transmission du port **FXS1**.
2. Ajouter une nouvelle mesure de **consommation** (niveau gateway) transcrite de `Conso.sh`.

---

## 1. Perte de 1 dB sur la transmission FXS1

**Fichier : `fxs_real.py` → `measure_trans()`**

La valeur de transmission est mesurée normalement, puis on lui **applique `-1`**
(`x - 1`, soit 1 dB de perte) **uniquement pour le port FXS1**. C'est cette valeur
ajustée qui est ensuite analysée contre les limites Sagem (8.1–10.1 dB à 1000 Hz)
pour décider du PASS/FAIL.

```python
db = -20.0 * math.log10(vs / ve)   # -> dB (atténuation)
if port == "FXS1":
    db -= 1.0                      # FXS1 : 1 dB de perte appliqué
return db
```

- FXS2 : inchangé.
- Exemple : une mesure ~9.1 dB devient ~8.1 dB (poussée en bas de bande).

---

## 2. Nouvelle mesure : Consommation (M_CONS_CONSUMPTION)

Mesure **niveau gateway** (pas par port), réalisée avec le capteur **DFRobot INA219**
(différent de l'ADS1115 utilisé pour les autres mesures).

- **Source** : `C:\Users\dell\OneDrive\Desktop\script reel_fxs\Conso.sh` (version active).
- **Séquence GPIO** : `18 dl` → sleep 0.1 → `25 dh` → lecture INA219.
- **Unité / limites** : **Watts (W)**, bande **7 – 20 W** (relevées du ROW_DATA :
  `M_CONS_CONSUMPTION`, Low Limit 7, High Limit 20, valeur typique ~12 W).
- Sur PC (simulation) : valeur ~12 W générée, ~10 % de cartes rendues atypiques.
- La conso **n'alimente pas l'IA** (`fxs_ai.py` est figé à 8 features) : c'est une
  porte seuil pure, comme dans l'export ROW_DATA.

### Fichiers modifiés

#### `fxs_real.py`
- Détection optionnelle de la lib INA219 (`HAVE_INA219`) ; repli simulation si
  absente, même sur le Pi (le reste des mesures continue en réel).
- Constantes `CONSO_MIN, CONSO_MAX = 7.0, 20.0` (W) et séquence `_CONSO_PREP`.
- `_Bench` : init INA219, `read_power()` (`get_power_mW()/1000 → W`) et `_sim_power()`.
- Nouvelle fonction `measure_conso(b)` → renvoie des watts.
- **Phase 4** dans `run_gateway_test` (après la transmission) : mesure la conso,
  remplit `conso_w` + le champ legacy `power`, calcule le verdict `pass_conso`,
  l'intègre dans le `final` global.
- `total_steps` : 8 → **9**.

#### `database.py`
- Nouvelles colonnes `conso_w REAL` et `pass_conso INTEGER`.
- Migration `ALTER TABLE` (`_CONSO_COLUMNS`) pour les bases existantes — pas de
  perte d'historique.
- Ajout aux `FIELDS` (persistance automatique via `save_test`).

#### `app.py`
- `conso_w` et `pass_conso` ajoutés à `EMPTY_STATE`.
- `total_steps` par défaut : 10 → **9** (cohérence avec `fxs_real`).

#### `templates/index.html`
- Nouvelle carte **« 5. Consommation »** (jauge gateway, plage `[7 - 20] W`).
- 5ᵉ étape « Consommation » dans la liste *Séquence de Test*.

#### `static/js/dashboard.js`
- `LIM.conso = [7, 20]`.
- Rendu de la jauge conso (niveau gateway) dans `updateMeasurements`.
- `updateStepsList` étendu à 5 étapes + statut `CONSO`.
- Tableau d'historique : colonne « Puissance » affichée en **W** (auparavant le
  champ `power` legacy — toujours vide — était rendu en mW).

---

## Vérifications effectuées

- `python -m py_compile fxs_real.py database.py app.py` → OK.
- Smoke test `run_gateway_test(simulate=True)` :
  - `conso_w` mesuré, `pass_conso` calculé, `power` rempli (W), `total_steps=9`.
  - perte `-1` appliquée sur la transmission FXS1.
- Migration DB : colonnes `conso_w` / `pass_conso` présentes dans `fxs_tests.db`.
