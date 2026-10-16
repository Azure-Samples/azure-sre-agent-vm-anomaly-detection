// Click-through helpers shared by the HUD and the 3D scene.

const TARGETS = [
  ['portal.azure.com', 'azure-portal'],
  ['github.com', 'github'],
];

export function safeUrl(url) {
  try {
    return new URL(url).protocol === 'https:' ? url : null;
  } catch {
    return null;
  }
}

// One reused tab per destination system keeps the presenter from piling up tabs.
export function targetFor(url) {
  const host = new URL(url).hostname;
  const match = TARGETS.find(([domain]) => host === domain || host.endsWith(`.${domain}`));
  return match ? match[1] : 'sre-agent';
}

export function openLink(link) {
  const url = link && safeUrl(link.url);
  if (!url) return;
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.target = targetFor(url);
  anchor.click();
}
