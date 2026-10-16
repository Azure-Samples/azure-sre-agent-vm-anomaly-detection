// Polls the local aggregator and drives the HUD and the 3D scene.
import { renderHud, renderOffline, showActionProblem, STAGES } from './hud.js';
import { StatusScene } from './scene.js';

const ui = { pin: null, director: true };
let snapshot = null;

const scene = new StatusScene(
  document.getElementById('scene'),
  document.getElementById('tooltip'),
  (id) => (snapshot && id ? snapshot.links[id] : null),
);

function effectiveStage() {
  if (!ui.pin) return snapshot.stage;
  return { ...snapshot.stage, current: ui.pin, waiting_for: 'none', detail: '' };
}

function render() {
  if (!snapshot) return;
  const stage = effectiveStage();
  renderHud(snapshot, stage, ui);
  scene.update(snapshot, stage);
}

async function poll() {
  try {
    const response = await fetch('/api/snapshot', { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    snapshot = await response.json();
    render();
  } catch (error) {
    renderOffline(`Aggregator unreachable · ${error.message}`);
  }
  setTimeout(poll, snapshot?.refresh_ms ?? 5000);
}

document.getElementById('controls').addEventListener('click', async (event) => {
  const button = event.target.closest('button[data-action]');
  if (!button || button.disabled) return;
  button.disabled = true;
  let problem = '';
  try {
    const response = await fetch(`/api/actions/${encodeURIComponent(button.dataset.action)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Dashboard-Action': '1' },
      body: '{}',
    });
    if (response.status === 409) problem = 'another action is still running';
    else if (!response.ok) problem = `rejected (HTTP ${response.status})`;
  } catch (error) {
    problem = error.message;
  }
  if (problem) showActionProblem(button.textContent.trim(), problem);
});

window.addEventListener('keydown', (event) => {
  if (event.target.closest?.('input, textarea')) return;
  const key = event.key.toLowerCase();
  if (key === 'd') {
    ui.director = !ui.director;
    scene.setDirector(ui.director);
  } else if (key >= '1' && key <= '4') {
    ui.pin = STAGES[Number(key) - 1];
  } else if (key === '0' || key === 'escape') {
    ui.pin = null;
  } else {
    return;
  }
  render();
});

poll();
