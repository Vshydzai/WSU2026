import { normalizeEndpoint } from './api-client.mjs';

export function filterItems(items, search = '', enabled = 'all') {
  const needle = search.trim().toLocaleLowerCase();
  return items.filter(item =>
    (enabled === 'all' || item.enabled === (enabled === 'enabled')) &&
    `${item.name} ${item.url}`.toLocaleLowerCase().includes(needle));
}

export function connectionMode(endpoint, config, origin) {
  const url = new URL(normalizeEndpoint(endpoint));
  if (config.demo && url.href.replace(/\/+$/, '') === normalizeEndpoint(new URL('/api', origin).href)) {
    return { label: 'Local simulator', kind: 'demo',
      detail: 'Rehearsal only. Data lives in memory and resets when the server stops. No AWS calls or deployment evidence.' };
  }
  if (url.protocol === 'http:' || ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)) {
    return { label: 'Local API', kind: 'local', detail: 'Connected to a loopback API. This is not proof of an AWS deployment.' };
  }
  const awsHost = /^[a-z0-9]+\.execute-api\.[a-z0-9-]+\.amazonaws\.com(?:\.cn)?$/.test(url.hostname);
  return { label: awsHost ? 'AWS API' : 'Public API', kind: 'live',
    detail: 'CRUD requests go directly to this endpoint. Confirm the environment before changing targets. No credentials are sent.' };
}

export class PageHistory {
  constructor() { this.reset(); }
  reset() { this.cursors = [null]; this.index = 0; }
  get cursor() { return this.cursors[this.index]; }
  get page() { return this.index + 1; }
  get hasPrevious() { return this.index > 0; }
  next(cursor) {
    if (typeof cursor !== 'string' || !cursor) return false;
    this.cursors = this.cursors.slice(0, this.index + 1);
    this.cursors.push(cursor);
    this.index++;
    return true;
  }
  previous() { if (this.hasPrevious) { this.index--; return true; } return false; }
}
