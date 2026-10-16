// Three.js topology: nodes, data-flow edges, approval gates, director camera, click-through.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DObject, CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';
import { openLink } from './links.js';
import { scoreState } from './hud.js';

const COLOR = {
  healthy: 0x3ddc97, warning: 0xffb020, anomaly: 0xff5d5d, waiting: 0xb07cff, idle: 0x5a6890, info: 0x5b7bd5,
};
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
const DRAG_PX = 5;
const Y = 1;

const LAYOUT = {
  vm: [-6, Y, 1.2], law: [-4, Y, -2.8], detector: [0, Y, -4.2], alert: [4, Y, -2.8], agent: [6, Y, 1.2],
  github: [1.8, Y, 4.4],
};
const CAMERA = {
  healthy: { pos: [0, 14, 20], look: [0, 0, 2] },
  alerting: { pos: [1, 13, 18], look: [1, 0, 1.2] },
  interim: { pos: [0, 12.5, 18], look: [0, 0, 2.2] },
  rca: { pos: [1.5, 12, 17], look: [1.5, 0, 1.5] },
  permanent: { pos: [-0.5, 12.5, 18], look: [-0.5, 0, 3] },
  resolved: { pos: [0, 14, 20], look: [0, 0, 2] },
};
const EDGES = [
  ['vm', 'law'], ['law', 'detector'], ['detector', 'alert'], ['alert', 'agent'],
  ['agent', 'vm', 'gate1'], ['agent', 'github'], ['github', 'vm', 'gate2'],
];

const ICON_PX = 256;
const PLATFORM_Y = -0.85;

function material(color) {
  return new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.12, metalness: 0.5, roughness: 0.45 });
}

function glow(radius, color) {
  return new THREE.Mesh(
    new THREE.SphereGeometry(radius, 24, 16),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false }),
  );
}

// Official service icon drawn on a round backplate so it reads on the dark scene.
function iconSprite(name) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = ICON_PX;
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const image = new Image();
  image.onload = () => {
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = 'rgba(22, 33, 63, 0.92)';
    ctx.beginPath();
    ctx.arc(ICON_PX / 2, ICON_PX / 2, ICON_PX / 2 - 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.drawImage(image, ICON_PX * 0.2, ICON_PX * 0.2, ICON_PX * 0.6, ICON_PX * 0.6);
    texture.needsUpdate = true;
  };
  image.src = `icons/${name}.svg`;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, alphaTest: 0.05 }));
  sprite.scale.set(1.8, 1.8, 1);
  return sprite;
}

function label(html) {
  const div = document.createElement('div');
  div.className = 'label';
  div.innerHTML = html;
  return new CSS2DObject(div);
}

export class StatusScene {
  constructor(container, tooltip, getLink) {
    this.container = container;
    this.tooltip = tooltip;
    this.getLink = getLink;
    this.director = true;
    this.stage = 'healthy';
    this.state = {};
    this.timer = new THREE.Timer();

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    container.appendChild(this.renderer.domElement);
    this.labels = new CSS2DRenderer();
    this.labels.domElement.className = 'labels';
    container.appendChild(this.labels.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0b1020);
    this.scene.fog = new THREE.Fog(0x0b1020, 22, 40);
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    this.camera.position.set(...CAMERA.healthy.pos);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.enabled = false;
    this.controls.target.set(...CAMERA.healthy.look);

    this.scene.add(new THREE.HemisphereLight(0x9fb4ff, 0x0b1020, 1.4));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(4, 10, 6);
    this.scene.add(sun);
    this.scene.add(new THREE.PolarGridHelper(8.5, 0, 4, 96, 0x1b2647, 0x1b2647));

    this.hits = [];
    this.nodes = {};
    this.buildNodes();
    this.buildEdges();
    this.bindPointer();
    window.addEventListener('resize', () => this.resize());
    this.resize();
    this.renderer.setAnimationLoop((time) => this.frame(time));
  }

  addNode(id, icon, name) {
    const group = new THREE.Group();
    group.position.set(...LAYOUT[id]);
    const base = new THREE.Mesh(new THREE.CylinderGeometry(0.95, 1.05, 0.14, 48), material(COLOR.idle));
    base.position.y = PLATFORM_Y;
    const rim = new THREE.Mesh(new THREE.TorusGeometry(1.05, 0.03, 8, 64), new THREE.MeshBasicMaterial({ color: COLOR.idle }));
    rim.rotation.x = Math.PI / 2;
    rim.position.y = PLATFORM_Y + 0.07;
    const sprite = iconSprite(icon);
    sprite.position.y = 0.25;
    const tag = label(`<b>${name}</b><span></span>`);
    tag.position.set(0, -1.75, 0.6);
    const hit = new THREE.Mesh(
      new THREE.SphereGeometry(1.4, 12, 8),
      new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }),
    );
    hit.userData.id = id;
    group.add(base, rim, sprite, tag, hit);
    this.hits.push(hit);
    this.scene.add(group);
    this.nodes[id] = { group, base, rim, sprite, tag, status: tag.element.querySelector('span'), phase: Math.random() * 6 };
    return this.nodes[id];
  }

  tint(id, color) {
    const node = this.nodes[id];
    node.base.material.color.setHex(color);
    node.base.material.emissive.setHex(color);
    node.rim.material.color.setHex(color);
  }

  buildNodes() {
    const vm = this.addNode('vm', 'vm', 'vm-app-01');
    const track = new THREE.Mesh(new THREE.RingGeometry(1.2, 1.36, 64),
      new THREE.MeshBasicMaterial({ color: 0x1d2a4d, side: THREE.DoubleSide }));
    track.rotation.x = -Math.PI / 2;
    track.position.y = PLATFORM_Y - 0.1;
    vm.gauge = new THREE.Mesh(new THREE.RingGeometry(1.2, 1.36, 64, 1, 0, 0.01),
      new THREE.MeshBasicMaterial({ color: COLOR.healthy, side: THREE.DoubleSide }));
    vm.gauge.rotation.x = -Math.PI / 2;
    vm.gauge.position.y = PLATFORM_Y - 0.09;
    vm.group.add(track, vm.gauge);

    this.addNode('law', 'log-analytics', 'Log Analytics');
    const detector = this.addNode('detector', 'function-app', 'Detector');
    detector.score = label('<span class="big">–</span>');
    detector.score.position.set(0, 1.55, 0);
    detector.group.add(detector.score);

    const alert = this.addNode('alert', 'alerts', 'Azure Monitor alert');
    alert.glow = glow(1.15, COLOR.anomaly);
    alert.glow.position.y = 0.25;
    alert.group.add(alert.glow);

    const agent = this.addNode('agent', 'sre-agent', 'SRE Agent');
    agent.ring = new THREE.Mesh(new THREE.TorusGeometry(1.2, 0.05, 8, 64), new THREE.MeshBasicMaterial({ color: COLOR.waiting }));
    agent.ring.rotation.x = Math.PI / 2;
    agent.ring.position.y = 0.25;
    agent.glow = glow(1.15, COLOR.waiting);
    agent.glow.position.y = 0.25;
    agent.group.add(agent.ring, agent.glow);

    const github = this.addNode('github', 'github', 'GitHub');
    github.chips = [-0.5, 0, 0.5].map((x) => {
      const chip = new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.17, 0.1, 24), material(COLOR.idle));
      chip.position.set(x, PLATFORM_Y + 0.12, -0.55);
      github.group.add(chip);
      return chip;
    });
  }

  setGauge(fraction, color) {
    const gauge = this.nodes.vm.gauge;
    gauge.geometry.dispose();
    gauge.geometry = new THREE.RingGeometry(1.2, 1.36, 64, 1, Math.PI / 2, -Math.max(0.01, fraction) * Math.PI * 2);
    gauge.material.color.setHex(color);
  }

  buildEdges() {
    this.edges = EDGES.map(([from, to, gateId]) => {
      const a = new THREE.Vector3(...LAYOUT[from]);
      const b = new THREE.Vector3(...LAYOUT[to]);
      const mid = a.clone().lerp(b, 0.5);
      mid.y += 1.2;
      const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(curve.getPoints(60)),
        new THREE.LineDashedMaterial({ color: COLOR.idle, dashSize: 0.25, gapSize: 0.2 }),
      );
      line.computeLineDistances();
      this.scene.add(line);
      const particles = Array.from({ length: 5 }, (_, i) => {
        const dot = new THREE.Mesh(new THREE.SphereGeometry(0.09, 10, 8), new THREE.MeshBasicMaterial({ color: COLOR.healthy }));
        dot.userData.t = i / 5;
        dot.visible = false;
        this.scene.add(dot);
        return dot;
      });
      const edge = { id: `${from}-${to}`, curve, line, particles, active: false };
      if (gateId) edge.gate = this.buildGate(gateId, curve);
      return edge;
    });
  }

  buildGate(id, curve) {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.55, 0.1, 12, 40), new THREE.MeshBasicMaterial({ color: COLOR.idle }));
    const at = curve.getPoint(0.5);
    ring.position.copy(at);
    ring.rotation.x = Math.PI / 2;
    const hit = new THREE.Mesh(new THREE.SphereGeometry(0.9, 12, 8),
      new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }));
    hit.position.copy(at);
    hit.userData.id = id;
    const tag = label(`<span>${id === 'gate1' ? 'gate 1 · approve restart' : 'gate 2 · approved label'}</span>`);
    tag.position.copy(at).add(new THREE.Vector3(0, -0.9, 0));
    this.scene.add(ring, hit, tag);
    this.hits.push(hit);
    return { ring, tag };
  }

  linkIdFor(id) {
    const s = this.snapshot;
    if (!s) return null;
    const has = (key) => key in s.links;
    const map = {
      vm: 'vm', law: 'law', detector: 'detector', alert: 'alert:ml',
      agent: has('approval') ? 'approval' : 'agent',
      github: has('pull') ? 'pull' : has('issue') ? 'issue' : 'repo',
      gate1: has('approval') ? 'approval' : 'agent',
      gate2: has('issue') ? 'issue' : 'repo',
    };
    return map[id];
  }

  bindPointer() {
    const el = this.renderer.domElement;
    const ray = new THREE.Raycaster();
    const pick = (event) => {
      const rect = el.getBoundingClientRect();
      const pointer = new THREE.Vector2(((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1);
      ray.setFromCamera(pointer, this.camera);
      const hit = ray.intersectObjects(this.hits, false)[0];
      return hit ? hit.object.userData.id : null;
    };
    let down = null;
    el.addEventListener('pointerdown', (e) => { down = { x: e.clientX, y: e.clientY }; });
    el.addEventListener('pointerup', (e) => {
      if (down && Math.hypot(e.clientX - down.x, e.clientY - down.y) < DRAG_PX) {
        const node = pick(e);
        if (node) openLink(this.getLink(this.linkIdFor(node)));
      }
      down = null;
    });
    el.addEventListener('pointermove', (e) => {
      const node = pick(e);
      const link = node && this.getLink(this.linkIdFor(node));
      this.hover = link ? node : null;
      document.body.classList.toggle('hovering', Boolean(link));
      this.tooltip.hidden = !link;
      if (!link) return;
      const demo = this.snapshot.mode === 'demo' ? ' · demo data' : '';
      this.tooltip.innerHTML = '';
      const title = document.createElement('b');
      title.textContent = `${link.label} ↗`;
      const url = document.createElement('span');
      url.className = 'dim';
      url.textContent = `${new URL(link.url).hostname}${link.exact ? '' : ' · overview'}${demo}`;
      this.tooltip.append(title, url);
      this.tooltip.style.left = `${e.clientX + 16}px`;
      this.tooltip.style.top = `${e.clientY + 12}px`;
    });
    el.addEventListener('pointerleave', () => { this.tooltip.hidden = true; document.body.classList.remove('hovering'); });
  }

  setDirector(on) {
    this.director = on;
    this.controls.enabled = !on;
  }

  update(s, stage) {
    this.snapshot = s;
    this.stage = stage.current;
    const { detector, alerts, agent, ticket, metrics, service, power_state: power } = s.state;
    const score = detector.score;
    const scoreLevel = scoreState(score);
    const ml = alerts.find((a) => a.key === 'ml');
    const fired = ml?.condition === 'Fired';
    const waitingHuman = stage.waiting_for === 'human';

    const vm = this.nodes.vm;
    const mem = Math.min(1, (metrics.mem_used_pct ?? 0) / 100);
    const vmLevel = !power ? 'idle' : power !== 'running' ? 'anomaly' : scoreState(detector.groups.memory);
    this.tint('vm', COLOR[vmLevel]);
    this.setGauge(mem, COLOR[vmLevel === 'idle' ? 'healthy' : vmLevel]);
    vm.status.textContent = `mem ${metrics.mem_used_pct ?? '–'} % · rss ${service.rss_mb ?? '–'} MB`;

    this.nodes.law.status.textContent = 'Perf · Syslog · Scores';
    this.tint('law', metrics.mem_used_pct != null ? COLOR.healthy : COLOR.idle);
    this.tint('detector', COLOR[scoreLevel]);
    this.nodes.detector.score.element.firstChild.textContent = score == null ? '–' : score.toFixed(2);
    this.nodes.detector.status.textContent = 'Function · every 1 min';

    this.tint('alert', fired ? COLOR.anomaly : ml?.condition === 'Resolved' ? COLOR.healthy : COLOR.idle);
    this.nodes.alert.status.textContent = ml ? (ml.condition === 'None' ? 'not fired' : `${ml.condition} · ${ml.severity ?? ''}`) : '–';

    const approvals = agent.approvals.length > 0;
    const agentColor = approvals ? COLOR.waiting : stage.current === 'resolved' ? COLOR.healthy : agent.thread_id ? COLOR.info : COLOR.idle;
    this.tint('agent', agentColor);
    this.nodes.agent.ring.visible = approvals;
    this.nodes.agent.status.textContent = approvals ? 'waiting for approval' : agent.thread_id ? stage.detail : 'idle';

    const [issueCard, pullCard, runCard] = this.nodes.github.chips;
    const issue = ticket.issue;
    const pull = ticket.pull;
    const deploy = ticket.runs.find((r) => r.workflow === 'deploy-app');
    this.paint(issueCard, !issue ? COLOR.idle : issue.state === 'closed' ? COLOR.healthy : COLOR.waiting);
    this.paint(pullCard, !pull ? COLOR.idle : pull.merged ? COLOR.healthy : COLOR.waiting);
    this.paint(runCard, !deploy ? COLOR.idle : !deploy.conclusion ? COLOR.warning : deploy.conclusion === 'success' ? COLOR.healthy : COLOR.anomaly);
    this.nodes.github.status.textContent = issue ? `#${issue.number} ${issue.state}${pull ? ` · PR #${pull.number}` : ''}` : 'issue · PR · Actions';
    this.tint('github', !issue ? COLOR.idle : issue.state === 'closed' ? COLOR.healthy : waitingHuman ? COLOR.waiting : COLOR.info);

    const inIncident = !['healthy', 'resolved'].includes(stage.current);
    const deploying = pull?.merged && deploy && !deploy.conclusion;
    const flows = {
      'vm-law': [power === 'running', COLOR.healthy],
      'law-detector': [detector.latest_bin != null, COLOR.healthy],
      'detector-alert': [scoreLevel === 'anomaly', COLOR.anomaly],
      'alert-agent': [fired, COLOR.anomaly],
      'agent-vm': [['interim', 'rca'].includes(stage.current), COLOR.waiting],
      'agent-github': [inIncident && issue != null, COLOR.waiting],
      'github-vm': [Boolean(deploying) || (stage.current === 'permanent' && stage.detail.startsWith('Verifying')), COLOR.healthy],
    };
    for (const edge of this.edges) {
      const [active, color] = flows[edge.id];
      edge.active = Boolean(active);
      edge.line.material.color.setHex(edge.active ? color : COLOR.idle);
      edge.line.material.dashSize = edge.active ? 10 : 0.25;
      edge.particles.forEach((p) => { p.material.color.setHex(color); p.visible = edge.active && !REDUCED; });
    }
    const [gate1, gate2] = this.edges.filter((e) => e.gate).map((e) => e.gate);
    const gate2Waiting = stage.current === 'permanent' && waitingHuman;
    gate1.ring.material.color.setHex(approvals ? COLOR.waiting : this.stagePassed('interim') ? COLOR.healthy : COLOR.idle);
    gate2.ring.material.color.setHex(gate2Waiting ? COLOR.waiting : pull?.merged ? COLOR.healthy : COLOR.idle);
    this.gatesWaiting = [approvals, gate2Waiting];
    this.pulsing = { alert: fired, agent: approvals };
  }

  stagePassed(name) {
    const order = ['healthy', 'alerting', 'interim', 'rca', 'permanent', 'resolved'];
    return order.indexOf(this.stage) > order.indexOf(name);
  }

  paint(mesh, color) {
    mesh.material.color.setHex(color);
    mesh.material.emissive.setHex(color);
  }

  resize() {
    const { clientWidth: w, clientHeight: h } = this.container;
    this.renderer.setSize(w, h);
    this.labels.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  frame(time) {
    this.timer.update(time);
    const dt = Math.min(this.timer.getDelta(), 0.1);
    const t = this.timer.getElapsed();
    if (this.director) {
      const shot = CAMERA[this.stage] ?? CAMERA.healthy;
      const k = REDUCED ? 1 : 1 - Math.exp(-dt * 2.5);
      this.camera.position.lerp(new THREE.Vector3(...shot.pos), k);
      this.controls.target.lerp(new THREE.Vector3(...shot.look), k);
      if (!REDUCED && ['healthy', 'resolved'].includes(this.stage)) {
        this.camera.position.x += Math.sin(t * 0.15) * 0.02;
      }
    }
    this.controls.update();
    for (const edge of this.edges ?? []) {
      if (!edge.active || REDUCED) continue;
      for (const p of edge.particles) {
        p.userData.t = (p.userData.t + dt * 0.35) % 1;
        p.position.copy(edge.curve.getPoint(p.userData.t));
      }
    }
    const wave = REDUCED ? 1 : 0.5 + 0.5 * Math.sin(t * 3);
    if (this.pulsing) {
      this.nodes.alert.glow.material.opacity = this.pulsing.alert ? 0.08 + 0.1 * wave : 0;
      this.nodes.agent.glow.material.opacity = this.pulsing.agent ? 0.06 + 0.1 * wave : 0;
      this.nodes.agent.ring.scale.setScalar(1 + (REDUCED ? 0 : 0.08 * wave));
      const [g1, g2] = this.edges.filter((e) => e.gate).map((e) => e.gate);
      g1.ring.scale.setScalar(this.gatesWaiting[0] ? 1 + 0.15 * wave : 1);
      g2.ring.scale.setScalar(this.gatesWaiting[1] ? 1 + 0.15 * wave : 1);
    }
    for (const node of Object.values(this.nodes)) {
      node.sprite.position.y = 0.25 + (REDUCED ? 0 : Math.sin(t * 1.2 + node.phase) * 0.06);
      const hovered = this.hover != null && node.group.children.some((c) => c.userData.id === this.hover);
      node.group.scale.setScalar(hovered ? 1.08 : 1);
    }
    this.renderer.render(this.scene, this.camera);
    this.labels.render(this.scene, this.camera);
  }
}
