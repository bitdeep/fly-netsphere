import { sampleTooltip } from './inspect.js';

const $ = (id) => document.getElementById(id);

export function createMotorPanel(descriptor, tooltips) {
  let state, rendered = -1;
  if (!descriptor?.available) {
    $('motor-status').textContent = descriptor?.error || 'Motor link unavailable in this environment.';
    $('motor-controls').hidden = true;
    return { update() {}, render() {} };
  }
  $('fly-controller').dataset.tooltip = 'Anatomical flybody with one experimental MN9 → rostrum motor link. Walking and flight are not connected.';
  $('organism-controller').textContent = 'One neural motor link available';
  sampleTooltip($('motor-timeline'), () => state?.history,
    (sample) => `${sample.ms} ms brain / body\nMN9: ${sample.mn9_spikes} cumulative spikes\nDrive: ${sample.drive.toFixed(3)} / 1\nRostrum angle: ${sample.angle_deg.toFixed(2)}°`,
    tooltips.refresh, descriptor.total_ms);

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
    if ($('neural-panel').hidden || $('motor-readout').hidden || document.hidden || !state || rendered === state.revision) return;
    rendered = state.revision;
    const idle = state.status === 'idle';
    const taste = state.stimulus || 'sugar', label = taste[0].toUpperCase() + taste.slice(1);
    const names = { stimulus: label, baseline: `${label} baseline`, blocked: `${label} · motor blocked` };
    $('motor-input').firstChild.textContent = label;
    $('motor-input').querySelector('small').textContent = `${state.input_count || descriptor.input_count} inputs`;
    $('motor-input').dataset.tooltip = `${state.input_count || descriptor.input_count} identified ${taste} sensory neurons. ${descriptor.rate_hz} Hz for ${descriptor.stimulus_ms} ms, followed by 200 ms recovery. Each trial starts from neural rest with the same seed.`;
    $('motor-status').textContent = idle ? 'Taste · Ready'
      : state.error || `${names[state.mode]} · ${state.paused && state.status === 'running' ? 'Paused' : state.status}`;
    $('motor-progress').value = state.simulated_ms || 0;
    $('motor-time').textContent = `${(state.simulated_ms || 0).toFixed(0)} / 500 ms`;
    $('motor-time').dataset.tooltip = `Shared clock: ${(state.simulated_ms || 0).toFixed(1)} ms neural / ${(state.physical_ms || 0).toFixed(1)} ms physical time. Neither is wall time.`;
    $('motor-wall').textContent = idle ? 'On demand' : `${(state.wall_seconds || 0).toFixed(2)} s elapsed`;
    $('motor-wall').dataset.tooltip = `Elapsed wall time, including pauses: ${(state.wall_seconds || 0).toFixed(2)} s. Thread CPU time: ${(state.cpu_seconds || 0).toFixed(3)} s.`;
    $('motor-mn9').textContent = idle ? '—' : (state.readouts || []).map((item) => item.spikes).join(' / ');
    $('motor-excursion').textContent = idle ? '—' : `${(state.peak_excursion_deg || 0).toFixed(1)}°`;
    $('motor-downstream').textContent = idle ? '—' : Number(state.downstream_spikes || 0).toLocaleString('en-US');
    $('motor-drive').textContent = state.drive_enabled ? 'Rostrum on'
      : state.status === 'running' && state.mode === 'blocked' ? 'Drive blocked' : 'Drive off';
    $('motor-mn9').parentElement.dataset.tooltip = (state.readouts || []).map((item) => `${item.label}: ${item.spikes} spikes · ${item.voltage_mv.toFixed(2)} mV\nFlyWire ID ${item.id}`).join('\n') || 'Calculated MN9 motor-neuron spikes, left / right.';
    $('motor-workflow-brain').classList.toggle('measured', state.downstream_spikes > 0);
    $('motor-workflow-mn9').classList.toggle('measured', (state.readouts || []).some((item) => item.spikes > 0));
    $('motor-workflow-body').classList.toggle('measured', state.peak_force > 0);
    drawHistory(state.history || []);
  }
  return {
    update(next) {
      if (next) state = next;
      render();
    },
    render,
  };
}
