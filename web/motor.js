const $ = (id) => document.getElementById(id);

export function createMotorPanel(descriptor, command, busyChanged) {
  const buttons = [...document.querySelectorAll('[data-motor-mode]')];
  let state, connected = true, otherBusy = false, paused = false, sleeping = false, pending = false, rendered = -1;
  if (!descriptor?.available) {
    $('motor-status').textContent = descriptor?.error || 'Motor link unavailable in this environment.';
    $('motor-controls').hidden = true;
    return { update() {}, setConnected() {}, setOtherBusy() {}, render() {} };
  }
  $('motor-protocol').textContent = `${descriptor.input_count} sugar-sensing neurons · ${descriptor.rate_hz} Hz for ${descriptor.stimulus_ms} ms, then 200 ms recovery. Neural and body time advance together.`;
  $('fly-controller').textContent = 'MN9 → proboscis motor link available.';
  $('organism-controller').textContent = 'One neural motor link available';
  function controls() {
    const running = state?.status === 'running';
    for (const button of buttons) {
      button.disabled = !connected || otherBusy || running || pending || paused || !sleeping;
      button.setAttribute('aria-pressed', String(state?.mode === button.dataset.motorMode));
    }
    $('motor-stop').disabled = !connected || !running || pending;
    $('motor-readiness').textContent = paused ? 'Resume the simulation to continue.'
      : !running && !sleeping ? 'Waiting for the body to settle before the next trial.' : '';
    busyChanged(running || pending);
  }
  for (const button of buttons) {
    button.addEventListener('click', async () => {
      pending = true;
      controls();
      try { await command({ action: 'motor_trial', mode: button.dataset.motorMode }); }
      finally { pending = false; controls(); }
    });
  }
  $('motor-stop').addEventListener('click', () => command({ action: 'motor_stop' }));

  function drawHistory(history) {
    const canvas = $('motor-timeline'), ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.font = '10px monospace';
    const rows = [
      ['mn9_spikes', '#b8d6c1', 'MN9 spikes'],
      ['drive', '#e3be80', 'Drive 0–1'],
      ['angle_deg', '#b5b3e6', 'Angle °'],
    ];
    rows.forEach(([key, color, label], row) => {
      const top = row * 39 + 5, base = top + 27;
      const values = history.map((item) => item[key]);
      const low = key === 'angle_deg' ? Math.min(-75, ...values) : 0;
      const high = key === 'drive' ? 1 : key === 'angle_deg' ? Math.max(15, ...values) : Math.max(1, ...values);
      ctx.fillStyle = '#aab8bc';
      ctx.fillText(label, 0, top + 16);
      ctx.strokeStyle = '#c3d9dc26';
      ctx.beginPath(); ctx.moveTo(85, base); ctx.lineTo(412, base); ctx.stroke();
      ctx.strokeStyle = color;
      ctx.beginPath();
      history.forEach((item, i) => {
        const x = 85 + item.ms / descriptor.total_ms * 327;
        const y = base - (item[key] - low) / (high - low) * 25;
        if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
      });
      ctx.stroke();
    });
    ctx.fillStyle = '#aab8bc';
    ctx.fillText('0', 85, 137); ctx.fillText('300', 272, 137); ctx.fillText('500 ms', 373, 137);
    ctx.setLineDash([3, 4]); ctx.strokeStyle = '#c3d9dc55';
    ctx.beginPath(); ctx.moveTo(281.2, 0); ctx.lineTo(281.2, 119); ctx.stroke(); ctx.setLineDash([]);
  }

  function render() {
    if ($('neural-panel').hidden || document.hidden || !state || rendered === state.revision) return;
    rendered = state.revision;
    const idle = state.status === 'idle';
    const names = { stimulus: 'Sugar response', baseline: 'No input', blocked: 'Motor link blocked' };
    $('motor-status').textContent = idle ? 'Ready · one motor link'
      : state.error || `${names[state.mode]} · ${state.paused && state.status === 'running' ? 'Paused' : state.status}`;
    $('motor-progress').value = state.simulated_ms || 0;
    $('motor-time').textContent = `${(state.simulated_ms || 0).toFixed(0)} ms brain / ${(state.physical_ms || 0).toFixed(0)} ms body`;
    $('motor-wall').textContent = idle ? 'Runs on demand' : `${(state.wall_seconds || 0).toFixed(2)} s elapsed`;
    $('motor-mn9').textContent = idle ? '—' : (state.readouts || []).map((item) => item.spikes).join(' / ');
    $('motor-excursion').textContent = idle ? '—' : `${(state.peak_excursion_deg || 0).toFixed(1)}°`;
    $('motor-downstream').textContent = idle ? '—' : Number(state.downstream_spikes || 0).toLocaleString('en-US');
    $('motor-drive').textContent = state.drive_enabled ? 'Enabled · rostrum only'
      : state.status === 'running' && state.mode === 'blocked' ? 'Blocked' : 'Off';
    $('motor-workflow-brain').classList.toggle('measured', state.downstream_spikes > 0);
    $('motor-workflow-mn9').classList.toggle('measured', (state.readouts || []).some((item) => item.spikes > 0));
    $('motor-workflow-body').classList.toggle('measured', state.peak_force > 0);
    drawHistory(state.history || []);
  }
  return {
    update(next, isPaused, isSleeping) {
      paused = isPaused;
      sleeping = isSleeping;
      if (next) state = next;
      controls();
      render();
    },
    setOtherBusy(value) { otherBusy = value; controls(); },
    setConnected(value) { connected = value; controls(); },
    render,
  };
}
