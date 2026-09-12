import * as THREE from 'three';
import { createFly } from './fly.js';

const $ = (selector) => document.querySelector(selector);
const canvas = $('#world');
const keys = new Set();
const up = new THREE.Vector3(0, 0, 1);
const forward = new THREE.Vector3();
const right = new THREE.Vector3();
const movement = new THREE.Vector3();
const scratch = new THREE.Vector3();
const projected = new THREE.Vector3();
const markerPoint = new THREE.Vector2();
const raycaster = new THREE.Raycaster();
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(65, innerWidth / innerHeight, 0.04, 550);
camera.up.copy(up);
let renderer, world, state, geometries = [], frames = 0;
let lastEvent = 0, lastFrame = performance.now(), fpsStart = lastFrame, frameCount = 0;
let yaw = 0, pitch = 0, drag = null, transition = null, toastTimer;
let probe, trail, lastTrailLength = -1, lastGeneration = -1, connected = null;
let needsRender = true, lastRender = 0, renderLimit = 30, pixelBudget = 1500000;
let graphicsLost = false;
let graphicsDevice = '', softwareGraphics = false, renderCostMs = 0;
let cameraMovedSinceHud = false;
let neuralPanel;
let fly, flyView = false, headView = false, orbitYaw = -.95, orbitPitch = .45, orbitDistance = .65;
let scheduledFrame = 0, hudTimer = 0;
const freeHelp = $('.navigation-help').innerHTML;
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

function invalidate() {
  needsRender = true;
  scheduleFrame();
}

function scheduleFrame() {
  if (scheduledFrame || document.hidden || graphicsLost || !renderer) return;
  scheduledFrame = requestAnimationFrame(render);
}

function toast(text) {
  $('#toast').textContent = text;
  $('#toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 3800);
}

function fail(message) {
  $('#loading').hidden = false;
  $('#loading').replaceChildren();
  const title = document.createElement('strong');
  title.textContent = 'Could not open the environment';
  const explanation = document.createElement('span');
  explanation.textContent = message;
  $('#loading').append(title, explanation);
}

function setConnected(value) {
  if (connected === value) return;
  connected = value;
  $('#connection-dot').className = `dot ${value ? 'live' : 'offline'}`;
  $('#connection').textContent = value ? 'Environment connected' : 'Reconnecting…';
  for (const id of ['#drop', '#pause', '#speed']) $(id).disabled = !value;
  neuralPanel?.setConnected(value);
}

async function command(payload) {
  try {
    const response = await fetch('/api/command', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const failure = await response.json().catch(() => ({}));
      toast(failure.error || `Command unavailable (HTTP ${response.status}).`);
      return false;
    }
    updateState(await response.json());
    return true;
  } catch {
    toast('The command did not reach the environment. Wait for reconnection and try again.');
    return false;
  }
}

function updateState(next) {
  if (!next.probe.trail) next.probe.trail = state?.probe.trail || [];
  if (!next.neural || (state?.neural?.revision ?? -1) > next.neural.revision) next.neural = state?.neural;
  if (!next.motor || (state?.motor?.revision ?? -1) > next.motor.revision) next.motor = state?.motor;
  state = next;
  neuralPanel?.update(next.neural, next.motor, next.paused, next.fly.sleeping);
  lastEvent = performance.now();
  setConnected(!next.error);
  if (next.error) {
    $('#connection').textContent = 'Physics stopped';
    toast('The simulation has stopped. Check the environment service.');
  }
  $('#pause').textContent = next.paused ? '▷' : 'Ⅱ';
  $('#pause').setAttribute('aria-label', next.paused ? 'Resume simulation' : 'Pause simulation');
  $('#pause').title = next.paused ? 'Resume simulation' : 'Pause simulation';
  $('#speed').value = String(next.speed);
  const minutes = Math.floor(next.time / 60).toString().padStart(2, '0');
  $('#sim-time').textContent = `${minutes}:${(next.time % 60).toFixed(2).padStart(5, '0')}`;
  $('#physical-rate').textContent = next.paused ? 'PAUSED' : `${next.realtime_ratio.toFixed(2)}× PHYSICS`;
  if (fly && fly.apply(next.fly)) {
    if (flyView) orbitCamera();
    invalidate();
  }
  $('#fly-status').textContent = next.paused ? 'Paused' : next.fly.sleeping ? 'At rest' : next.motor_running ? 'Motor trial' : 'Settling';
  $('#fly-drive').textContent = next.motor?.drive_enabled ? 'Rostrum only' : 'Off';
  if (!probe) return;
  const moved = probe.position.distanceToSquared(scratch.fromArray(next.probe.position)) > 1e-8;
  if (probe.visible !== next.probe.active || (next.probe.active && moved)) {
    invalidate();
    renderer.shadowMap.needsUpdate = true;
  }
  probe.visible = trail.visible = next.probe.active;
  probe.position.fromArray(next.probe.position);
  if (next.probe.generation !== lastGeneration || next.probe.trail.length !== lastTrailLength) {
    const attribute = trail.geometry.attributes.position;
    for (let i = 0; i < next.probe.trail.length; i++) attribute.array.set(next.probe.trail[i], i * 3);
    attribute.needsUpdate = true;
    trail.geometry.setDrawRange(0, next.probe.trail.length);
    lastTrailLength = next.probe.trail.length;
    lastGeneration = next.probe.generation;
  }
  $('#probe-status').textContent = !next.probe.active
    ? 'Test sphere · 9 mm diameter'
    : next.probe.contact_seen ? 'Physical contact recorded on the walkway' : 'Sphere falling · measured trajectory';
  $('#probe-status').classList.toggle('contact', next.probe.contact_seen);
}

function geometryFor(item, material) {
  const [x, y, z] = item.size;
  let geometry;
  if (item.type === 'box') {
    geometry = new THREE.BoxGeometry(x * 2, y * 2, z * 2);
    if (material.name !== 'designation') {
      const positions = geometry.attributes.position;
      const normals = geometry.attributes.normal;
      const uv = geometry.attributes.uv;
      const tile = material.name === 'metal' || material.name === 'cladding' ? 7 : 18;
      for (let i = 0; i < positions.count; i++) {
        const nx = Math.abs(normals.getX(i)), ny = Math.abs(normals.getY(i));
        uv.setXY(i, (nx > .5 ? positions.getY(i) : positions.getX(i)) / tile,
          (nx > .5 || ny > .5 ? positions.getZ(i) : positions.getY(i)) / tile);
      }
    }
  } else if (item.type === 'plane') {
    geometry = new THREE.PlaneGeometry(x * 2, y * 2);
    const uv = geometry.attributes.uv;
    for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) * 24, uv.getY(i) * 24);
  } else if (item.type === 'cylinder') {
    geometry = new THREE.CylinderGeometry(x, x, y * 2, x < .4 ? 8 : 24);
    geometry.rotateX(Math.PI / 2);
  } else if (item.type === 'capsule') {
    geometry = new THREE.CapsuleGeometry(x, y * 2, 4, 8);
    geometry.rotateX(Math.PI / 2);
  } else if (item.type === 'sphere') {
    geometry = new THREE.SphereGeometry(x, 24, 16);
  } else {
    throw new Error(`Unsupported geometry: ${item.type}`);
  }
  return geometry;
}

async function buildWorld() {
  const textures = new Map();
  const loader = new THREE.TextureLoader();
  await Promise.all(world.materials.filter((m) => m.texture).map(async (m) => {
    if (textures.has(m.texture)) return;
    const promise = loader.loadAsync(m.texture);
    textures.set(m.texture, promise);
    const texture = await promise;
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
    texture.anisotropy = Math.min(renderer.capabilities.getMaxAnisotropy(), 8);
    textures.set(m.texture, texture);
  }));
  const materials = world.materials.map((m) => {
    const color = new THREE.Color().setRGB(...m.rgba.slice(0, 3));
    const mat = new THREE.MeshStandardMaterial({
      name: m.name, color,
      roughness: m.name === 'metal' ? .66 : .91,
      metalness: ['metal', 'cladding'].includes(m.name) ? .25 : .02,
      map: m.texture ? textures.get(m.texture) : null,
      emissive: m.emission ? color : 0,
      emissiveIntensity: m.emission * 1.4,
    });
    if (m.name === 'lamp') mat.emissive.setHex(0xffd09a);
    return mat;
  });
  for (const item of world.geoms) {
    const material = materials[item.material];
    if (!material) throw new Error('World material is missing');
    const mesh = new THREE.Mesh(geometryFor(item, material), material);
    mesh.name = item.name;
    mesh.position.fromArray(item.position);
    const r = item.rotation;
    const matrix = new THREE.Matrix4().set(
      ...r[0], 0, ...r[1], 0, ...r[2], 0, 0, 0, 0, 1,
    );
    mesh.quaternion.setFromRotationMatrix(matrix);
    mesh.castShadow = item.type !== 'plane';
    mesh.receiveShadow = true;
    mesh.userData.physical = item;
    mesh.updateMatrixWorld(true);
    geometries.push(mesh);
  }
  // The world is static: batch by material while retaining exact source meshes
  // for observer collision queries. Physical positions still come from MuJoCo.
  for (const material of materials) {
    const sources = geometries.filter((mesh) => mesh.material === material).map((mesh) => {
      const geometry = mesh.geometry.index ? mesh.geometry.toNonIndexed() : mesh.geometry.clone();
      return geometry.applyMatrix4(mesh.matrixWorld);
    });
    if (!sources.length) continue;
    const merged = new THREE.BufferGeometry();
    for (const attribute of ['position', 'normal', 'uv']) {
      const length = sources.reduce((sum, g) => sum + g.attributes[attribute].array.length, 0);
      const buffer = new Float32Array(length);
      let offset = 0;
      for (const source of sources) {
        buffer.set(source.attributes[attribute].array, offset);
        offset += source.attributes[attribute].array.length;
      }
      merged.setAttribute(attribute, new THREE.BufferAttribute(buffer, attribute === 'uv' ? 2 : 3));
    }
    for (const source of sources) source.dispose();
    const batch = new THREE.Mesh(merged, material);
    batch.castShadow = batch.receiveShadow = true;
    scene.add(batch);
  }
  scene.background = new THREE.Color(0x536674);
  scene.fog = new THREE.FogExp2(0x536674, .009);
  const hemisphere = new THREE.HemisphereLight(0xccdfeb, 0x34434b, 2.3);
  hemisphere.position.copy(up);
  scene.add(hemisphere);
  const upper = new THREE.DirectionalLight(0xd6e6f1, 2.8);
  upper.position.set(-28, -16, 174);
  upper.target.position.set(0, -25, -15);
  upper.castShadow = true;
  upper.shadow.mapSize.set(1024, 1024);
  Object.assign(upper.shadow.camera, { left: -92, right: 92, top: 110, bottom: -110, near: .5, far: 320 });
  upper.shadow.bias = -.00025;
  upper.shadow.normalBias = .1;
  scene.add(upper, upper.target);
  const bounce = new THREE.DirectionalLight(0xa9c6da, .9);
  bounce.position.set(-52, -38, 40);
  bounce.target.position.set(0, -15, 10);
  scene.add(bounce, bounce.target);
  for (const x of [-45, -15, 15, 45]) {
    const light = new THREE.PointLight(0xffbe77, 22, 17, 1.5);
    light.position.set(x, -38, 11);
    scene.add(light);
  }
  probe = new THREE.Mesh(
    new THREE.SphereGeometry(world.probe.radius, 24, 16),
    new THREE.MeshStandardMaterial({ color: 0xeaaa57, metalness: .28, roughness: .3,
      emissive: 0xa85112, emissiveIntensity: .7 }),
  );
  probe.castShadow = true;
  probe.visible = false;
  scene.add(probe);
  const trailGeometry = new THREE.BufferGeometry();
  trailGeometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(1500), 3).setUsage(THREE.DynamicDrawUsage));
  trailGeometry.setDrawRange(0, 0);
  trail = new THREE.Line(trailGeometry, new THREE.LineBasicMaterial({
    color: 0xffc276, transparent: true, opacity: .65,
  }));
  trail.visible = false;
  trail.frustumCulled = false;
  scene.add(trail);
  scene.updateMatrixWorld(true);
  $('#geom-count').textContent = String(world.geoms.length);
}

function syncAngles() {
  camera.getWorldDirection(forward);
  yaw = Math.atan2(forward.y, forward.x);
  pitch = Math.asin(THREE.MathUtils.clamp(forward.z, -.999, .999));
}

function orient() {
  cameraMovedSinceHud = true;
  scratch.set(
    Math.cos(yaw) * Math.cos(pitch), Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch),
  );
  camera.lookAt(scratch.add(camera.position));
  invalidate();
}

function orbitCamera() {
  const focus = headView ? fly.headPosition : fly.position;
  camera.position.set(
    Math.cos(orbitYaw) * Math.cos(orbitPitch),
    Math.sin(orbitYaw) * Math.cos(orbitPitch),
    Math.sin(orbitPitch),
  ).multiplyScalar(orbitDistance * Math.max(1, .95 / camera.aspect)).add(focus);
  camera.lookAt(focus);
  syncAngles();
  invalidate();
}

function setView(id, immediate = false) {
  cameraMovedSinceHud = true;
  flyView = id === 'fly';
  headView = false;
  document.body.classList.toggle('fly-view', flyView);
  $('#fly-panel').hidden = !flyView;
  $('#gravity-panel').hidden = flyView;
  $('.navigation-help').innerHTML = flyView ? '<span>Drag to orbit</span><span>Scroll to zoom</span>' : freeHelp;
  camera.near = flyView ? .001 : .04;
  camera.updateProjectionMatrix();
  document.querySelectorAll('[data-view]').forEach((button) => {
    const selected = button.dataset.view === id;
    button.classList.toggle('selected', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
  if (flyView) {
    transition = null;
    keys.clear();
    $('#view-title').textContent = 'Fly 001';
    $('#view-caption').textContent = 'One fruit fly on the lower walkway.';
    orbitCamera();
    return;
  }
  const view = world.views.find((v) => v.id === id);
  if (!view) return;
  invalidate();
  const destination = new THREE.Vector3(...view.position);
  const target = new THREE.Vector3(...view.target);
  const endCamera = camera.clone();
  endCamera.position.copy(destination);
  endCamera.lookAt(target);
  if (immediate || reducedMotion) {
    camera.position.copy(destination);
    camera.quaternion.copy(endCamera.quaternion);
    transition = null;
    syncAngles();
  } else {
    transition = {
      started: performance.now(), from: camera.position.clone(), to: destination,
      startRotation: camera.quaternion.clone(), endRotation: endCamera.quaternion.clone(),
    };
  }
  $('#view-title').textContent = view.title;
  $('#view-caption').textContent = view.caption;
}

function moveCamera(delta) {
  transition = null;
  const distance = delta.length();
  if (!distance) return;
  cameraMovedSinceHud = true;
  raycaster.set(camera.position, scratch.copy(delta).normalize());
  raycaster.near = 0;
  raycaster.far = distance + .3;
  const hit = raycaster.intersectObjects(geometries, false)[0];
  if (hit) delta.multiplyScalar(Math.max(0, hit.distance - .3) / distance);
  camera.position.add(delta);
  camera.position.x = THREE.MathUtils.clamp(camera.position.x, -57, 57);
  camera.position.y = THREE.MathUtils.clamp(camera.position.y, -40, 40);
  camera.position.z = THREE.MathUtils.clamp(camera.position.z, -46, 175);
  invalidate();
}

function drawMap() {
  const map = $('#minimap'), ctx = map.getContext('2d');
  const scale = 2.7, ox = map.width / 2, oy = map.height / 2;
  ctx.clearRect(0, 0, map.width, map.height);
  ctx.strokeStyle = '#aac8cb12';
  ctx.lineWidth = 1;
  for (let x = 21; x < map.width; x += 27) {
    ctx.beginPath(); ctx.moveTo(x, 15); ctx.lineTo(x, map.height - 15); ctx.stroke();
  }
  for (let y = 20; y < map.height; y += 27) {
    ctx.beginPath(); ctx.moveTo(18, y); ctx.lineTo(map.width - 18, y); ctx.stroke();
  }
  for (const item of world.geoms) {
    if (item.type === 'plane') continue;
    const [x, y, z] = item.position, [sx, sy, sz] = item.size;
    const reaches = item.type === 'cylinder' ? sy : sz;
    const active = Math.abs(camera.position.z - z) <= reaches;
    ctx.fillStyle = active ? '#b1c8c32c' : '#b1c8c30a';
    ctx.strokeStyle = active ? '#accac573' : '#accac526';
    if (item.type === 'box') {
      ctx.fillRect(ox + (x - sx) * scale, oy - (y + sy) * scale, sx * 2 * scale, sy * 2 * scale);
      ctx.strokeRect(ox + (x - sx) * scale, oy - (y + sy) * scale, sx * 2 * scale, sy * 2 * scale);
    } else if (item.type === 'cylinder') {
      ctx.beginPath(); ctx.arc(ox + x * scale, oy - y * scale, Math.max(sx * scale, 1), 0, Math.PI * 2);
      ctx.fill(); ctx.stroke();
    }
  }
  const x = ox + camera.position.x * scale, y = oy - camera.position.y * scale;
  ctx.fillStyle = '#c4e4c82b';
  ctx.beginPath(); ctx.moveTo(x, y); ctx.arc(x, y, 29, -yaw - .5, -yaw + .5); ctx.closePath(); ctx.fill();
  ctx.fillStyle = '#c4e4c8';
  ctx.beginPath(); ctx.arc(x, y, 3.5, 0, Math.PI * 2); ctx.fill();
  if (fly) {
    ctx.fillStyle = '#efc07c';
    ctx.beginPath(); ctx.arc(ox + fly.position.x * scale, oy - fly.position.y * scale, 3, 0, Math.PI * 2); ctx.fill();
  }
  $('#coordinates').textContent = camera.position.toArray().map((p) => p.toFixed(1).padStart(5)).join(' / ');
}

function render(now) {
  scheduledFrame = 0;
  if (document.hidden || graphicsLost) return;
  if (!needsRender && !transition && !(keys.size && !flyView)) return;
  // Pace on vsync. A full timeout followed by rAF can miss the target refresh.
  // Only pending work schedules another callback; idle scenes still stop.
  if (now - lastRender < 1000 / renderLimit - .5) {
    scheduleFrame();
    return;
  }
  const dt = Math.min((now - lastFrame) / 1000, .05);
  lastFrame = now;
  if (transition) {
    cameraMovedSinceHud = true;
    needsRender = true;
    const t = Math.min((now - transition.started) / 1100, 1);
    const ease = t * t * (3 - 2 * t);
    camera.position.lerpVectors(transition.from, transition.to, ease);
    camera.quaternion.slerpQuaternions(transition.startRotation, transition.endRotation, ease);
    if (t === 1) { transition = null; syncAngles(); }
  }
  if (keys.size && !flyView) {
    camera.getWorldDirection(forward);
    right.crossVectors(forward, up).normalize();
    const delta = movement.set(0, 0, 0);
    if (keys.has('KeyW') || keys.has('ArrowUp')) delta.add(forward);
    if (keys.has('KeyS') || keys.has('ArrowDown')) delta.sub(forward);
    if (keys.has('KeyD') || keys.has('ArrowRight')) delta.add(right);
    if (keys.has('KeyA') || keys.has('ArrowLeft')) delta.sub(right);
    if (keys.has('KeyE')) delta.add(up);
    if (keys.has('KeyQ')) delta.sub(up);
    const speed = keys.has('ShiftLeft') || keys.has('ShiftRight') ? 30 : 12;
    moveCamera(delta.normalize().multiplyScalar(dt * speed));
  }
  if (needsRender) {
    const started = performance.now();
    fly.updateVisibility(camera, canvas.height);
    renderer.render(scene, camera);
    frames++; frameCount++;
    needsRender = false;
    lastRender = now;
    drawMap();
    updateMarker();
    renderCostMs = performance.now() - started;
  }
  if (transition || (keys.size && !flyView)) scheduleFrame();
}

function updateMarker() {
  const marker = $('#fly-marker');
  marker.hidden = true;
  if (flyView || fly.revision < 0) return;
  projected.copy(fly.position).project(camera);
  if (Math.abs(projected.x) > .96 || Math.abs(projected.y) > .92 || Math.abs(projected.z) > 1) return;
  scratch.copy(fly.position).sub(camera.position);
  const distance = scratch.length();
  raycaster.set(camera.position, scratch.normalize());
  raycaster.near = 0;
  raycaster.far = Math.max(0, distance - .15);
  if (raycaster.intersectObjects(geometries, false).length) return;
  marker.style.left = `${(projected.x + 1) * innerWidth / 2}px`;
  marker.style.top = `${(1 - projected.y) * innerHeight / 2}px`;
  marker.hidden = false;
}

function updateHud() {
  if (!document.hidden) {
    const now = performance.now();
    const rate = Math.round(frameCount * 1000 / (now - fpsStart));
    $('#fps').textContent = frameCount ? `${rate} ${cameraMovedSinceHud ? 'FPS' : 'UPDATES/S'}` : 'VIEW IDLE';
    $('#fps').title = 'FPS while moving the camera; changed scene updates per second while stationary. Target: 30 FPS during movement. Idle scenes do not redraw.';
    cameraMovedSinceHud = false;
    frameCount = 0;
    fpsStart = now;
    if (connected && now - lastEvent > 3500) setConnected(false);
  }
}

function bindControls() {
  $('#motor-focus').addEventListener('click', () => {
    setView('fly', true);
    headView = true;
    orbitDistance = .35;
    orbitPitch = .25;
    orbitCamera();
  });
  document.querySelectorAll('[data-view]').forEach((button) => {
    button.addEventListener('click', () => setView(button.dataset.view));
  });
  $('#fly-marker').addEventListener('click', () => setView('fly'));
  $('#drop').addEventListener('click', async () => {
    // Move the observer first so the fast physical event is actually visible.
    setView('lower', true);
    if (await command({ action: 'drop' })) toast('Sphere released. Use 0.25× to watch the fall in slow motion.');
  });
  $('#pause').addEventListener('click', () => command({ action: 'pause', paused: !state.paused }));
  $('#speed').addEventListener('change', () => command({ action: 'speed', value: Number($('#speed').value) }));
  $('#fullscreen').addEventListener('click', async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch { toast('This browser did not allow full screen.'); }
  });
  canvas.addEventListener('pointerdown', (event) => {
    if (event.button !== 0) return;
    canvas.focus();
    transition = null;
    syncAngles();
    drag = { id: event.pointerId, x: event.clientX, y: event.clientY, moved: 0 };
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener('pointermove', (event) => {
    if (!drag || event.pointerId !== drag.id) return;
    const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
    drag.moved += Math.abs(dx) + Math.abs(dy);
    if (flyView) {
      cameraMovedSinceHud = true;
      orbitYaw -= dx * .008;
      orbitPitch = THREE.MathUtils.clamp(orbitPitch + dy * .008, .12, 1.48);
      drag.x = event.clientX; drag.y = event.clientY;
      orbitCamera();
      return;
    }
    yaw -= (event.clientX - drag.x) * .003;
    pitch = THREE.MathUtils.clamp(pitch - (event.clientY - drag.y) * .003, -1.48, 1.48);
    drag.x = event.clientX; drag.y = event.clientY;
    orient();
  });
  const release = (event) => {
    if (drag && drag.moved < 5 && !flyView && event.type === 'pointerup') {
      markerPoint.set(event.clientX / innerWidth * 2 - 1, 1 - event.clientY / innerHeight * 2);
      raycaster.setFromCamera(markerPoint, camera);
      if (raycaster.ray.distanceToPoint(fly.position) < .18) {
        // Selection changes only the observer; the marker already handles far views.
        const distance = camera.position.distanceTo(fly.position);
        raycaster.near = 0; raycaster.far = Math.max(0, distance - .18);
        if (!raycaster.intersectObjects(geometries, false).length) setView('fly');
      }
    }
    drag = null;
  };
  canvas.addEventListener('pointerup', release);
  canvas.addEventListener('pointercancel', release);
  canvas.addEventListener('lostpointercapture', release);
  canvas.addEventListener('wheel', (event) => {
    event.preventDefault();
    if (flyView) {
      cameraMovedSinceHud = true;
      orbitDistance = THREE.MathUtils.clamp(orbitDistance * Math.exp(event.deltaY * .001), .3, 3);
      orbitCamera();
      return;
    }
    camera.getWorldDirection(forward);
    moveCamera(movement.copy(forward).multiplyScalar(-THREE.MathUtils.clamp(event.deltaY * .012, -4, 4)));
  }, { passive: false });
  const movementKeys = new Set(['KeyW', 'KeyA', 'KeyS', 'KeyD', 'KeyQ', 'KeyE',
    'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ShiftLeft', 'ShiftRight']);
  addEventListener('keydown', (event) => {
    if (['SELECT', 'INPUT', 'TEXTAREA', 'BUTTON'].includes(document.activeElement.tagName)) return;
    if (!flyView && movementKeys.has(event.code)) {
      keys.add(event.code); event.preventDefault(); lastFrame = performance.now(); invalidate();
    }
  });
  addEventListener('keyup', (event) => keys.delete(event.code));
  addEventListener('blur', () => { keys.clear(); drag = null; });
  document.addEventListener('visibilitychange', () => {
    keys.clear(); lastFrame = performance.now();
    if (document.hidden) {
      cancelAnimationFrame(scheduledFrame);
      scheduledFrame = 0;
    } else invalidate();
  });
  document.querySelectorAll('[data-move]').forEach((button) => {
    button.addEventListener('pointerdown', (event) => {
      event.preventDefault(); button.setPointerCapture(event.pointerId);
      keys.add(button.dataset.move);
      lastFrame = performance.now(); invalidate();
    });
    for (const name of ['pointerup', 'pointercancel', 'lostpointercapture']) {
      button.addEventListener(name, () => keys.delete(button.dataset.move));
    }
  });
  addEventListener('resize', () => {
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
    renderer.setPixelRatio(Math.min(1, Math.sqrt(pixelBudget / (innerWidth * innerHeight))));
    renderer.setSize(innerWidth, innerHeight);
    if (flyView) orbitCamera();
    invalidate();
  });
}

async function start() {
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
    const gl = renderer.getContext();
    const debug = gl.getExtension('WEBGL_debug_renderer_info');
    graphicsDevice = debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : '';
    softwareGraphics = /swiftshader|llvmpipe|software/i.test(graphicsDevice);
    if (softwareGraphics) {
      pixelBudget = 360000;
    }
    $('#graphics-mode').textContent = `${softwareGraphics ? 'SOFTWARE' : graphicsDevice ? 'GPU' : 'WEBGL'} · 30 FPS TARGET`;
    $('#graphics-mode').title = softwareGraphics
      ? `${graphicsDevice}. Enable hardware acceleration in your browser to use the GPU.`
      : graphicsDevice || 'The browser does not expose its graphics device.';
    renderer.setPixelRatio(Math.min(1, Math.sqrt(pixelBudget / (innerWidth * innerHeight))));
    renderer.setSize(innerWidth, innerHeight);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.shadowMap.autoUpdate = false;
    renderer.shadowMap.needsUpdate = true;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    canvas.addEventListener('webglcontextlost', (event) => {
      event.preventDefault();
      graphicsLost = true;
      fail('The graphics context was lost. Reload the page to resume viewing.');
    });
    canvas.addEventListener('webglcontextrestored', () => {
      graphicsLost = false;
      renderer.setSize(innerWidth, innerHeight);
      renderer.shadowMap.needsUpdate = true;
      invalidate();
      $('#loading').hidden = true;
    });
    const response = await fetch('/api/world');
    if (!response.ok) throw new Error('The environment service did not respond.');
    world = await response.json();
    if (world.neural) {
      const { createNeuralPanel } = await import('./neural.js');
      neuralPanel = createNeuralPanel(world.neural, world.motor, command);
    }
    await buildWorld();
    const [animal, initial] = await Promise.all([
      createFly(world.fly_body, scene),
      fetch('/api/state').then((r) => { if (!r.ok) throw new Error('Physics unavailable.'); return r.json(); }),
    ]);
    fly = animal;
    $('#fly-mass').textContent = `${world.fly_body.mass_mg.toFixed(3)} mg`;
    updateState(initial);
    setView('fly', true);
    bindControls();
    drawMap();
    const events = new EventSource('/api/events');
    events.onmessage = (event) => updateState(JSON.parse(event.data));
    events.onerror = () => setConnected(false);
    addEventListener('pagehide', () => {
      events.close(); clearInterval(hudTimer);
      cancelAnimationFrame(scheduledFrame);
    }, { once: true });
    $('#loading').hidden = !graphicsLost;
    invalidate();
    hudTimer = setInterval(updateHud, 1000);
    // Read-only observability for browser checks; no simulation control hidden here.
    Object.defineProperty(window, 'environmentDebug', { get: () => ({
      ready: !graphicsLost, frames, camera: camera.position.toArray(), direction: camera.getWorldDirection(new THREE.Vector3()).toArray(),
      renderedGeoms: geometries.length, modelHash: world.model_sha256,
      simulation: state ? structuredClone(state) : null, connected,
      drawCalls: renderer.info.render.calls, triangles: renderer.info.render.triangles,
      renderLimit, pixelBudget, graphicsDevice, softwareGraphics, renderCostMs,
      fly: { selected: flyView, visible: fly.visible, poseRevision: fly.revision,
        position: fly.position.toArray(), bodies: world.fly_body.bodies.length },
      geometryCount: renderer.info.memory.geometries, textureCount: renderer.info.memory.textures,
    }) });
  } catch (error) {
    console.error(error);
    fail(error.message || 'Check WebGL 2 support and reload the page.');
  }
}

start();
