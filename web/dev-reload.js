// Development only: page reload for frontend edits; Python restarts in Docker.
let previous;
async function check() {
  if (!document.hidden) {
    try {
      const response = await fetch('/api/dev-version', { cache: 'no-store' });
      if (response.ok) {
        const current = await response.text();
        if (previous && previous !== current) { location.reload(); return; }
        previous = current;
      }
    } catch { /* The supervisor may be restarting the backend. */ }
  }
  setTimeout(check, 1500);
}
check();
