"""
Banc de Test FXS — API Server + Web Interface
==============================================
Flask + SocketIO backend serving:
  - REST API  (/api/status, /api/start, /api/stop, /api/reset, /api/history)
  - WebSocket (real-time test updates)
  - Web dashboard (desktop browser at /)
  - Mobile app connects via same API + WebSocket

Usage on Raspberry Pi:
    pip install flask flask-socketio
    python app.py

Mobile (Expo) connects to:  http://<raspberry-pi-ip>:5000
"""

import os
import threading
import logging
from pathlib import Path
from datetime import datetime


def _load_dotenv():
    """Charge un fichier `.env` optionnel (KEY=VALUE) du dossier de l'app, AVANT
    d'importer gateway_voice (qui lit FXS_GW_URL au moment de l'import). Évite de
    devoir `export FXS_GW_URL=...` à la main à chaque lancement de `python3 app.py`.
    Un `export` explicite garde la priorité (setdefault n'écrase rien)."""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit

import database
import fxs_ai        # module IA : scoring Isolation Forest + explicabilité
import fxs_real      # séquence de test réelle par port (FXS1+FXS2), transcription prod
import gateway_voice # pilotage gateway (Telnet local ou déporté sur PC) + /health

# NB : plus aucune init GPIO/LED côté backend. La prod ne câble aucune LED et
# `fxs_real` pilote tous les GPIO (via raspi-gpio) pour le multiplexage de mesure.
# Toucher ces pins ici entrerait en conflit avec la mesure réelle.

# ─────────────────────────────────────────────
#  DEMO MODE
#  When True, /api/start runs fake_test_sequence() instead of the real one.
#  GPIO LEDs still light up on the bench; only the I2C reads are skipped and
#  values come from a randomised scenario (different every run).
#  Flip to False once the real signal path is wired and calibrated.
# ─────────────────────────────────────────────
DEMO_MODE = False

# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  FLASK APP
# ─────────────────────────────────────────────
app = Flask(__name__)
app.config['SECRET_KEY'] = 'fxs_test_bench_2026'
socketio = SocketIO(app, cors_allowed_origins="*")


@app.after_request
def _add_cors_headers(resp):
    # Autorise l'app mobile (Expo web, autre origine) à appeler l'API REST
    # (/api/status, /api/history, /api/start...). Sans ça le navigateur bloque
    # les fetch cross-origin -> historique/graphique vides.
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return resp

# ─────────────────────────────────────────────
#  SHARED STATE
# ─────────────────────────────────────────────
lock = threading.Lock()
stop_event = threading.Event()
_test_thread = None     # thread du test en cours (pour pouvoir le (re)démarrer)

# Default/empty state — keys match the results dict produced by
# fxs_real.run_gateway_test (par-port FXS1/FXS2) + verdict IA.
EMPTY_STATE = {
    # Mesures par port (gateway = FXS1 + FXS2)
    "tr_fxs1": None, "tr_fxs2": None,
    "cl_fxs1": None, "cl_fxs2": None,
    "alarm_rms_fxs1": None, "alarm_rms_fxs2": None,
    "trans_300_fxs1": None, "trans_1000_fxs1": None, "trans_3400_fxs1": None,
    "trans_300_fxs2": None, "trans_1000_fxs2": None, "trans_3400_fxs2": None,
    # Clés héritées (mono-ligne = FXS1) pour compat éventuelle
    "tr": None, "cl": None, "power": None, "alarm_rms": None,
    "trans_300": None, "trans_1000": None, "trans_3400": None,
    # Consommation gateway (M_CONS_CONSUMPTION, W) — niveau gateway
    "conso_w": None, "pass_conso": None,
    # Verdicts seuils (niveau gateway : ET des 2 ports)
    "pass_tr": None, "pass_cl": None, "pass_alarm": None, "pass_trans": None,
    "final": None, "slot": 1,
    # Verdict IA (rempli en fin de séquence par fxs_ai.analyze)
    "ai_available": None, "ai_score": None, "ai_atypical": None,
    "ai_verdict": None, "ai_culprit": None, "ai_culprit_pct": None,
    "status": "IDLE", "step": 0, "total_steps": 9, "timestamp": None,
}

test_state = dict(EMPTY_STATE)


def on_test_update(results):
    """Callback from fxs_real.run_gateway_test — pushes to web clients."""
    with lock:
        test_state.update(results)
    socketio.emit('test_update', results)


def reset_state():
    """Reset all test state to idle (témoins d'avancement = logiciels)."""
    with lock:
        test_state.clear()
        test_state.update(EMPTY_STATE)


# ─────────────────────────────────────────────
#  ROUTES
# ─────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/status')
def api_status():
    with lock:
        return jsonify(dict(test_state))


@app.route('/api/history')
def api_history():
    limit = request.args.get('limit', default=20, type=int)
    return jsonify(database.get_history(limit))


@app.route('/api/stats')
def api_stats():
    return jsonify(database.get_stats())


@app.route('/api/gateway')
def api_gateway():
    """Statut du pilotage gateway pour l'app mobile :
      - mode 'local'  : le Pi telnet le gateway directement (FXS_GW_URL non défini).
      - mode 'remote' : sonnerie déportée sur le PC ; `reachable` dit si le serveur
                        PC (gateway_server.py) répond -> prévient l'opérateur AVANT
                        de lancer un test si la sonnerie/p2p ne marchera pas."""
    url = gateway_voice.GW_SERVER_URL
    if not url:
        return jsonify(mode="local", url=None, reachable=None,
                       gateway=gateway_voice.GW_HOST)
    h = gateway_voice.gateway_health()
    return jsonify(mode="remote", url=url,
                   reachable=bool(h and h.get("ok")),
                   gateway=(h or {}).get("gateway", gateway_voice.GW_HOST))


@app.route('/api/start', methods=['POST'])
def api_start():
    global _test_thread

    # (RE)DÉMARRAGE : si un test tourne déjà, on l'arrête proprement d'abord, puis
    # on relance un test neuf. Cliquer START redémarre donc toujours.
    if _test_thread is not None and _test_thread.is_alive():
        stop_event.set()
        _test_thread.join(timeout=8)
    stop_event.clear()
    reset_state()

    def _run():
        try:
            # Séquence réelle par port (FXS1+FXS2). En DEMO_MODE on force le
            # simulateur de fxs_real (valeurs plausibles, sans matériel) ; sinon
            # fxs_real auto-détecte le Pi (ADS1115 + raspi-gpio).
            results = fxs_real.run_gateway_test(
                notify_callback=on_test_update,
                stop_check=stop_event.is_set,
                simulate=True if DEMO_MODE else None,
                slot=1,
            )

            # On ne traite/enregistre que les tests RÉELLEMENT terminés (pas les
            # tests interrompus par un redémarrage).
            if results.get("status") == "DONE":
                # ── Analyse IA : signale les cartes dans les limites mais
                #    atypiques (dérive). Jamais bloquant pour le banc.
                try:
                    ai = fxs_ai.analyze(results)
                    results.update(ai)
                    with lock:
                        test_state.update(ai)
                    socketio.emit('test_update', dict(results))
                    log.info(f"   IA : {ai['ai_verdict']} "
                             f"(score {ai['ai_score']}, cause {ai['ai_culprit']})")
                except Exception:
                    log.exception("Analyse IA echouee (non bloquant)")

                entry = dict(results)
                entry["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                database.save_test(entry)
        except Exception as e:
            log.exception("Test sequence error")
            with lock:
                test_state["status"] = "ERROR"
                test_state["final"] = False
            socketio.emit('test_update', {"status": "ERROR", "error": str(e)})

    _test_thread = threading.Thread(target=_run, daemon=True)
    _test_thread.start()
    return jsonify({"message": "Test started"})


@app.route('/api/stop', methods=['POST'])
def api_stop():
    """Request that the running sequence aborts at the next safe checkpoint."""
    stop_event.set()
    log.info("STOP requested from web UI")
    return jsonify({"message": "Stop requested"})


@app.route('/api/reset', methods=['POST'])
def api_reset():
    reset_state()
    with lock:
        socketio.emit('test_update', dict(test_state))
    return jsonify({"message": "Reset OK"})


@socketio.on('connect')
def on_connect():
    with lock:
        emit('test_update', dict(test_state))


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    log.info("=" * 50)
    log.info("  FXS TEST BENCH - Starting up")
    log.info("=" * 50)

    # Database init
    database.init_db()
    log.info(f"Database ready at {database.DB_PATH}")

    # IA init — charge le bundle Isolation Forest au démarrage
    try:
        b = fxs_ai.load()
        log.info(f"Modele IA charge ({b['_path']}, seuil {b['threshold']:.3f})")
    except Exception as e:
        log.warning(f"Modele IA NON charge : {e} — le banc tournera sans verdict IA")

    # La mesure passe par fxs_real (I2C ADS1115 + GPIO via raspi-gpio, comme la
    # prod). Aucune init GPIO/LED/smbus ici : ces pins servent au multiplexage de
    # mesure et fxs_real les gère lui-même au moment de la séquence.
    if DEMO_MODE:
        log.warning("DEMO MODE actif — fxs_real tournera en SIMULATION")
    elif not fxs_real.ON_PI:
        log.warning("Hors Raspberry Pi — fxs_real basculera en SIMULATION")
    else:
        log.info("Mode REEL — fxs_real (ADS1115 + raspi-gpio)")

    log.info("Server starting on port 5000")

    try:
        socketio.run(app, host="0.0.0.0", port=5000, debug=False,
                     allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        log.info("Shutting down...")
    finally:
        log.info("Cleanup complete")
