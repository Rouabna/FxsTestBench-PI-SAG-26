/* ═══════════════════════════════════════════════
   Banc de Test FXS — Dashboard JavaScript
   Real-time updates via Socket.IO
   Result-dict keys: tr, cl, power, alarm_rms, trans_300/1000/3400
   ═══════════════════════════════════════════════ */

const socket = io();

// ── Clock ──
setInterval(() => {
  document.getElementById('clock').textContent =
    new Date().toLocaleTimeString('fr-FR', {
      hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
}, 1000);

// ── Controls ──
function startTest() {
  // START (re)démarre toujours : le backend arrête un test en cours et relance.
  fetch('/api/start', { method: 'POST' })
    .then(r => r.json())
    .then(d => { if (d.error) alert(d.error); })
    .catch(() => {});
}

function resetTest() {
  fetch('/api/reset', { method: 'POST' })
    .then(r => r.json())
    .then(() => {
      document.getElementById('btnStart').disabled = false;
    });
}

// ── Format helpers ──
function fmtV(v)    { return v != null ? v.toFixed(2)            : '---'; }  // volts
function fmtMA(v)   { return v != null ? (v * 1000).toFixed(2)   : '---'; }  // amperes -> mA
function fmtMW(v)   { return v != null ? (v * 1000).toFixed(2)   : '---'; }  // watts -> mW
function fmtVRMS(v) { return v != null ? v.toFixed(2)            : '---'; }  // V RMS
function fmtDB(v)   { return v != null ? v.toFixed(2)            : '---'; }  // dB

function passClass(v) { return v === true ? 'pass' : v === false ? 'fail' : ''; }
function passText(v)  { return v === true ? 'PASS' : v === false ? 'FAIL' : '--'; }

function barPct(val, min, max) {
  if (val == null) return 0;
  const span = max - min;
  // visualise the [min..max] band as the middle of the bar
  return Math.min(100, Math.max(0, ((val - (min - span)) / (span * 3)) * 100));
}

// ── Status label map ──
const STATUS_LABELS = {
  'IDLE':      'En attente',
  'RUNNING':   'Initialisation...',
  'RING_WAIT': 'Sonnerie : envoyez la commande telephone...',
  'STOPPED':   'Sequence interrompue',
  'DONE':      'Sequence terminee',
  'ERROR':     'Erreur'
};

// fxs_real émet des statuts par port : TR_FXS1, CL_FXS2, RING_FXS1, TRANS_FXS2...
function statusLabel(s) {
  if (!s) return '';
  if (STATUS_LABELS[s]) return STATUS_LABELS[s];
  var m = s.match(/^(TR|CL|RING|TRANS)_(FXS\d)$/);
  if (m) {
    var name = { TR: 'Tension de repos', CL: 'Courant de ligne',
                 RING: 'Sonnerie', TRANS: 'Transmission' }[m[1]];
    return name + ' — ' + m[2];
  }
  return s;
}

// ── Socket events ──
socket.on('test_update', function(d) { updateUI(d); });

// Load on page open
fetch('/api/status').then(r => r.json()).then(d => updateUI(d));

// ── Main UI update ──
function updateUI(d) {
  updateStatusBadge(d);
  updateProgressBar(d);
  updateMeasurements(d);
  updateStepsList(d);
  updateLEDs(d);
  updateFinalResult(d);
  updateAI(d);
  loadHistory();
}

// ── Verdict IA (Isolation Forest) ──
function updateAI(d) {
  var ind = document.getElementById('ind_ai');
  var vEl = document.getElementById('ai_verdict');
  var sEl = document.getElementById('ai_score');
  var tEl = document.getElementById('ai_threshold');
  var cEl = document.getElementById('ai_culprit');
  var nEl = document.getElementById('ai_note');
  var scoreRow = document.getElementById('ai_score_row');
  var culpritRow = document.getElementById('ai_culprit_row');
  var recoLabel = document.getElementById('ai_reco_label');
  var svEl = document.getElementById('ai_severity');
  var mgEl = document.getElementById('ai_margin');
  var mgRow = document.getElementById('ai_margin_row');
  ind.className = 'indicator';
  // Par défaut on montre score + cause + marge (rétabli à chaque update).
  if (scoreRow) scoreRow.style.display = '';
  if (culpritRow) culpritRow.style.display = '';
  if (mgRow) mgRow.style.display = '';
  if (recoLabel) recoLabel.textContent = 'Recommandation maintenance';

  var SEV_COLOR = { OK: 'var(--pass-green)', WATCH: '#e0a000', ALERT: '#ff7a18', FAIL: 'var(--fail-red)' };

  // Pas encore de verdict (test en cours / idle / interrompu)
  if (d.ai_score == null && d.ai_available == null) {
    vEl.textContent = (d.status === 'DONE') ? '--' : 'En attente';
    vEl.className = 'gauge-value';
    sEl.textContent = '---'; tEl.textContent = '';
    cEl.textContent = '---'; nEl.textContent = '';
    if (svEl) { svEl.textContent = '--'; svEl.style.color = ''; }
    if (mgEl) mgEl.textContent = '---';
    return;
  }

  if (d.ai_available === false) {
    vEl.textContent = 'IA indisponible';
    vEl.className = 'gauge-value';
    ind.classList.add('fail');
    sEl.textContent = '---'; tEl.textContent = '';
    cEl.textContent = '---'; nEl.textContent = d.ai_error || '';
    if (svEl) { svEl.textContent = '--'; svEl.style.color = ''; }
    if (mgEl) mgEl.textContent = '---';
    if (mgRow) mgRow.style.display = 'none';
    return;
  }

  var atypical = d.ai_atypical === true;
  vEl.textContent = d.ai_verdict || '--';
  vEl.className = 'gauge-value ' + (atypical ? 'fail' : 'pass');
  ind.classList.add(atypical ? 'fail' : 'pass');

  sEl.textContent = d.ai_score;
  tEl.textContent = d.ai_threshold != null ? '(seuil ' + d.ai_threshold + ')' : '';
  cEl.textContent = (d.ai_culprit || '---') +
                    (d.ai_culprit_pct != null ? ' (' + d.ai_culprit_pct + '%)' : '');

  // Sévérité (OK / WATCH / ALERT / FAIL) + couleur.
  if (svEl) {
    svEl.textContent = d.ai_severity || '--';
    svEl.style.color = SEV_COLOR[d.ai_severity] || '';
  }
  // Marge mini au seuil (mesure la plus proche de sa limite).
  if (mgEl) {
    mgEl.textContent = (d.ai_min_margin != null)
      ? d.ai_min_margin + '%  ·  ' + (d.ai_min_margin_measure || '--')
      : '---';
  }

  // L'IA n'est pertinente que sur une carte QUI PASSE : sur un ECHEC (ai_relevant
  // === false), la cause vient des seuils -> on masque score/cause/marge et on
  // affiche juste la cause déterministe.
  if (d.ai_relevant === false) {
    if (scoreRow) scoreRow.style.display = 'none';
    if (culpritRow) culpritRow.style.display = 'none';
    if (mgRow) mgRow.style.display = 'none';
    if (recoLabel) recoLabel.textContent = 'Echec - cause par les seuils';
  }

  // Recommandation maintenance : texte fourni par le backend (fxs_ai), avec repli.
  if (d.ai_recommendation)
    nEl.textContent = d.ai_recommendation;
  else if (atypical && d.final === true)
    nEl.textContent = 'Carte conforme aux seuils mais atypique : a surveiller (derive precoce).';
  else if (atypical)
    nEl.textContent = 'Carte atypique par rapport au profil des cartes normales.';
  else
    nEl.textContent = 'Carte conforme au profil normal.';
}

function updateStatusBadge(d) {
  const badge = document.getElementById('statusBadge');
  badge.textContent = d.status;
  badge.className = 'status-badge';

  if (d.status === 'IDLE')
    badge.classList.add('status-idle');
  else if (d.status === 'DONE' && d.final === true)
    badge.classList.add('status-pass');
  else if (d.status === 'DONE' && d.final === false)
    badge.classList.add('status-fail');
  else if (d.status === 'ERROR')
    badge.classList.add('status-error');
  else
    badge.classList.add('status-running');
}

function updateProgressBar(d) {
  const step  = d.step || 0;
  const total = d.total_steps || 5;
  const pct   = d.status === 'DONE' ? 100 : (step / total * 100);

  document.getElementById('progressBar').style.width = pct + '%';
  document.getElementById('progressLabel').textContent = statusLabel(d.status);
}

// Limites Sagem (unités modèle) pour le PASS/FAIL côté client, par port.
const LIM = { tr: [44, 50], cl: [33, 39], alarm: [35, 41], trans: [8.1, 10.1], conso: [7, 20] };
function inRange(v, lo, hi) { return v != null ? (v >= lo && v <= hi) : null; }

function setPortGauge(prefix, port, val, unit, lo, hi) {
  var id = prefix + '_' + port;
  var ok = inRange(val, lo, hi);
  var g = document.getElementById('val_' + id);
  if (g) {
    g.innerHTML = (val != null ? val.toFixed(2) : '---') +
                  '<span class="gauge-unit"> ' + unit + '</span>';
    g.className = 'gauge-value ' + passClass(ok);
  }
  var r = document.getElementById('res_' + id);
  if (r) { r.textContent = passText(ok); r.className = 'step-result ' + passClass(ok); }
  var b = document.getElementById('bar_' + id);
  if (b) { b.style.width = barPct(val, lo, hi) + '%'; b.className = 'bar-gauge-fill ' + passClass(ok); }
}

function updateMeasurements(d) {
  var sn = document.getElementById('slotNum');
  if (sn && d.slot != null) sn.textContent = d.slot;

  ['fxs1', 'fxs2'].forEach(function(p) {
    setPortGauge('tr',    p, d['tr_' + p],        'V',    LIM.tr[0],    LIM.tr[1]);
    setPortGauge('cl',    p, d['cl_' + p],        'mA',   LIM.cl[0],    LIM.cl[1]);
    setPortGauge('alarm', p, d['alarm_rms_' + p], 'Vrms', LIM.alarm[0], LIM.alarm[1]);

    // Transmission : 3 fréquences en cellules de tableau ; PASS/FAIL sur 1000 Hz.
    ['300', '1000', '3400'].forEach(function(f) {
      var cell = document.getElementById('val_trans_' + f + '_' + p);
      if (!cell) return;
      var v = d['trans_' + f + '_' + p];
      cell.textContent = v != null ? v.toFixed(2) + ' dB' : '---';
      var ok = (f === '1000') ? inRange(v, LIM.trans[0], LIM.trans[1]) : null;
      cell.className = ok === true ? 'pass' : ok === false ? 'fail' : '';
    });
    var okT = inRange(d['trans_1000_' + p], LIM.trans[0], LIM.trans[1]);
    var rr = document.getElementById('res_trans_' + p);
    if (rr) { rr.textContent = passText(okT); rr.className = 'step-result ' + passClass(okT); }
  });

  // Consommation : niveau gateway (une seule valeur, pas par port).
  var cv = d.conso_w, okC = inRange(cv, LIM.conso[0], LIM.conso[1]);
  var cg = document.getElementById('val_conso');
  if (cg) {
    cg.innerHTML = (cv != null ? cv.toFixed(2) : '---') + '<span class="gauge-unit"> W</span>';
    cg.className = 'gauge-value ' + passClass(okC);
  }
  var cr = document.getElementById('res_conso');
  if (cr) { cr.textContent = passText(okC); cr.className = 'step-result ' + passClass(okC); }
  var cb = document.getElementById('bar_conso');
  if (cb) { cb.style.width = barPct(cv, LIM.conso[0], LIM.conso[1]) + '%'; cb.className = 'bar-gauge-fill ' + passClass(okC); }
}

// Étapes : 4 niveau gateway (ET des 2 ports) + conso (niveau gateway). Statut par fxs_real.
function updateStepsList(d) {
  var passes = [d.pass_tr, d.pass_cl, d.pass_alarm, d.pass_trans, d.pass_conso];
  var active = { TR: 1, CL: 2, RING: 3, TRANS: 4, CONSO: 5 };
  var cur = 0;
  var m = (d.status || '').match(/^(TR|CL|RING|TRANS)_FXS\d$/);
  if (m) cur = active[m[1]];
  else if (d.status === 'CONSO') cur = active.CONSO;

  for (var i = 1; i <= 5; i++) {
    var el    = document.getElementById('step' + i);
    var resEl = document.getElementById('step' + i + '_res');
    if (!el) continue;
    el.className = 'step-item';
    var p = passes[i - 1];

    if (d.status === 'DONE') {
      el.classList.add(p === false ? 'done-fail' : 'done-pass');
      resEl.textContent = passText(p);
      resEl.className = 'step-result ' + passClass(p);
    } else if (cur === i) {
      el.classList.add('active');
      resEl.textContent = '...';
      resEl.className = 'step-result';
    } else if (cur > i || p != null) {
      el.classList.add(p === false ? 'done-fail' : 'done-pass');
      resEl.textContent = passText(p);
      resEl.className = 'step-result ' + passClass(p);
    } else {
      resEl.textContent = '';
      resEl.className = 'step-result';
    }
  }
}

// Témoin d'avancement (LOGICIEL, pas de LED matérielle) :
// une pastille s'allume quand la mesure a été EFFECTUÉE (valeur présente),
// par mesure et par port. Le banc de prod ne câble aucune LED — ces pins
// servent au multiplexage de mesure.
var DONE_MEAS = [
  { key: 'tr',         label: 'TR',    color: '#00d4ff' },
  { key: 'cl',         label: 'CL',    color: '#2ee6a6' },
  { key: 'alarm_rms',  label: 'Ring',  color: '#b366ff' },
  { key: 'trans_1000', label: 'Trans', color: '#ff6ec7' }
];
var DONE_PORTS = ['FXS1', 'FXS2'];

function updateLEDs(d) {
  var grid = document.getElementById('doneGrid');
  if (!grid) return;

  // Mesure en cours (statut "TR_FXS1" ...) -> affichée "active".
  var m = (d.status || '').match(/^(TR|CL|RING|TRANS)_(FXS\d)$/);
  var activeKey = m ? { TR:'tr', CL:'cl', RING:'alarm_rms', TRANS:'trans_1000' }[m[1]] : null;
  var activePort = m ? m[2] : null;

  var done = 0;
  grid.innerHTML = '';
  DONE_PORTS.forEach(function(port) {
    var p = port.toLowerCase();
    var leds = DONE_MEAS.map(function(me) {
      var on = d[me.key + '_' + p] != null;
      if (on) done++;
      var active = !on && activeKey === me.key && activePort === port;
      var cls = 'done-dot' + (on ? ' on' : active ? ' active' : '');
      return '<div class="done-led" style="color:' + me.color + '">' +
               '<div class="' + cls + '"></div>' +
               '<span class="done-led-label">' + me.label + '</span>' +
             '</div>';
    }).join('');
    grid.innerHTML +=
      '<div class="done-port-row"><span class="done-port-tag">' + port + '</span>' +
      '<div class="done-leds">' + leds + '</div></div>';
  });

  var dc = document.getElementById('doneCount');
  if (dc) dc.innerHTML = 'allume = faite &bull; ' + done + '/8';
}

function updateFinalResult(d) {
  var fr = document.getElementById('finalResult');
  var ft = document.getElementById('finalText');
  var fs = document.getElementById('finalSub');

  fr.className = 'final-result';

  if (d.status === 'DONE') {
    fr.classList.add(d.final ? 'pass' : 'fail');
    ft.textContent = d.final ? 'PASS' : 'FAIL';
    ft.className = 'final-text ' + (d.final ? 'pass' : 'fail');
    fs.textContent = d.timestamp || '';
    document.getElementById('btnStart').disabled = false;
  } else if (d.status === 'IDLE') {
    ft.textContent = 'EN ATTENTE';
    ft.className = 'final-text idle';
    fs.textContent = 'Appuyez sur DEMARRER pour lancer la sequence';
  } else if (d.status === 'STOPPED') {
    ft.textContent = 'STOPPED';
    ft.className = 'final-text idle';
    fs.textContent = 'Sequence interrompue';
    document.getElementById('btnStart').disabled = false;
  } else if (d.status === 'ERROR') {
    ft.textContent = 'ERREUR';
    ft.className = 'final-text fail';
    fs.textContent = 'Erreur durant le test';
    document.getElementById('btnStart').disabled = false;
  } else {
    ft.textContent = 'TEST EN COURS';
    ft.className = 'final-text idle';
    fs.textContent = statusLabel(d.status);
  }
}

function loadHistory() {
  fetch('/api/history')
    .then(r => r.json())
    .then(function(hist) {
      var tbody = document.getElementById('historyBody');
      tbody.innerHTML = '';

      hist.reverse().forEach(function(h, idx) {
        var passColor   = h.final ? 'var(--pass-green)' : 'var(--fail-red)';
        var audioColor  = h.pass_trans ? 'var(--pass-green)' : 'var(--fail-red)';
        var trans1000   = h.trans_1000 != null ? h.trans_1000.toFixed(2) + ' dB' : '-';

        // Colonne IA : ATYPIQUE (orange) / OK (vert) / - si non score
        var aiText = '-', aiColor = 'var(--text-dim, #888)';
        if (h.ai_atypical === 1)      { aiText = 'ATYPIQUE'; aiColor = 'var(--warn-orange, #e08a00)'; }
        else if (h.ai_atypical === 0) { aiText = 'OK';       aiColor = 'var(--pass-green)'; }

        var tr = document.createElement('tr');
        tr.innerHTML =
          '<td>' + (hist.length - idx) + '</td>' +
          '<td>' + (h.timestamp || '-') + '</td>' +
          '<td>' + (h.tr != null        ? h.tr.toFixed(2) + ' V'         : '-') + '</td>' +
          '<td>' + (h.cl != null        ? (h.cl * 1000).toFixed(2) + ' mA' : '-') + '</td>' +
          '<td>' + (h.power != null     ? h.power.toFixed(2) + ' W' : '-') + '</td>' +
          '<td>' + (h.alarm_rms != null ? h.alarm_rms.toFixed(2) + ' V RMS' : '-') + '</td>' +
          '<td style="color:' + audioColor + '">' + trans1000 + '</td>' +
          '<td style="color:' + aiColor + '; font-weight:700" title="' +
            ((h.ai_verdict || '') + (h.ai_recommendation ? ' — ' + h.ai_recommendation : ''))
              .replace(/"/g, "'") + '">' + aiText + '</td>' +
          '<td style="color:' + passColor + '; font-weight:700">' +
            (h.final ? 'PASS' : 'FAIL') + '</td>';
        tbody.appendChild(tr);
      });
    });
}
