const $ = (id) => document.getElementById(id);
const names = { sugar: 'Feed', water: 'Water', bitter: 'Bitter', antenna: 'Antenna' };

export function createActions(neural, motor, command, selectReadout) {
  const presets = [...document.querySelectorAll('[data-preset]')];
  let selected = 'sugar', state = null, connected = false, pending = false;
  let seenMotor = 0, seenNeural = 0;
  let rendered = '';
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
  function render() {
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
      if (next.motor_running && next.motor.trial !== seenMotor) {
        seenMotor = next.motor.trial;
        selected = next.motor.stimulus || 'sugar';
        selectReadout('motor');
      } else if (next.neural_running && next.neural.trial !== seenNeural) {
        seenNeural = next.neural.trial;
        selected = 'antenna';
        selectReadout('antenna');
      }
      render();
    },
    setConnected(value) { connected = value; render(); },
  };
}
