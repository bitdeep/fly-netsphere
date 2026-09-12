const $ = (id) => document.getElementById(id);
const names = { sugar: 'Feed', water: 'Water', bitter: 'Bitter', antenna: 'Antenna' };

export function createActions(neural, motor, command, selectReadout) {
  const presets = [...document.querySelectorAll('[data-preset]')];
  let selected = 'sugar', state = null, connected = false, pending = false;
  let seenMotor = 0, seenNeural = 0;
  let rendered = '', renderedResult = '';
  $('fly-actions').hidden = false;
  function disabled(button, value) {
    // aria-disabled keeps reasons available to keyboard and touch users.
    button.setAttribute('aria-disabled', String(value));
  }
  function allowed(preset) {
    return connected && !pending && !state?.motor_running && !state?.neural_running
      && (preset === 'antenna' ? neural?.available
        : motor?.available && !state?.paused && state?.fly.sleeping);
  }
  function renderResult() {
    const isAntenna = selected === 'antenna';
    const trial = isAntenna ? state?.neural : state?.motor;
    const current = isAntenna || (trial?.stimulus || 'sugar') === selected;
    const key = [selected, pending, current, trial?.revision, state?.paused, connected].join('|');
    if (key === renderedResult) return;
    renderedResult = key;
    const label = current && trial?.source ? trial.source.label : names[selected];
    let result;
    if (pending) result = pending === 'stop' ? 'Stopping the trial…' : `Starting ${label}…`;
    else if (!connected) result = 'Disconnected · waiting for the environment.';
    else if (!current || !trial || trial.status === 'idle') result = `${label} · choose a stimulus to run a trial.`;
    else if (trial.error) result = `${label} · ${trial.error}`;
    else if (trial.status === 'unavailable') result = `${label} · neural link unavailable.`;
    else if (trial.status === 'running') {
      const paused = !isAntenna && state.paused;
      result = `${label} · ${paused ? 'Paused' : 'Running'} · ${Math.round(trial.simulated_ms || 0)} / ${isAntenna ? 150 : 500} ms`;
    } else if (trial.status === 'cancelled') result = `${label} · Stopped · incomplete result.`;
    else {
      const spikes = `${Number(trial.downstream_spikes || 0).toLocaleString('en-US')} downstream spikes`;
      if (trial.mode === 'baseline') result = `${label} baseline · No input · ${spikes}`;
      else if (trial.mode === 'blocked') result = `${label} · ${isAntenna ? 'Sensory output blocked' : 'Motor link blocked'} · ${spikes}`;
      else if (isAntenna) result = `${label} · ${spikes} · Muscles unlinked`;
      else {
        const movement = trial.peak_excursion_deg > .05
          ? `Proboscis moved ${trial.peak_excursion_deg.toFixed(1)}°` : 'No proboscis movement';
        result = `${label} · ${movement} · ${spikes}`;
      }
    }
    $('action-result').textContent = result;
  }
  function render() {
    renderResult();
    const key = [selected, connected, pending, state?.motor_running, state?.neural_running,
      state?.paused, state?.fly.sleeping, state?.motor?.stimulus].join('|');
    if (key === rendered) return;
    rendered = key;
    for (const button of presets) {
      disabled(button, !allowed(button.dataset.preset));
      button.setAttribute('aria-pressed', String(button.dataset.preset === selected));
    }
    disabled($('action-baseline'), !allowed(selected));
    disabled($('action-block'), !allowed(selected));
    disabled($('trial-stop'), !connected || pending || !(state?.motor_running || state?.neural_running));
    const active = state?.motor_running ? state.motor : state?.neural_running ? state.neural : null;
    $('action-status').textContent = !connected ? 'Reconnecting…'
      : pending ? pending === 'stop' ? 'Stopping…' : 'Starting…'
      : active ? `${state.motor_running ? names[active.stimulus || 'sugar'] : 'Antenna'} · ${state.motor_running && state.paused ? 'Paused' : 'Running'}`
      : !neural?.available ? 'Neural cache unavailable'
      : state?.paused ? 'Body paused'
      : !state?.fly.sleeping ? 'Body settling'
      : 'Ready';
    $('action-block').textContent = selected === 'antenna' ? 'Block sensory' : 'Block link';
    $('action-block').dataset.tooltip = selected === 'antenna'
      ? 'Same antennal input, with outgoing sensory connections blocked. Input neurons still spike.'
      : `Same ${selected} input and brain activity, with motor actuation disabled.`;
    $('action-baseline').dataset.tooltip = `${names[selected]} protocol with no external input. The physical fly is never reset for a trial.`;
  }
  async function run(mode) {
    if (!allowed(selected)) return;
    selectReadout(selected === 'antenna' ? 'antenna' : 'motor');
    pending = true;
    render();
    try {
      await command(selected === 'antenna' ? { action: 'neural_trial', mode }
        : { action: 'motor_trial', mode, stimulus: selected });
    } finally { pending = false; render(); }
  }
  for (const button of presets) {
    button.addEventListener('click', () => {
      if (!allowed(button.dataset.preset)) return;
      selected = button.dataset.preset;
      run('stimulus');
    });
  }
  $('action-baseline').addEventListener('click', () => run('baseline'));
  $('action-block').addEventListener('click', () => run('blocked'));
  $('trial-stop').addEventListener('click', async () => {
    if ($('trial-stop').getAttribute('aria-disabled') === 'true') return;
    pending = 'stop'; render();
    try { await command({ action: state.motor_running ? 'motor_stop' : 'neural_stop' }); }
    finally { pending = false; render(); }
  });
  render();
  return {
    update(next) {
      state = next;
      const newMotor = next.motor?.trial && next.motor.trial !== seenMotor;
      const newNeural = next.neural?.trial && next.neural.trial !== seenNeural;
      seenMotor = next.motor?.trial || 0;
      seenNeural = next.neural?.trial || 0;
      // A contact-only neural response can finish between idle SSE updates.
      // Retain its result even when no "running" packet reached this viewer.
      if (newMotor && !next.neural_running) {
        selected = next.motor.stimulus || 'sugar';
        selectReadout('motor');
      } else if (newNeural) {
        selected = 'antenna';
        selectReadout('antenna');
      }
      render();
    },
    setConnected(value) { connected = value; render(); },
  };
}
