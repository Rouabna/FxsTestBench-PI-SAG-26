# ✅ TEST FINAL — dossier à copier sur la carte SD (Pi)

Déploiement **production** pour la démonstration : mesure réelle + IA + dashboards
web/mobile + démarrage automatique. `DEMO_MODE` est déjà à **False** (mesure réelle).

> Prérequis : `fxs_real` **déjà validé** au premier test (`validate_fxs_real.py` → 8/8 OK).
> Travailler sur le **CLONE** de la carte de prod (cf. DEPLOY.md §0).

## Contenu
`app.py` (DEMO_MODE=False) · `fxs_real.py` · `fxs_ai.py` · `database.py`
`fxs_iso.joblib` · `requirements.txt` · `fxs_app.service` · `DEPLOY.md` (réf. complète)
`templates/` · `static/`

## Étapes

1. **Copier** ce dossier sur le Pi (clone) :  `/home/pi/fxs_app/`
2. **Dépendances** (sur le Pi, `python` = Python 2 → utiliser **`python3`**) :
   ```bash
   cd ~/fxs_app && python3 -m pip install -r requirements.txt
   ```
3. **App mobile** : dans `fxs-mobile/src/constants/config.js`, mettre
   `API_URL = 'http://<IP_DU_PI>:5000'` (IP via `hostname -I`).
4. **Démarrage automatique** (service systemd) :
   ```bash
   sudo cp ~/fxs_app/fxs_app.service /etc/systemd/system/fxs_app.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now fxs_app
   journalctl -u fxs_app -f          # logs en direct
   ```
   (Sans systemd : simplement `python3 app.py`.)
5. **Utiliser** : dashboard web `http://<IP_DU_PI>:5000` · app mobile (Expo).

## Règles d'exploitation
- **Arrêter le service avant de relancer LabVIEW** (mêmes GPIO/I2C) :
  `sudo systemctl stop fxs_app`.
- Si `raspi-gpio set` est refusé sous `pi` → passer `User=root` dans `fxs_app.service`.
- IA : si le bundle ne se charge pas (version scikit-learn), l'app continue et
  affiche « IA indisponible » ; la mesure n'est pas impactée.

Détails complets : voir **`DEPLOY.md`** (inclus dans ce dossier).
