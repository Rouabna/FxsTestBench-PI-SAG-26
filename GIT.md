# Git — dépôts & déploiement

Versionnement et déploiement du banc FXS via Git. Voir aussi [SETUP.md](SETUP.md)
(exploitation) et [SESSION_LOG.md](SESSION_LOG.md) (historique des modifs).

---

## 1. Dépôts (2 repos séparés, privés)

| Repo | Contenu | URL |
|---|---|---|
| **Backend** (Pi) | `deploy_test_final` — Flask, mesures, IA, gateway, dashboard | https://github.com/Rouabna/FxsTestBench-PI-SAG-26 |
| **Mobile/Web** | `fxs-mobile` — app Expo / React Native Web | https://github.com/Rouabna/FxsTestBench-APP-SAG-26 |

> **Privés** : `gateway_voice.py` contient `GW_USER/GW_PASSWORD = "root"`. Ne pas
> rendre public tant que ce mot de passe est en dur dans le code.

**Branche** : `main` sur les deux.

### Fichiers NON versionnés (`.gitignore`)
- Backend : `fxs_tests.db` (données runtime), `__pycache__/`, `*.pyc`, logs.
  - Versionnés volontairement : `fxs_iso.joblib` (modèle IA), `fxs_train_normal.csv`,
    `.env` (juste l'IP LAN `FXS_GW_URL`, pas un secret).
- Mobile : `node_modules/`, `.expo/`, `dist/`, logs.

---

## 2. Workflow quotidien (remplace le scp)

```
PC  :  modifier le code  ->  git add -A  ->  git commit -m "..."  ->  git push
Pi  :  cd ~/deploy_test_final  ->  git pull  ->  sudo systemctl restart fxs_app
```

Un seul `git pull` sur le Pi remplace toutes les copies fichier-par-fichier.

### Sur le PC (backend)
```bash
cd /d/ing-pfe-bancTest/deploy_test_final     # (PowerShell : D:\ing-pfe-bancTest\deploy_test_final)
git add -A
git commit -m "Description claire du changement"
git push
```

### Sur le PC (mobile)
```bash
cd /d/ing-pfe-bancTest/fxs-mobile
git add -A
git commit -m "..."
git push
```

### Sur le Pi (récupérer + appliquer)
```bash
cd ~/deploy_test_final
git pull
rm -rf __pycache__           # évite tout bytecode périmé
sudo systemctl restart fxs_app
```

---

## 3. Installation initiale sur le Pi (une seule fois)

Transforme le dossier `~/deploy_test_final` (fichiers en vrac) en clone Git, **en
préservant la base de données** (l'historique ; la DB n'est pas dans le repo).

Le repo étant **privé**, créer d'abord un **Personal Access Token (PAT)** :
GitHub → Settings → Developer settings → Tokens → *Fine-grained token* → accès
**lecture** au repo backend.

```bash
# 0. git installé ?
sudo apt-get update && sudo apt-get install -y git

# 1. stopper le service + sauvegarder l'existant (garde la DB)
sudo systemctl stop fxs_app
cd ~
mv deploy_test_final deploy_test_final.bak

# 2. cloner dans le MÊME chemin que le service
git clone https://github.com/Rouabna/FxsTestBench-PI-SAG-26.git deploy_test_final
#    Username = Rouabna   |   Password = <coller le PAT>

# 3. restaurer la base (historique des tests)
cp deploy_test_final.bak/fxs_tests.db deploy_test_final/ 2>/dev/null || echo "pas de DB"

# 4. mémoriser le token (plus de re-saisie aux prochains pull) — banc dédié
git -C ~/deploy_test_final config credential.helper store

# 5. relancer
sudo systemctl restart fxs_app
systemctl status fxs_app          # active (running) attendu
```

Après vérification : `rm -rf ~/deploy_test_final.bak`.

> Le `.env` est versionné, donc présent après le clone. Le service `fxs_app` a de
> toute façon `FXS_GW_URL` dans son unité systemd.

---

## 4. Commandes utiles

```bash
git status                 # état (fichiers modifiés / non suivis)
git diff                   # voir les changements non encore "add"
git log --oneline -10      # 10 derniers commits
git pull                   # récupérer la dernière version (Pi)
git push                   # envoyer ses commits (PC)
git restore <fichier>      # annuler les modifs locales d'un fichier
git checkout -- .          # annuler TOUTES les modifs locales non commit
```

### Conflit au `git pull` (Pi modifié à la main)
Si le Pi a été édité localement et diverge :
```bash
git stash          # met de côté les modifs locales du Pi
git pull
git stash drop     # jeter les modifs locales (ou `git stash pop` pour les rejouer)
```
Bonne pratique : **ne plus éditer le code directement sur le Pi** — modifier sur le
PC, commit/push, puis `git pull` sur le Pi.

---

## 5. Notes

- **Mobile** : versionné pour le dev sur PC (`npm run web`) — **pas déployé sur le Pi**.
- **DB** : jamais versionnée ; vit uniquement sur le Pi (`fxs_tests.db`).
- **Modèle IA** (`fxs_iso.joblib`) : versionné → présent après chaque clone/pull.
- **Durcissement futur** : déplacer `GW_PASSWORD` dans `.env` pour retirer tout
  identifiant du code (le repo pourrait alors être public sans risque).
