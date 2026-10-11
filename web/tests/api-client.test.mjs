import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ApiClient, ApiError, normalizeEndpoint, safeTargetUrl, validateItem } from '../api-client.mjs';

const item = { id: 'target-1', name: 'Example', url: 'https://example.com/', enabled: true,
  created_at: '2026-10-11T00:00:00Z', updated_at: '2026-10-11T00:00:00Z' };
const reply = (data, status = 200) => new Response(status === 204 ? null : JSON.stringify(data), { status });
const endpoint = 'https://example.execute-api.us-east-2.amazonaws.com/beta/';

test('keeps the API stage and removes trailing slashes', () => {
  assert.equal(normalizeEndpoint(` ${endpoint} `), endpoint.slice(0, -1));
});
test('allows HTTP only on exact loopback hosts', () => {
  for (const host of ['localhost', '127.0.0.1', '[::1]']) assert.equal(normalizeEndpoint(`http://${host}:8787/api/`), `http://${host}:8787/api`);
  for (const value of ['http://example.com', 'http://localhost.evil.com', 'ftp://example.com', '/api',
    'https://user:pass@example.com', 'https://example.com/?x=1', 'https://example.com/#a', 'garbage']) {
    assert.throws(() => normalizeEndpoint(value), ApiError);
  }
});
test('only safe HTTP(S) target links become clickable', () => {
  assert.equal(safeTargetUrl('https://example.com'), 'https://example.com/');
  for (const value of ['javascript:alert(1)', 'data:text/html,hello', 'https://user:pass@example.com', 'bad']) assert.equal(safeTargetUrl(value), null);
});
test('rejects malformed targets before the view receives them', () => {
  assert.equal(validateItem(item), item);
  for (const value of [null, { ...item, id: '../secret' }, { ...item, id: 123 }, { ...item, enabled: 'true' },
    { ...item, name: ' ' }, { ...item, url: 'javascript:alert(1)' }, { ...item, created_at: '' }, { ...item, updated_at: null }]) {
    assert.throws(() => validateItem(value), /invalid target/);
  }
});
test('list preserves an opaque cursor and sends no credentials or JSON preflight header', async () => {
  let sent;
  const cursor = 'abc+/= &?';
  const client = new ApiClient(endpoint, { fetchImpl: async (url, options) => { sent = { url, options }; return reply({ items: [item], next_cursor: cursor }); } });
  assert.deepEqual(await client.list({ limit: 10, cursor }), { items: [item], next_cursor: cursor });
  const url = new URL(sent.url);
  assert.equal(url.pathname, '/beta/targets');
  assert.equal(url.searchParams.get('cursor'), cursor);
  assert.equal(sent.options.credentials, 'omit');
  assert.equal(sent.options.redirect, 'error');
  assert.equal(sent.options.headers['Content-Type'], undefined);
});
test('default page size is 25', async () => {
  const client = new ApiClient(endpoint, { fetchImpl: async url => { assert.equal(new URL(url).searchParams.get('limit'), '25'); return reply({ items: [], next_cursor: null }); } });
  assert.deepEqual(await client.list(), { items: [], next_cursor: null });
});
test('refuses out-of-range page sizes without making a request', async () => {
  const client = new ApiClient(endpoint, { fetchImpl: () => assert.fail('Unexpected request') });
  for (const limit of [0, 101, 1.5]) await assert.rejects(client.list({ limit }), /Page size/);
});
test('rejects missing or malformed list/cursor response shapes', async () => {
  for (const data of [null, [], { items: {} }, { items: [], next_cursor: 4 }, { items: [null], next_cursor: null }]) {
    const client = new ApiClient(endpoint, { fetchImpl: async () => reply(data) });
    await assert.rejects(client.list(), ApiError);
  }
});
test('CRUD methods enforce status, ID and JSON contracts', async () => {
  const calls = [];
  const client = new ApiClient(endpoint, { fetchImpl: async (url, options) => {
    calls.push({ url, options });
    return reply(item, options.method === 'POST' ? 201 : options.method === 'DELETE' ? 204 : 200);
  } });
  assert.deepEqual(await client.create(item), item);
  assert.deepEqual(await client.get(item.id), item);
  assert.deepEqual(await client.update(item.id, item), item);
  await client.delete(item.id);
  assert.deepEqual(calls.map(call => call.options.method), ['POST', 'GET', 'PUT', 'DELETE']);
  assert.equal(calls[0].options.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(calls[2].options.body), item);
  assert.ok(calls.slice(1).every(call => new URL(call.url).pathname === '/beta/targets/target-1'));
  for (const id of ['../secret', '', 'a'.repeat(65), 123]) await assert.rejects(client.get(id), /Invalid target ID/);
  assert.equal(calls.length, 4);
});
test('reports actionable validation, missing, throttling and storage failures', async () => {
  for (const [status, text] of [[400, 'rejected'], [404, 'no longer exists'], [429, 'busy'], [500, 'encountered'], [503, 'unavailable'], [403, 'HTTP 403']]) {
    const client = new ApiClient(endpoint, { fetchImpl: async () => reply({ error: 'Server detail' }, status) });
    await assert.rejects(client.get(item.id), error => error.status === status && error.message.includes(text) && error.message.includes('Server detail'));
  }
});
test('handles gateway error bodies without assuming JSON', async () => {
  const client = new ApiClient(endpoint, { fetchImpl: async () => new Response('Unavailable', { status: 503 }) });
  await assert.rejects(client.list(), /temporarily unavailable/);
});
test('rejects successful non-JSON and unexpected success status', async () => {
  const invalid = new ApiClient(endpoint, { fetchImpl: async () => new Response('Not JSON', { status: 200 }) });
  await assert.rejects(invalid.list(), /invalid JSON/);
  const wrong = new ApiClient(endpoint, { fetchImpl: async () => reply(item, 202) });
  await assert.rejects(wrong.create(item), /Unexpected API status/);
});
test('network failures provide CORS guidance and never retry writes', async () => {
  let calls = 0;
  const client = new ApiClient(endpoint, { fetchImpl: async () => { calls++; throw new TypeError('Failed to fetch'); } });
  await assert.rejects(client.create(item), /CORS.*Refresh before retrying/);
  assert.equal(calls, 1);
});
test('aborts timed-out writes and explains the uncertain outcome', async () => {
  let calls = 0;
  const client = new ApiClient(endpoint, { timeoutMs: 5, fetchImpl: async (_url, { signal }) => {
    calls++;
    return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('Aborted'))));
  } });
  await assert.rejects(client.create(item), /timed out.*may have completed/);
  assert.equal(calls, 1);
});
test('records method, HTTP status and browser round trip on successes and failures', async () => {
  const records = [];
  const client = new ApiClient(endpoint, { onRequest: data => records.push(data), fetchImpl: async () => reply(item) });
  await client.get(item.id);
  client.fetchImpl = async () => { throw new Error('offline'); };
  await assert.rejects(client.get(item.id));
  assert.deepEqual(records.map(({ method, status }) => ({ method, status })), [{ method: 'GET', status: 200 }, { method: 'GET', status: 0 }]);
  assert.ok(records.every(record => record.durationMs >= 0));
});
test('the default fetch implementation works with a loopback response and an empty body', async () => {
  const previous = globalThis.fetch;
  globalThis.fetch = async function () {
    // Browser fetch requires its native Window receiver; an unbound class property fails.
    assert.equal(this, globalThis);
    return new Response(null, { status: 204 });
  };
  try { await new ApiClient('http://127.0.0.1:8787/api').delete('target-1'); } finally { globalThis.fetch = previous; }
});
