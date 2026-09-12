import { createMotorPanel } from './motor.js';
import { sampleTooltip } from './inspect.js';

const $ = (id) => document.getElementById(id);
const svgNS = 'http://www.w3.org/2000/svg';
const format = (number) => Number(number || 0).toLocaleString('en-US');

function svgElement(tag, attributes = {}) {
  const element = document.createElementNS(svgNS, tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  return element;
}

export function createNeuralPanel(descriptor, motorDescriptor, tooltips) {
  const stylesheet = document.createElement('link');
  stylesheet.rel = 'stylesheet';
  stylesheet.href = '/neural.css';
  document.head.append(stylesheet);
  const panel = $('neural-panel'), open = $('neural-open');
  let state = null, rendered = -1;
  const motor = createMotorPanel(motorDescriptor, tooltips);
  const nodeElements = new Map(), readoutElements = new Map();
  open.hidden = false;
  function select(kind) {
    const isMotor = kind === 'motor';
    $('motor-readout').hidden = !isMotor;
    $('antenna-readout').hidden = isMotor;
    for (const [id, selected] of [['motor-tab', isMotor], ['antenna-tab', !isMotor]]) {
      $(id).setAttribute('aria-selected', String(selected));
      $(id).tabIndex = selected ? 0 : -1;
    }
    motor.render(); render();
  }
  for (const [id, kind] of [['motor-tab', 'motor'], ['antenna-tab', 'antenna']]) {
    $(id).addEventListener('click', () => select(kind));
    $(id).addEventListener('keydown', (event) => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      const other = kind === 'motor' ? 'antenna' : 'motor';
      select(other); $(`${other}-tab`).focus();
    });
  }

  function show(value) {
    panel.hidden = !value;
    document.body.classList.toggle('neural-open', value);
    open.setAttribute('aria-expanded', String(value));
    if (value) {
      motor.render();
      render();
      $('neural-close').focus();
    } else open.focus();
  }
  open.addEventListener('click', () => show(panel.hidden));
  $('neural-close').addEventListener('click', () => show(false));
  panel.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') { event.stopPropagation(); show(false); }
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { render(); motor.render(); } });

  if (!descriptor.available) {
    $('neural-unavailable').textContent = descriptor.error || 'Neural reference unavailable.';
    $('neural-unavailable').hidden = false;
    $('neural-content').hidden = true;
    return { update() {}, select() {} };
  }
  $('neural-dataset').textContent = `${(descriptor.neuron_count / 1000).toFixed(1)}k neurons`;
  $('neural-dataset').dataset.tooltip = `${descriptor.dataset}: ${format(descriptor.neuron_count)} neurons. The published FlyWire 630 specimen, not MaleCNS.`;
  $('neural-graph-size').textContent = `${(descriptor.edge_count / 1e6).toFixed(2)}M links`;
  $('neural-graph-size').dataset.tooltip = `All ${format(descriptor.edge_count)} stored directed connections, with signed synapse counts preserved.`;
  $('neural-provenance').href = `https://github.com/philshiu/Drosophila_brain_model/tree/${descriptor.reference_commit}`;
  const diagram = $('neural-graph');
  const nodes = descriptor.diagram.nodes;
  const readouts = new Set(descriptor.readouts.map((item) => item.index));
  const columns = [
    nodes.filter((item) => item.role === 'sensory'),
    nodes.filter((item) => item.role !== 'sensory' && !readouts.has(item.index)),
    nodes.filter((item) => readouts.has(item.index)),
  ];
  const positions = new Map();
  columns.forEach((items, column) => {
    const title = svgElement('text', { x: 62 + column * 148, y: 15, 'text-anchor': 'middle', class: 'graph-column' });
    title.textContent = ['INPUT', 'NETWORK', 'READOUTS'][column];
    diagram.append(title);
    items.forEach((item, row) => {
      positions.set(item.index, { x: 62 + column * 148, y: 34 + (row + .5) * 250 / items.length });
    });
  });
  for (const edge of descriptor.diagram.edges) {
    const from = positions.get(edge.source), to = positions.get(edge.target);
    const path = svgElement('path', {
      d: `M${from.x},${from.y} C${from.x + 44},${from.y} ${to.x - 44},${to.y} ${to.x},${to.y}`,
      class: edge.count > 0 ? 'graph-excitatory' : 'graph-inhibitory',
      'marker-end': edge.count > 0 ? 'url(#neural-arrow)' : 'url(#neural-stop)',
    });
    const title = svgElement('title');
    title.textContent = `${edge.source} → ${edge.target}: ${edge.count} signed synapses`;
    path.dataset.tooltip = title.textContent;
    path.append(title);
    diagram.append(path);
  }
  for (const item of nodes) {
    const { x, y } = positions.get(item.index);
    const group = svgElement('g', { class: 'graph-node' });
    const circle = svgElement('circle', { cx: x, cy: y, r: 5 });
    const label = svgElement('text', { x: x + 10, y: y + 3.5 });
    label.textContent = item.label;
    const title = svgElement('title');
    title.textContent = `FlyWire ID ${item.id}`;
    group.append(circle, label, title);
    group.setAttribute('tabindex', '0');
    group.dataset.tooltip = title.textContent;
    diagram.append(group);
    nodeElements.set(item.index, { group, circle, title, item });
  }
  for (const item of descriptor.readouts) {
    const row = document.createElement('tr');
    const name = document.createElement('th');
    name.scope = 'row';
    name.textContent = item.label;
    name.title = `${item.role} · FlyWire ID ${item.id}`;
    row.tabIndex = 0;
    row.dataset.tooltip = name.title;
    const spikes = document.createElement('td'), voltage = document.createElement('td');
    spikes.textContent = voltage.textContent = '—';
    row.append(name, spikes, voltage);
    $('neural-readouts').append(row);
    readoutElements.set(item.index, { spikes, voltage, row, item });
  }
  sampleTooltip($('neural-timeline'), () => state?.history,
    (bin) => `${bin.ms - 5}–${bin.ms} ms\nInput: ${bin.input} spikes\nNetwork: ${bin.network} spikes\nDescending readouts: ${bin.descending} spikes`,
    tooltips.refresh, descriptor.total_ms);

  function drawHistory(history) {
    const canvas = $('neural-timeline'), context = canvas.getContext('2d');
    const width = canvas.width, height = canvas.height;
    context.clearRect(0, 0, width, height);
    context.font = '10px monospace';
    const rows = [['input', '#a6d7ca', 'Input'], ['network', '#e3be80', 'Network'],
      ['descending', '#b5b3e6', 'Descending']];
    rows.forEach(([key, color, label], row) => {
      const top = row * 43 + 5, base = top + 27;
      context.fillStyle = '#aab8bc';
      context.fillText(label, 0, top + 16);
      context.strokeStyle = '#c3d9dc26';
      context.beginPath(); context.moveTo(85, base); context.lineTo(width - 8, base); context.stroke();
      const maximum = Math.max(1, ...history.map((bin) => bin[key]));
      const step = (width - 93) / 30;
      context.fillStyle = color;
      history.forEach((bin, i) => {
        const h = bin[key] / maximum * 24;
        context.fillRect(85 + i * step, base - h, Math.max(1, step - 2), h);
      });
    });
    context.fillStyle = '#aab8bc';
    context.fillText('0', 85, height - 3);
    context.fillText('100', width - 138, height - 3);
    context.fillText('150 ms', width - 46, height - 3);
    context.setLineDash([3, 4]);
    context.strokeStyle = '#c3d9dc55';
    const end = 85 + (width - 93) * 2 / 3;
    context.beginPath(); context.moveTo(end, 0); context.lineTo(end, 128); context.stroke();
    context.setLineDash([]);
  }

  function render() {
    if (panel.hidden || $('antenna-readout').hidden || document.hidden || !state || rendered === state.revision) return;
    rendered = state.revision;
    const idle = state.status === 'idle';
    const names = { stimulus: 'Antennal stimulus', baseline: 'No input', blocked: 'Sensory output blocked' };
    $('neural-status').textContent = idle ? 'Antenna · Ready'
      : state.error || `${names[state.mode]} · ${state.status === 'running' ? 'Running' : state.status === 'complete' ? 'Complete' : state.status}`;
    $('neural-progress').value = state.simulated_ms || 0;
    $('neural-time').textContent = `${(state.simulated_ms || 0).toFixed(0)} / ${descriptor.total_ms} ms`;
    $('neural-wall').textContent = idle ? 'On demand' : `${(state.wall_seconds || 0).toFixed(2)} s elapsed`;
    $('neural-wall').dataset.tooltip = `Elapsed wall time: ${(state.wall_seconds || 0).toFixed(2)} s. Thread CPU time: ${(state.cpu_seconds || 0).toFixed(3)} s.`;
    $('neural-spikes').textContent = idle ? '—' : format(state.total_spikes);
    $('neural-downstream').textContent = idle ? '—' : format(state.downstream_spikes);
    $('neural-active').textContent = idle ? '—' : format(state.neurons_that_spiked);
    const measurements = new Map((state.nodes || []).map((node) => [node.index, node]));
    for (const [index, element] of nodeElements) {
      const value = measurements.get(index);
      const count = value?.spikes || 0;
      element.group.classList.toggle('has-spikes', count > 0);
      element.circle.setAttribute('r', String(5 + Math.min(4, Math.log2(1 + count))));
      element.title.textContent = `FlyWire ID ${element.item.id} · ${count} trial spikes${value ? ` · ${value.voltage_mv.toFixed(2)} mV` : ''}`;
      element.group.dataset.tooltip = `${element.item.label}\n${element.title.textContent}`;
    }
    for (const [index, cells] of readoutElements) {
      const value = (state.readouts || []).find((item) => item.index === index);
      cells.spikes.textContent = value ? format(value.spikes) : '—';
      cells.voltage.textContent = value ? `${value.voltage_mv.toFixed(2)} mV` : '—';
      cells.row.dataset.tooltip = `${cells.item.label} · ${cells.item.role}\nFlyWire ID ${cells.item.id}\n${cells.spikes.textContent} spikes · ${cells.voltage.textContent}`;
    }
    drawHistory(state.history || []);
    const descending = (state.readouts || []).filter((item) => item.role === 'descending')
      .reduce((sum, item) => sum + item.spikes, 0);
    $('workflow-readout').classList.toggle('measured', descending > 0);
    $('workflow-brain').classList.toggle('measured', state.downstream_spikes > 0);
  }

  return {
    update(next, motorState) {
      motor.update(motorState);
      if (!next || next.revision === state?.revision) return;
      state = next;
      render();
    },
    select,
  };
}
