// HTML overlay: panels, timeline, events and top bar rendered from one snapshot.
import { safeUrl, targetFor } from './links.js';

export const STAGES = ['alerting', 'interim', 'rca', 'permanent'];
const ORDER = ['healthy', ...STAGES, 'resolved'];
const STAGE_TITLES = {
  healthy: 'Healthy', alerting: '1 Alerting', interim: '2 Interim action', rca: '3 Root cause analysis',
  permanent: '4 Permanent action', resolved: 'Resolved',
};
const THRESHOLD = 0.8;
const COLORS = { healthy: '#3ddc97', warning: '#ffb020', anomaly: '#ff5d5d', waiting: '#b07cff', idle: '#5a6890' };
const STALE_SEC = 180;

const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const hhmm = (iso) => (iso ? `${iso.slice(11, 19)}Z` : '–');
const num = (value, digits = 0) => (value == null ? '–' : Number(value).toFixed(digits));

export function scoreState(score) {
  if (score == null) return 'idle';
  if (score >= THRESHOLD) return 'anomaly';
  return score >= 0.6 ? 'warning' : 'healthy';
}

function link(snapshot, id, html) {
  const item = snapshot.links[id];
  const url = item && safeUrl(item.url);
  if (!url) return html;
  const suffix = snapshot.mode === 'demo' ? ' · demo data' : '';
  return `<a class="lnk${item.exact ? '' : ' fallback'}" href="${esc(url)}" target="${targetFor(url)}"
    title="${esc(item.label + suffix)}">${html} <span class="arrow">↗</span></a>`;
}

function bar(fraction, state) {
  const width = Math.max(0, Math.min(1, fraction ?? 0)) * 100;
  const color = COLORS[state];
  return `<svg class="bar" viewBox="0 0 100 10" preserveAspectRatio="none"><rect width="100" height="10" fill="#1d2a4d"/>
    <rect width="${width.toFixed(1)}" height="10" fill="${color}"/></svg>`;
}

function sparkline(series) {
  const points = series.slice(-60);
  const y = (score) => (70 - Math.min(1, score) * 64).toFixed(1);
  const step = 260 / Math.max(1, points.length - 1);
  const path = points.map((p, i) => `${(i * step).toFixed(1)},${y(p.score)}`).join(' ');
  return `<svg class="spark" viewBox="0 0 260 74" preserveAspectRatio="none" role="img" aria-label="Score, last 60 minutes">
    <line x1="0" x2="260" y1="${y(THRESHOLD)}" y2="${y(THRESHOLD)}" stroke="${COLORS.warning}" stroke-dasharray="5 4"/>
    <polyline points="${path}" fill="none" stroke="${COLORS.anomaly}" stroke-width="2.5" vector-effect="non-scaling-stroke"/></svg>`;
}

function renderDetector(s) {
  const d = s.state.detector;
  const state = scoreState(d.score);
  const groups = Object.entries(d.groups).map(([name, value]) => `<div class="row"><span>${esc(name)}</span>
    ${bar(value, scoreState(value))}<span class="mono">${num(value, 2)}</span></div>`).join('');
  return `<h2>${link(s, 'detector', 'Detector · anomaly score')}</h2>
    <div class="score"><span class="big s-${state}">${num(d.score, 2)}</span>
      <span class="muted small">VMAnomalyScore_CL<br>max of groups · threshold ${THRESHOLD.toFixed(2)}<br>bin ${hhmm(d.latest_bin)}</span></div>
    ${sparkline(d.series)}<div class="dim small">last 60 min</div>${groups}
    <div class="row small"><span class="muted">TopFeature</span><span class="mono">${esc(d.top_feature ?? '–')}</span></div>
    <div class="row small"><span class="muted">scored by</span>${link(s, 'function', 'Function App')}</div>`;
}

function renderVm(s) {
  const { power_state: power, metrics: m, service: svc } = s.state;
  const powerState = power === 'running' ? 'healthy' : power ? 'anomaly' : 'idle';
  const memState = scoreState(s.state.detector.groups.memory);
  return `<h2>${link(s, 'vm', `VM · ${esc(s.environment.vm_name)}`)}</h2>
    <div class="row"><span><i class="dot s-${powerState}"></i>Power state: ${esc(power ?? 'unknown')}</span></div>
    <div class="row"><span>${link(s, 'perf', 'Memory used')}</span>${bar((m.mem_used_pct ?? 0) / 100, memState)}<span class="mono">${num(m.mem_used_pct, 1)} %</span></div>
    <div class="row"><span>CPU ${num(m.cpu_pct, 1)} %</span><span>Disk ${num(m.disk_used_pct, 0)} %</span></div>
    <div class="row">${link(s, 'syslog', `demo-app rss <b>${num(svc.rss_mb)}</b> MB · cache ${num(svc.cache_entries)}${svc.archive_entries == null ? '' : ` · archive ${num(svc.archive_entries)}`}`)}</div>
    <div class="row small"><span class="muted">version</span>${link(s, 'syslog', `<span class="mono">${esc(svc.version ?? '–')}</span>`)}</div>
    <div class="row small"><span class="muted">deployed</span><span>${hhmm(svc.deployed_at)}</span></div>`;
}

function renderAgent(s) {
  const a = s.state.agent;
  if (!a.thread_id) {
    return `<h2>${link(s, 'agent', 'SRE Agent')}</h2><p class="muted small">No incident thread in the current window.</p>`;
  }
  const steps = a.steps.slice(-5).map((step) => `<li><span class="s-healthy">✓</span>
    <span class="time">${hhmm(step.time)}</span><span>${esc(step.text)}</span></li>`).join('');
  const approvals = a.approvals.map((ap) => `<div class="approval"><div class="title pulse">● AWAITING APPROVAL</div>
    <div class="action">${esc(ap.action)}</div>
    <div class="row small"><span class="muted">requested ${hhmm(ap.requested_at)} · Review mode</span>${link(s, 'approval', '<b>Open thread</b>')}</div></div>`).join('');
  return `<h2>${link(s, 'agent', 'SRE Agent · thread')}</h2><div><b>${esc(a.title ?? a.thread_id)}</b></div>
    <ul class="steps">${steps}</ul>${approvals}`;
}

function runText(run) {
  if (!run) return ['idle', 'no runs'];
  if (!run.conclusion) return ['warning', `${run.status} · ${run.head_sha.slice(0, 7)}`];
  const state = run.conclusion === 'success' ? 'healthy' : 'anomaly';
  return [state, `${run.conclusion} · ${run.created_at ? run.created_at.slice(11, 16) : '–'}Z · ${run.head_sha.slice(0, 7)}`];
}

function renderTicket(s) {
  const { alerts, ticket } = s.state;
  const rows = alerts.map((al) => {
    const state = al.condition === 'Fired' ? 'anomaly' : 'healthy';
    const text = al.condition === 'None' ? 'not fired' : `${al.condition}${al.severity ? ` · ${al.severity}` : ''}`;
    const name = al.key === 'ml' ? 'ML anomaly alert' : 'Memory-low alert';
    return `<div class="row"><span><i class="dot s-${state}"></i>${link(s, `alert:${al.key}`, `${name}: ${esc(text)}`)}</span></div>`;
  });
  const issue = ticket.issue;
  const issueState = !issue ? 'idle' : issue.state === 'closed' ? 'healthy' : issue.labels.includes('approved') ? 'healthy' : 'waiting';
  rows.push(`<div class="row"><span><i class="dot s-${issueState}"></i>${issue
    ? link(s, 'issue', `Issue #${issue.number} ${esc(issue.state)} · ${esc(issue.labels.join(', '))}`)
    : '<span class="muted">Incident issue: not created</span>'}</span></div>`);
  const pull = ticket.pull;
  const pullState = !pull ? 'idle' : pull.merged ? 'healthy' : 'waiting';
  rows.push(`<div class="row"><span><i class="dot s-${pullState}"></i>${pull
    ? link(s, 'pull', `Fix PR #${pull.number} ${pull.merged ? 'merged' : esc(pull.state)}`)
    : '<span class="muted">Fix PR: none</span>'}</span></div>`);
  for (const workflow of ['incident-approved', 'deploy-app']) {
    const [state, text] = runText(ticket.runs.find((r) => r.workflow === workflow));
    rows.push(`<div class="row"><span><i class="dot s-${state}"></i>${link(s, `run:${workflow}`, `${workflow}.yml: ${esc(text)}`)}</span></div>`);
  }
  return `<h2>${link(s, 'repo', 'Alerts · Ticket · Delivery')}</h2>${rows.join('')}`;
}

function renderTimeline(s, stage) {
  const current = ORDER.indexOf(stage.current);
  const chevrons = STAGES.map((name, i) => {
    const index = i + 1;
    let cls = 'stage';
    let sub = '';
    if (stage.current === 'resolved' || current > index) {
      cls += ' done';
      sub = '✓';
    } else if (current === index) {
      cls += ` active ${stage.waiting_for}`;
      sub = stage.waiting_for === 'human' ? '● waiting for human' : esc(stage.detail);
    }
    const body = `${STAGE_TITLES[name]}<small>${sub}</small>`;
    const item = s.links[`stage:${name}`];
    const url = item && safeUrl(item.url);
    return url
      ? `<a class="${cls}" href="${esc(url)}" target="${targetFor(url)}" title="${esc(item.label)}">${body}</a>`
      : `<div class="${cls}">${body}</div>`;
  });
  chevrons.push('<div class="stage doc">5 Horizontal deployment<small>not implemented</small></div>');
  chevrons.push('<div class="stage doc">6 Postmortem<small>not implemented</small></div>');
  return chevrons.join('');
}

function renderEvents(s) {
  const items = s.events.slice(-5).map((e) => `<li><span class="src">${hhmm(e.time)} ${esc(e.source)}</span>${
    e.link_id ? link(s, e.link_id, esc(e.message)) : esc(e.message)}</li>`).join('');
  return `<h2>Events</h2><ol>${items || '<li class="muted">No events yet</li>'}</ol>`;
}

function bannerState(stage) {
  if (stage.current === 'healthy' || stage.current === 'resolved') return 'healthy';
  return stage.waiting_for === 'human' ? 'waiting' : 'anomaly';
}

function renderBanner(s, stage, pinned) {
  const waiting = stage.waiting_for === 'human' ? 'waiting for human' : stage.detail;
  const text = stage.current === 'healthy' ? 'HEALTHY · All systems normal'
    : stage.current === 'resolved' ? `RESOLVED · ${stage.detail}`
      : `INCIDENT · ${STAGE_TITLES[stage.current]}${waiting ? ` · ${waiting}` : ''}`;
  return `${link(s, `stage:${stage.current}`, esc(text))}${pinned ? ' <span class="dim">(pinned)</span>' : ''}`;
}

function renderEnv(s) {
  const failing = s.sources.filter((src) => !src.ok);
  const ages = s.sources.map((src) => src.age_sec).filter((age) => age != null);
  const age = ages.length ? Math.max(...ages) : null;
  const stale = age == null || age > STALE_SEC;
  const health = failing.length
    ? `<i class="dot s-anomaly"></i>${failing.length} source(s) failing: ${esc(failing.map((f) => f.name).join(', '))}`
    : `<i class="dot ${stale ? 'stale' : 's-healthy'}"></i>all sources OK`;
  const title = esc(s.sources.map((src) => `${src.name}: ${src.ok ? 'ok' : src.error}`).join('\n'));
  return `${esc(s.environment.resource_group)} · ${esc(s.environment.vm_name)} · ${hhmm(s.generated_at)}<br>
    <span title="${title}">${health} · data ${age == null ? '–' : Math.round(age)} s old</span>`;
}

export function renderHud(s, stage, ui) {
  const set = (id, html) => { document.getElementById(id).innerHTML = html; };
  const mode = document.getElementById('mode');
  mode.textContent = s.mode.toUpperCase();
  mode.className = `badge ${s.mode}`;
  const banner = document.getElementById('banner');
  banner.className = `banner s-${bannerState(stage)}`;
  banner.innerHTML = renderBanner(s, stage, ui.pin != null);
  set('env', renderEnv(s));
  set('detector', renderDetector(s));
  set('vm', renderVm(s));
  set('agent', renderAgent(s));
  set('ticket', renderTicket(s));
  set('timeline', renderTimeline(s, stage));
  set('events', renderEvents(s));
  renderControls(s);
  document.getElementById('director-state').textContent = ui.director ? '(on)' : '(off)';
}

const ACTION_ICONS = { 'inject-memory-leak': '▶', restore: '↺' };
let controlsKey = '';

function renderControls(s) {
  const actions = s.actions;
  if (!actions) return;
  const current = actions.current;
  const running = current?.state === 'running';
  const vmDown = s.mode === 'live' && s.state.power_state !== 'running';
  const key = JSON.stringify([current, running, vmDown]);
  if (key === controlsKey) return;
  controlsKey = key;
  const buttons = actions.available.map((a) => {
    const blocked = running || (vmDown && a.name === 'inject-memory-leak');
    const why = running ? 'Another action is running' : blocked ? 'vm-app-01 is not running' : a.description;
    return `<button type="button" data-action="${esc(a.name)}" data-description="${esc(a.description)}"
      class="${a.name === 'inject-memory-leak' ? 'danger' : ''}" title="${esc(why)}" ${blocked ? 'disabled' : ''}>
      ${ACTION_ICONS[a.name] ?? ''} ${esc(a.label)}</button>`;
  });
  let status = '';
  if (current) {
    const mark = { running: '⏳', succeeded: '✓', failed: '✕' }[current.state];
    const cls = { running: 's-warning', succeeded: 's-healthy', failed: 's-anomaly' }[current.state];
    const detail = current.state === 'running' ? `started ${hhmm(current.started_at)}` : esc(current.message);
    status = `<span class="action-status" title="${esc(current.label)}: ${esc(current.message)}"><span class="${cls}">${mark}</span> ${detail}</span>`;
  }
  document.getElementById('controls').innerHTML = buttons.join('') + status;
}

export function showActionProblem(label, problem) {
  controlsKey = '';
  const status = document.createElement('span');
  status.className = 'action-status';
  status.innerHTML = `<span class="s-anomaly">✕</span> ${esc(label)} · ${esc(problem)}`;
  document.getElementById('controls').append(status);
}

export function renderOffline(message) {
  const banner = document.getElementById('banner');
  banner.className = 'banner s-idle';
  banner.textContent = message;
}
