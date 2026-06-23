"""
gateway_server.py — Serveur de pilotage gateway FXS, tournant sur le PC
=======================================================================
Sur une station de test-final (TF), le Pi est embarqué et figé dans le banc ; le
DUT (gateway) change à chaque unité testée. Pour ne JAMAIS reconfigurer le Pi par
gateway, on déporte TOUT le pilotage `scos-voice` sur le PC (operator station) :
le Pi (fxs_real, via gateway_voice) demande les opérations en HTTP, et c'est le PC
qui ouvre la session Telnet vers le gateway (192.168.5.1). Bénéfice secondaire :
lien PC↔gateway plus fiable que Pi↔gateway.

    Pi (fxs_real) ──HTTP──► PC (ce serveur) ──Telnet──► gateway (192.168.5.1)

UNE seule session Telnet est tenue ouverte pour toute la durée d'un test :
    /session/open  -> connexion + `scos-voice -b fxs init`  (énergise la ligne)
    /ring/start    -> ring start          (avant la sonnerie)
    /ring/stop     -> ring stop           (après la sonnerie)
    /p2p/start     -> p2p start           (avant la transmission, décroché)
    /session/close -> ferme la session    (fin du test)

Lancement :
    PC :   python gateway_server.py            # écoute sur 0.0.0.0:5050
    Pi :   export FXS_GW_URL=http://<ip-pc>:5050   (puis (re)lancer fxs_real / app.py)

Tolérance : si le gateway est injoignable, les endpoints renvoient 502 ; côté Pi,
gateway_voice logge un warning et la mesure continue (pilotage manuel possible).
"""

import logging
import threading

from flask import Flask, jsonify, request

import gateway_voice   # moteur Telnet partagé (mêmes commandes scos-voice)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("gateway_server")

app = Flask(__name__)

# Un seul banc -> un seul gateway -> une seule session Telnet à la fois.
_lock = threading.Lock()
_session = None          # gateway_voice.GatewayVoice actif, ou None


def _close_locked():
    """Ferme la session courante (à appeler sous _lock)."""
    global _session
    if _session is not None:
        try:
            _session.close()
        except Exception:
            pass
        _session = None


def _open_locked(do_init):
    """Ouvre une session neuve (init si demandé). À appeler sous _lock.
    Renvoie le GatewayVoice, ou lève si le gateway est injoignable."""
    global _session
    _close_locked()
    gw = gateway_voice.GatewayVoice()
    gw.connect()
    if do_init:
        gw.init()                 # énergise la ligne + POST_INIT_SETTLE
    _session = gw
    return gw


def _ensure_locked(do_init=True):
    """Renvoie la session ouverte ; en ouvre une (avec init) s'il n'y en a pas.
    Permet d'appeler /ring/start ou /p2p/start sans /session/open préalable."""
    if _session is None:
        return _open_locked(do_init)
    return _session


def _op(method_name, ensure=True):
    """Exécute une opération gateway sous verrou, avec tolérance + 502 si KO."""
    try:
        with _lock:
            gw = _ensure_locked() if ensure else _session
            if gw is None:
                return jsonify(ok=False, error="pas de session"), 409
            getattr(gw, method_name)()
        return jsonify(ok=True)
    except Exception as e:  # noqa: BLE001
        log.warning("%s échoué : %s", method_name, e)
        with _lock:
            _close_locked()       # session probablement morte -> on repart propre
        return jsonify(ok=False, error=str(e)), 502


@app.route("/health")
def health():
    return jsonify(ok=True, gateway=gateway_voice.GW_HOST,
                   session=_session is not None)


@app.route("/session/open", methods=["POST"])
def session_open():
    do_init = (request.get_json(silent=True) or {}).get("init", True)
    try:
        with _lock:
            _open_locked(do_init)
        return jsonify(ok=True)
    except Exception as e:  # noqa: BLE001
        log.warning("session/open échoué : %s", e)
        with _lock:
            _close_locked()
        return jsonify(ok=False, error=str(e)), 502


@app.route("/session/close", methods=["POST"])
def session_close():
    with _lock:
        _close_locked()
    return jsonify(ok=True)


@app.route("/ring/start", methods=["POST"])
def ring_start():
    return _op("ring_start")


@app.route("/ring/stop", methods=["POST"])
def ring_stop():
    return _op("ring_stop", ensure=False)   # inutile d'ouvrir une session pour stopper


@app.route("/p2p/start", methods=["POST"])
def p2p_start():
    return _op("p2p_start")


@app.route("/p2p/stop", methods=["POST"])
def p2p_stop():
    return _op("p2p_stop", ensure=False)


if __name__ == "__main__":
    log.info("=" * 60)
    log.info("  Serveur gateway PC — DUT %s — port 5050", gateway_voice.GW_HOST)
    log.info("  Pi : export FXS_GW_URL=http://<ip-pc>:5050")
    log.info("=" * 60)
    app.run(host="0.0.0.0", port=5050)
