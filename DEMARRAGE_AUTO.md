# Démarrage automatique du banc de test FXS

## Objectif

Le banc fait intervenir **deux machines** et **trois programmes** :

1. le **serveur gateway** sur le PC (pilotage de la sonnerie / point-à-point du DUT) ;
2. le **backend** sur le Raspberry Pi (mesures + serveur web) ;
3. l'**application** de supervision (dashboard web et application mobile).

À l'origine, il fallait lancer ces éléments **manuellement et dans le bon ordre**
(serveur PC → backend Pi → application), ce qui était contraignant et source
d'erreurs (oubli, mauvais ordre, mauvaise adresse réseau…).

La configuration mise en place rend le démarrage **automatique** : les deux services
se lancent seuls à l'allumage des machines. L'opérateur n'a plus qu'à **ouvrir
l'application et appuyer sur « DÉMARRER »**.

## Architecture

```
   Raspberry Pi                         PC (poste opérateur)              Gateway (DUT)
   backend (app.py)        ──HTTP──►     serveur (gateway_server.py)  ──Telnet──►  unité testée
   mesures + dashboard      :5000        pilotage sonnerie / p2p        :5050
   192.168.100.10                        192.168.100.50
```

- Le **Pi** réalise les mesures (tension de repos, courant de ligne, sonnerie,
  transmission, consommation) et héberge le tableau de bord web.
- Le **PC** pilote le gateway (commandes `scos-voice` par Telnet) à la demande du Pi.
- L'**application** (web ou mobile) se connecte au backend du Pi pour afficher les
  résultats en temps réel.

## Ce qui démarre automatiquement

| Machine | Programme | Mécanisme de démarrage automatique |
|---|---|---|
| **Raspberry Pi** | `app.py` (backend) | **Service systemd** `fxs_app` — lancé au démarrage du Pi, **redémarré automatiquement** en cas d'arrêt anormal. |
| **PC** | `gateway_server.py` (serveur gateway) | **Raccourci** dans le dossier *Démarrage* de Windows — lancé à l'ouverture de session. |

L'**application** n'a pas besoin de démarrage automatique : c'est l'interface que
l'opérateur ouvre lui-même (page web ou application mobile).

## Étapes d'utilisation (de la mise sous tension à la mesure)

1. **Allumer le PC** et ouvrir la session Windows.
   → le serveur gateway (`gateway_server.py`) se lance **automatiquement**.
2. **Allumer le Raspberry Pi.**
   → le backend (`app.py`) se lance **automatiquement** (service `fxs_app`) et la
   ligne du gateway est énergisée.
3. **Ouvrir l'application** :
   - tableau de bord web : `http://192.168.100.10:5000` (navigateur du PC), ou
   - application mobile/web (Expo) connectée à la même adresse.
4. **Appuyer sur « DÉMARRER »** pour lancer une séquence de test complète
   (FXS1 + FXS2). Les résultats s'affichent en temps réel et sont enregistrés
   dans l'historique.

> Aucune commande à taper, aucun ordre de lancement à respecter : tout est prêt
> dès que les deux machines sont allumées.

## Comment c'est mis en place (configuration)

### Côté Raspberry Pi — service systemd
Un fichier d'unité `fxs_app.service` (dans `/etc/systemd/system/`) décrit le service :
il exécute `app.py`, le **relance en cas d'échec**, et est **activé au démarrage**.

```bash
sudo systemctl enable --now fxs_app     # activer (au boot) + démarrer maintenant
systemctl status  fxs_app               # vérifier : « active (running) »
journalctl -u     fxs_app -f            # consulter les journaux en direct
```

Gestion courante :
```bash
sudo systemctl stop    fxs_app          # arrêter (ex. avant d'utiliser LabVIEW)
sudo systemctl restart fxs_app          # relancer (ex. après une mise à jour du code)
```

### Côté PC — démarrage Windows
Un script `run_gateway_server.bat` lance `gateway_server.py` avec le bon interpréteur
Python. Un **raccourci** vers ce script est placé dans le dossier de démarrage de
Windows (accessible via `Win + R` → `shell:startup`) : le serveur se lance donc à
chaque ouverture de session.

## Remarques

- Le banc tolère l'indisponibilité momentanée d'un élément : si le serveur PC n'est
  pas joignable, la mesure continue (pilotage sonnerie manuel possible).
- En cas de mise à jour du code : `git pull` sur le Pi puis `sudo systemctl restart fxs_app`.
- Ne pas faire tourner `app.py` **et** LabVIEW en même temps (ils partagent les mêmes
  GPIO/I2C) : arrêter le service `fxs_app` avant de lancer LabVIEW.
