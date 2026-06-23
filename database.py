"""
SQLite persistence for FXS test results.
Stores every completed test run so history survives reboots.

NOTE: schema was updated when the test sequence was rewritten (TR/CL/alarme/
transmission instead of v_repos/i_line/dial_rms/audio_*). If an old
fxs_tests.db file exists from before that change, delete it so the new schema
is created on the next run.
"""

import sqlite3
import threading
from pathlib import Path

DB_PATH = Path(__file__).parent / "fxs_tests.db"
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS test_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,
    -- valeurs héritées (mono-ligne = FXS1 ; cl en Ampères)
    tr          REAL,
    cl          REAL,
    power       REAL,
    alarm_rms   REAL,
    trans_300   REAL,
    trans_1000  REAL,
    trans_3400  REAL,
    -- valeurs PAR PORT (unités modèle ; cl_fxs* en mA)
    tr_fxs1 REAL, tr_fxs2 REAL,
    cl_fxs1 REAL, cl_fxs2 REAL,
    alarm_rms_fxs1 REAL, alarm_rms_fxs2 REAL,
    trans_300_fxs1 REAL, trans_1000_fxs1 REAL, trans_3400_fxs1 REAL,
    trans_300_fxs2 REAL, trans_1000_fxs2 REAL, trans_3400_fxs2 REAL,
    -- verdicts seuils (niveau gateway) + statut
    pass_tr     INTEGER,
    pass_cl     INTEGER,
    pass_alarm  INTEGER,
    pass_trans  INTEGER,
    -- consommation gateway (M_CONS_CONSUMPTION, W)
    conso_w     REAL,
    pass_conso  INTEGER,
    final       INTEGER,
    status      TEXT,
    -- verdict IA (niveau gateway)
    ai_score    REAL,                -- score d'anomalie Isolation Forest
    ai_atypical INTEGER,             -- 1 = carte atypique (dérive) selon l'IA
    ai_verdict  TEXT,                -- libellé verdict IA
    ai_culprit  TEXT,                -- mesure la plus contributive
    ai_relevant INTEGER,             -- 1 = carte PASS (IA pertinente) ; 0 = ECHEC (cause par seuils)
    ai_recommendation TEXT,          -- recommandation maintenance (texte)
    ai_severity TEXT,                -- OK / WATCH / ALERT / FAIL (marge + IA)
    ai_min_margin REAL               -- % marge de la mesure la plus proche du seuil
);
CREATE INDEX IF NOT EXISTS idx_test_runs_timestamp ON test_runs(timestamp DESC);
"""

# Colonnes ajoutées après coup : migrées via ALTER TABLE sur les bases existantes
# (voir init_db) pour ne pas perdre l'historique déjà enregistré.
_AI_COLUMNS = {
    "ai_score": "REAL",
    "ai_atypical": "INTEGER",
    "ai_verdict": "TEXT",
    "ai_culprit": "TEXT",
    "ai_relevant": "INTEGER",
    "ai_recommendation": "TEXT",
    "ai_severity": "TEXT",
    "ai_min_margin": "REAL",
}
_CONSO_COLUMNS = {
    "conso_w": "REAL",
    "pass_conso": "INTEGER",
}
_PORT_COLUMNS = {
    "tr_fxs1": "REAL", "tr_fxs2": "REAL",
    "cl_fxs1": "REAL", "cl_fxs2": "REAL",
    "alarm_rms_fxs1": "REAL", "alarm_rms_fxs2": "REAL",
    "trans_300_fxs1": "REAL", "trans_1000_fxs1": "REAL", "trans_3400_fxs1": "REAL",
    "trans_300_fxs2": "REAL", "trans_1000_fxs2": "REAL", "trans_3400_fxs2": "REAL",
}

FIELDS = [
    "timestamp",
    "tr", "cl", "power",
    "alarm_rms",
    "trans_300", "trans_1000", "trans_3400",
    # par port (FXS1 + FXS2)
    "tr_fxs1", "tr_fxs2", "cl_fxs1", "cl_fxs2",
    "alarm_rms_fxs1", "alarm_rms_fxs2",
    "trans_300_fxs1", "trans_1000_fxs1", "trans_3400_fxs1",
    "trans_300_fxs2", "trans_1000_fxs2", "trans_3400_fxs2",
    "pass_tr", "pass_cl", "pass_alarm", "pass_trans",
    "conso_w", "pass_conso",
    "final", "status",
    "ai_score", "ai_atypical", "ai_verdict", "ai_culprit",
    "ai_relevant", "ai_recommendation", "ai_severity", "ai_min_margin",
]


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _lock, _connect() as conn:
        conn.executescript(SCHEMA)
        # Migration : ajouter les colonnes IA + par-port si la base est antérieure.
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(test_runs)")}
        for col, col_type in {**_AI_COLUMNS, **_PORT_COLUMNS, **_CONSO_COLUMNS}.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE test_runs ADD COLUMN {col} {col_type}")


def save_test(entry: dict) -> int:
    """Insert one completed test run. Returns new row id."""
    values = [entry.get(f) for f in FIELDS]
    placeholders = ",".join("?" * len(FIELDS))
    cols = ",".join(FIELDS)
    with _lock, _connect() as conn:
        cur = conn.execute(
            f"INSERT INTO test_runs ({cols}) VALUES ({placeholders})",
            values,
        )
        return cur.lastrowid


def get_history(limit: int = 20) -> list[dict]:
    """Return most recent tests (newest first)."""
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM test_runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_stats() -> dict:
    """Aggregate counts for dashboard stats bar."""
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN final=1 THEN 1 ELSE 0 END) AS passed, "
            "SUM(CASE WHEN final=0 THEN 1 ELSE 0 END) AS failed "
            "FROM test_runs"
        ).fetchone()
    return {
        "total": row["total"] or 0,
        "passed": row["passed"] or 0,
        "failed": row["failed"] or 0,
    }
