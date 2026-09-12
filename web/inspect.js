// One shared tooltip. It does work only in response to pointer/focus events.
export function setupTooltips() {
  const box = document.getElementById('inspector-tooltip');
  let anchor = null;
  function hide() {
    anchor?.removeAttribute('aria-describedby');
    anchor = null;
    box.hidden = true;
  }
  function show(target) {
    if (!target?.dataset.tooltip) return;
    if (anchor !== target) hide();
    anchor = target;
    box.textContent = target.dataset.tooltip;
    box.hidden = false;
    target.setAttribute('aria-describedby', box.id);
    // Action hints belong above the whole bar, never over its other buttons.
    const rect = (target.closest('#fly-actions') || target).getBoundingClientRect();
    const width = box.offsetWidth, height = box.offsetHeight;
    box.style.left = `${Math.max(10, Math.min(innerWidth - width - 10, rect.left + rect.width / 2 - width / 2))}px`;
    const top = rect.top > height + 20 ? rect.top - height - 9 : rect.bottom + 9;
    box.style.top = `${Math.max(10, Math.min(innerHeight - height - 10, top))}px`;
  }
  const targetOf = (event) => event.target.closest?.('[data-tooltip]');
  document.addEventListener('pointerover', (event) => {
    if (event.pointerType === 'mouse') show(targetOf(event));
  });
  document.addEventListener('pointerout', (event) => {
    if (anchor && (event.target === anchor || anchor.contains(event.target) || box.contains(event.target))
        && !anchor.contains(event.relatedTarget) && !box.contains(event.relatedTarget)) hide();
  });
  document.addEventListener('focusin', (event) => show(targetOf(event)));
  document.addEventListener('focusout', (event) => { if (anchor?.contains(event.target)) hide(); });
  document.addEventListener('click', (event) => {
    const target = targetOf(event);
    if (target && (target.tagName !== 'BUTTON' || target.getAttribute('aria-disabled') === 'true')) show(target);
    else if (!box.contains(event.target)) hide();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !box.hidden) {
      hide(); event.preventDefault(); event.stopPropagation();
    }
  }, true);
  document.addEventListener('scroll', hide, true);
  addEventListener('resize', hide);
  document.addEventListener('visibilitychange', hide);
  return { refresh(target) { if (target === anchor) show(target); } };
}

export function sampleTooltip(canvas, samples, describe, refresh, duration) {
  const explanation = canvas.dataset.tooltip;
  const inspect = (event) => {
    const history = samples();
    if (!history?.length) return;
    const rect = canvas.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width * canvas.width;
    const ms = Math.max(0, Math.min(duration, (x - 85) / (canvas.width - 93) * duration));
    const sample = history.reduce((best, item) => Math.abs(item.ms - ms) < Math.abs(best.ms - ms) ? item : best);
    canvas.dataset.tooltip = describe(sample);
    refresh(canvas);
  };
  canvas.addEventListener('pointermove', inspect);
  canvas.addEventListener('pointerdown', inspect);
  canvas.addEventListener('pointerleave', () => { canvas.dataset.tooltip = explanation; });
  canvas.addEventListener('focus', () => {
    const history = samples();
    canvas.dataset.tooltip = history?.length ? describe(history.at(-1)) : explanation;
    refresh(canvas);
  });
}
