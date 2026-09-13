const $ = (id) => document.getElementById(id);

export function createSurvival(command) {
  let state, connected = false, pending = false, rendered = '';
  function render() {
    if (!state) return;
    const energy = (state.survival.energy * 100).toFixed(1);
    const water = (state.survival.water * 100).toFixed(1);
    const { alive, cause } = state.survival;
    const key = [energy, water, alive, cause, state.paused, connected, pending].join('|');
    if (rendered === key) return;
    rendered = key;
    for (const [resource, value] of [['energy', energy], ['water', water]]) {
      $(resource + '-value').textContent = `${value}%`;
      $(resource + '-meter').value = Number(value);
      $(resource + '-meter').setAttribute('aria-valuetext', `${value} percent`);
      $(resource + '-reserve').classList.toggle('low', Number(value) <= 20);
    }
    $('life-reserves').classList.toggle('dead', !alive);
    $('life-status').textContent = !alive
      ? `Died · ${cause === 'water' ? 'water' : 'energy'} depleted`
      : !connected ? 'Reserves disconnected' : state.paused ? 'Reserves paused' : 'Alive · reserves model';
    $('life-restart').hidden = alive;
    $('life-restart').disabled = !connected || pending;
  }
  $('life-restart').addEventListener('click', async () => {
    if (!connected || pending || state?.survival.alive) return;
    pending = true; render();
    try { await command({ action: 'life_restart' }); }
    finally { pending = false; render(); }
  });
  return {
    update(next) { if (next.survival) { state = next; render(); } },
    setConnected(value) { connected = value; render(); },
  };
}
