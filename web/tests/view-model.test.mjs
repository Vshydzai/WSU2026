import assert from 'node:assert/strict';
import { test } from 'node:test';
import { connectionMode, filterItems, PageHistory } from '../view-model.mjs';

const items = [{ name: 'University', url: 'https://wsu.edu.au', enabled: true }, { name: 'Example', url: 'https://example.com', enabled: false }];
test('filters the current page by name, URL and enabled state without modifying the data', () => {
  assert.deepEqual(filterItems(items), items);
  assert.deepEqual(filterItems(items, ' UNIVERSITY '), [items[0]]);
  assert.deepEqual(filterItems(items, 'example.com', 'disabled'), [items[1]]);
  assert.deepEqual(filterItems(items, '', 'enabled'), [items[0]]);
  assert.deepEqual(filterItems(items, 'not here'), []);
  assert.equal(items.length, 2);
});
test('simulator label applies only to the configured local simulator endpoint', () => {
  const origin = 'http://127.0.0.1:8787';
  assert.equal(connectionMode(`${origin}/api/`, { demo: true }, origin).kind, 'demo');
  assert.equal(connectionMode(`${origin}/other`, { demo: true }, origin).kind, 'local');
  assert.equal(connectionMode(`${origin}/api`, { demo: false }, origin).kind, 'local');
});
test('distinguishes real AWS gateway hostnames from arbitrary public endpoints', () => {
  assert.equal(connectionMode('https://abc123.execute-api.us-east-2.amazonaws.com/beta', {}, '').label, 'AWS API');
  assert.equal(connectionMode('https://abc.execute-api.cn-north-1.amazonaws.com.cn/prod', {}, '').label, 'AWS API');
  assert.equal(connectionMode('https://execute-api.us-east-2.amazonaws.com.evil.com', {}, '').label, 'Public API');
  assert.equal(connectionMode('https://localhost:8787/api', {}, '').kind, 'local');
});
test('pagination keeps opaque cursors and restores previous pages', () => {
  const history = new PageHistory();
  assert.equal(history.cursor, null);
  assert.equal(history.page, 1);
  assert.equal(history.previous(), false);
  assert.equal(history.next(null), false);
  assert.equal(history.next(''), false);
  assert.equal(history.next('opaque+/=1'), true);
  assert.equal(history.cursor, 'opaque+/=1');
  assert.equal(history.page, 2);
  assert.equal(history.hasPrevious, true);
  history.next('second');
  assert.equal(history.previous(), true);
  assert.equal(history.cursor, 'opaque+/=1');
  history.next('replacement');
  assert.deepEqual(history.cursors, [null, 'opaque+/=1', 'replacement']);
  history.reset();
  assert.equal(history.page, 1);
  assert.equal(history.hasPrevious, false);
});
