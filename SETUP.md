# Banc de Test FXS — SETUP & Exploitation

Référence opérationnelle du banc (mise à jour : 2026-06-22).
Pour l'historique détaillé des modifications, voir [SESSION_LOG.md](SESSION_LOG.md).

---

## 1. Architecture

```
   Pi (Raspberry)                  PC (station opérateur)              Gateway (DUT)
   app.py + fxs_real     ──HTTP──►  gateway_server.py      ──Telnet──►  192.168.5.1
   mesures ADS1115/GPIO   :5000     pilotage scos-voice      :5050      (scos-voice)
   dashboard web
```

- **Pi** : exécute `app.py` (Flask + SocketIO). Fait toutes les mesures (ADS1115 + GPIO
  via `raspi-gpio`) et sert le **dashboard web**. Lance `fxs_real.run_gateway_test()`.
- **PC** : exécute `gateway_server.py`. C'est lui qui ouvre la session **Telnet** vers le
  gateway (sonnerie / p2p via `scos-voice`). Le Pi lui parle en HTTP.
- **Gateway (DUT)** : l'unité testée. Change à chaque test. Joignable en Telnet **depuis le
  PC** (pas depuis le Pi).

---

## 2. Réseau (IP fixes)

| Machine / interface | IP | Rôle |
|---|---|---|
| **Pi** `eth0` | `192.168.100.10/24` | dashboard + mesures (IP statique) |
| **PC** `Wi-Fi` | `10.235.225.56/24` ✅ **statique** | pont (`bridge.js`) vers le Pi pour le téléphone |
| **PC** `Ethernet` | `192.168.100.50/24` | lien vers le Pi + `gateway_server` |
| **PC** `Ethernet 2` | `192.168.5.100/24` | lien vers le gateway (DUT) |
| **Gateway (DUT)** | `192.168.5.1` | cible Telnet `scos-voice` |

> Le Pi et le PC sont sur `192.168.100.0/24`. Le PC et le gateway sont sur `192.168.5.0/24`.
> Le PC fait le pont entre les deux (il a une carte sur chaque réseau).
>
> **IP Wi-Fi du PC fixée (2026-06-26)** : `10.235.225.56/24`, passerelle/DNS `10.235.225.157`,
> DHCP désactivé sur le Wi-Fi (adaptateur « Wi-Fi », MAC `74-12-B3-93-F5-77`). L'app mobile
> (`config.js`) et `bridge.js` pointent déjà sur cette adresse → elle ne changera plus au reboot.
> Revenir en DHCP (si le PC change de réseau Wi-Fi) :
> `netsh interface ip set address name="Wi-Fi" dhcp` + `netsh interface ip set dns name="Wi-Fi" dhcp` (admin).

**URLs :**
- Dashboard (à ouvrir dans le navigateur du PC) : **http://192.168.100.10:5000**
- Serveur gateway (santé) : http://192.168.100.50:5050/health

---

## 3. Démarrage automatique (rien à lancer à la main)

### Pi — service systemd `fxs_app`
`app.py` démarre au boot et redémarre en cas de crash.
- Fichier unité : `/etc/systemd/system/fxs_app.service`
- Variable `FXS_GW_URL=http://192.168.100.50:5050` (mode déporté) + fichier `.env`.

```bash
sudo systemctl status  fxs_app     # état (active = running)
sudo systemctl restart fxs_app     # après une modif de fxs_real.py / app.py
sudo systemctl stop    fxs_app     # AVANT de lancer LabVIEW (GPIO/I2C partagés)
sudo systemctl start   fxs_app
journalctl -u fxs_app -f           # logs en direct (q pour quitter)
```

### PC — `gateway_server.py` + `bridge.js`
Deux services lancés automatiquement à l'ouverture de session Windows via des raccourcis
dans le dossier de démarrage (`Win+R → shell:startup`) :

| Service | Script | Raccourci | Port | Rôle |
|---|---|---|---|---|
| **Serveur gateway** | `run_gateway_server.bat` (`C:\Python313\python.exe`) | `…\Startup\GatewayServer.lnk` | 5050 | Telnet vers le DUT |
| **Pont téléphone** ✅ | `run_bridge.bat` (`C:\nvm4w\nodejs\node.exe`) | `…\Startup\FxsBridge.lnk` | 5000 | relais Wi-Fi → Pi (téléphone) |

> `bridge.js` ajouté au démarrage auto le **2026-06-26** : sans lui, le téléphone ne joint
> pas le Pi après un reboot du PC. Lancement manuel : double-clic sur le `.bat` correspondant
> (`run_gateway_server.bat` dans `deploy_test_final/`, `run_bridge.bat` dans `fxs-mobile/`).

---

## 4. Lancer un test

1. PC allumé (le serveur gateway tourne tout seul) + Pi allumé (service `fxs_app`).
2. Ouvrir **http://192.168.100.10:5000** dans le navigateur du PC.
3. Cliquer **DÉMARRER** (ou `curl -X POST http://192.168.100.10:5000/api/start`).

> ⚠️ Lancer un test **uniquement via le dashboard / `app.py`**. `python3 fxs_real.py`
> en direct **n'enregistre pas** le résultat en base et, hors du bon shell, ne charge
> pas `FXS_GW_URL` (sonnerie KO).

---

## 5. Base de données

- Fichier : `/home/pi/deploy_test_final/fxs_tests.db` (**sur le Pi**, à côté de `database.py`).
- Écrite **uniquement** par `app.py` quand un test se termine (`status == DONE`).
- Le PC, s'il fait tourner `app.py`, aurait sa propre base séparée (non synchronisée).

```bash
sqlite3 ~/deploy_test_final/fxs_tests.db "SELECT COUNT(*) FROM test_runs;"
```

---

## 6. Particularités matérielles à connaître

- **Sonnerie = UNE rafale par `ring start`** (≈ 1,5 s), PAS une cadence répétée. Comme les
  2 ports sont mesurés en séquence, `fxs_real` **ré-déclenche `ring start` avant chaque
  port** et ne fait **qu'un seul `ring stop` à la fin**. Ne JAMAIS faire `ring stop` puis
  `ring start` rapprochés entre les ports : ça **fige la sonnerie** du gateway.
- **Transmission** : une perte de **−1 dB** est appliquée volontairement sur FXS1 **et**
  FXS2 avant le verdict (limites 1000 Hz : 8,1–10,1 dB).
- **Mode REEL vs SIMULATION** : `fxs_real` détecte le Pi (`ON_PI`). Sur PC sans ADS1115,
  il bascule en simulation (valeurs plausibles).

---

## 7. Dépannage rapide

| Symptôme | Cause probable | Fix |
|---|---|---|
| Dashboard ne s'ouvre pas | Pi sur IP APIPA `169.254.x.x` | vérifier `ip addr show eth0` = `192.168.100.10` |
| `Address already in use :5000` | un `app.py` tourne déjà | `pkill -f app.py` puis `systemctl restart fxs_app` |
| Sonnerie ne sonne pas (`No route to host`) | `FXS_GW_URL` absent (mode local) | lancer via `app.py` ; `echo $FXS_GW_URL` |
| Serveur PC `502` sur `/session/open` | PC ne joint pas le gateway | `ping 192.168.5.1` sur le PC ; `python gateway_voice.py` |
| `python` introuvable / Flask manquant (PC) | mauvais interpréteur | utiliser `C:\Python313\python.exe` |
| Modif de code sans effet (Pi) | service garde l'ancien code | `sudo systemctl restart fxs_app` |

Vérifier le mode de pilotage gateway : `curl http://192.168.100.10:5000/api/gateway`
→ doit renvoyer `"mode":"remote","reachable":true`.
