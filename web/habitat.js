import * as THREE from 'three';

const $ = (id) => document.getElementById(id);

export function createHabitat(descriptor, scene, command, invalidate, focus) {
  const kinds = new Map(descriptor.kinds.map((item) => [item.id, item]));
  const geometry = new THREE.SphereGeometry(descriptor.radius_cm, 16, 12);
  const materials = new Map(descriptor.kinds.map((item) => [item.id,
    new THREE.MeshStandardMaterial({ color: item.color, roughness: .4,
      transparent: true, opacity: .8 })]));
  const meshes = Array.from({ length: descriptor.capacity }, () => {
    const mesh = new THREE.Mesh(geometry, materials.get('fruit'));
    mesh.visible = false;
    scene.add(mesh);
    return mesh;
  });
  let selected = 'fruit', state, connected = false, pending = false, placing = false;
  let revision = -1, renderedControls = '';
  function hide() { $('habitat-panel').hidden = true; $('habitat-open').setAttribute('aria-expanded', 'false'); }
  function setPlacing(value) {
    placing = value;
    $('world').classList.toggle('placing-object', value);
    $('placement-hint').hidden = !value;
    $('habitat-place').setAttribute('aria-pressed', String(value));
  }
  function renderControls() {
    const full = (state?.objects.length || 0) >= descriptor.capacity;
    const key = [connected, pending, full, state?.enabled].join('|');
    if (key === renderedControls) return;
    renderedControls = key;
    for (const id of ['habitat-offer', 'habitat-place']) $(id).disabled = !connected || pending || full;
    $('habitat-senses').disabled = !connected || pending;
    $('habitat-senses').checked = Boolean(state?.enabled);
    for (const button of $('habitat-objects').querySelectorAll('button')) button.disabled = !connected || pending;
  }
  async function send(payload) {
    if (!connected || pending) return false;
    pending = true; renderControls();
    try { return await command(payload); }
    finally { pending = false; renderControls(); }
  }
  $('habitat-open').addEventListener('click', () => {
    const show = $('habitat-panel').hidden;
    if (show && innerWidth <= 700 && !$('neural-panel').hidden) $('neural-close').click();
    $('habitat-panel').hidden = !show;
    $('habitat-open').setAttribute('aria-expanded', String(show));
    if (show) $('habitat-close').focus();
  });
  $('habitat-close').addEventListener('click', hide);
  $('neural-open').addEventListener('click', () => { if (innerWidth <= 700) hide(); });
  for (const button of document.querySelectorAll('[data-object-kind]')) {
    button.addEventListener('click', () => {
      selected = button.dataset.objectKind;
      for (const other of document.querySelectorAll('[data-object-kind]')) {
        other.setAttribute('aria-pressed', String(other === button));
      }
    });
  }
  $('habitat-offer').addEventListener('click', async () => {
    setPlacing(false);
    if (await send({ action: 'object_place', kind: selected })) {
      if (innerWidth <= 700) hide();
      focus();
    }
  });
  $('habitat-place').addEventListener('click', () => {
    setPlacing(!placing);
    if (placing) hide();
  });
  $('habitat-senses').addEventListener('change', () =>
    send({ action: 'reactive_senses', enabled: $('habitat-senses').checked }));
  addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && placing) {
      setPlacing(false); event.preventDefault();
    }
  });
  return {
    get placing() { return placing; },
    async place(point) {
      if (await send({ action: 'object_place', kind: selected, position: point })) setPlacing(false);
    },
    setConnected(value) { connected = value; if (!value) setPlacing(false); renderControls(); },
    update(next) {
      if (!next || revision === next.revision) return;
      state = next; revision = next.revision;
      let changed = false;
      for (let slot = 0; slot < meshes.length; slot++) {
        const mesh = meshes[slot], item = next.objects.find((item) => item.slot === slot);
        const visible = Boolean(item);
        if (mesh.visible !== visible) changed = true;
        mesh.visible = visible;
        if (item) {
          if (mesh.position.toArray().some((x, i) => x !== item.position[i])
              || mesh.material !== materials.get(item.kind)) changed = true;
          mesh.position.fromArray(item.position);
          mesh.material = materials.get(item.kind);
        }
      }
      if (changed) invalidate();
      $('habitat-status').textContent = next.status;
      $('habitat-count').textContent = `${next.objects.length} / ${descriptor.capacity}`;
      $('habitat-objects').replaceChildren();
      for (const item of next.objects) {
        const row = document.createElement('li'), text = document.createElement('span');
        text.textContent = `${kinds.get(item.kind).label} · ${item.used ? 'Contact recorded' : 'Waiting for contact'}`;
        const remove = document.createElement('button');
        remove.textContent = '×';
        remove.setAttribute('aria-label', `Remove ${kinds.get(item.kind).label} ${item.id}`);
        remove.addEventListener('click', () => send({ action: 'object_remove', id: item.id }));
        row.append(text, remove); $('habitat-objects').append(row);
      }
      renderedControls = ''; renderControls();
    },
  };
}
