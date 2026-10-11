import { test as base, expect } from '@playwright/test';

const test = base.extend({
  makeTarget: async ({ request }, use) => {
    const created = [];
    await use(async fields => {
      const response = await request.post('/api/targets', { data: { name: 'Browser target', url: 'https://example.com', enabled: true, ...fields } });
      expect(response.status()).toBe(201);
      const item = await response.json();
      created.push(item.id);
      return item;
    });
    for (const id of created) await request.delete(`/api/targets/${id}`);
  },
});

async function open(page) {
  await page.goto('/');
  await expect(page.locator('#mode-label')).toHaveText('Local simulator');
  await expect(page.locator('#refresh')).toBeEnabled();
  await expect(page.locator('#connection-status')).toContainText('Connected');
}

const card = (page, name) => page.locator('.target-card').filter({ has: page.getByRole('heading', { name, exact: true }) });

test('loads a responsive, accessible simulator view with honest metrics', async ({ page }, testInfo) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await open(page);
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await expect(page.locator('#mode-detail')).toContainText('No AWS calls');
  await expect(page.locator('#total-count')).toHaveText('2');
  await expect(page.locator('#enabled-count')).toHaveText('1');
  await expect(page.locator('#request-detail')).toContainText('GET · HTTP 200 · browser time');
  await expect(page.getByLabel('Name', { exact: true })).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/dashboard-${testInfo.project.name}.png`, fullPage: true });
  expect(errors).toEqual([]);
});

test('creates, reads, updates, disables and deletes through actual HTTP requests', async ({ page, request }) => {
  await open(page);
  await page.getByLabel('Name', { exact: true }).fill('CRUD rehearsal');
  await page.getByLabel('Website URL').fill('https://example.com/docs');
  await page.getByRole('button', { name: 'Create target' }).click();
  await expect(page.locator('#notice')).toContainText('Target created. Page 1 refreshed.');
  const target = card(page, 'CRUD rehearsal');
  const id = await target.getAttribute('data-target-id');
  try {
    await expect(target).toBeVisible();
    await target.getByRole('button', { name: 'Edit:' }).click();
    await expect(page.getByRole('heading', { name: 'Edit target' })).toBeVisible();
    await page.getByLabel('Name', { exact: true }).fill('CRUD updated');
    await page.getByRole('button', { name: 'Save changes' }).click();
    await expect(page.locator('#notice')).toContainText('Target updated. Page 1 refreshed.');
    const updated = card(page, 'CRUD updated');
    await updated.getByRole('button', { name: 'Disable:' }).click();
    await expect(updated.locator('.target-state')).toHaveText('Disabled');
    expect((await (await request.get(`/api/targets/${id}`)).json()).enabled).toBe(false);
    await updated.getByRole('button', { name: 'Enable:' }).click();
    await expect(updated.locator('.target-state')).toHaveText('Enabled');
    await updated.getByRole('button', { name: 'Delete:' }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.getByRole('button', { name: 'Delete target', exact: true }).click();
    await expect(page.locator('#notice')).toContainText('Target deleted. Page 1 refreshed.');
    await expect(updated).toHaveCount(0);
    expect((await request.get(`/api/targets/${id}`)).status()).toBe(404);
  } finally { if (id) await request.delete(`/api/targets/${id}`); }
});

test('filters only this page and cancels edit and delete without writes', async ({ page, makeTarget, request }) => {
  const item = await makeTarget({ name: 'Filter rehearsal', enabled: false });
  await open(page);
  await page.getByLabel('Filter this page').fill('filter rehearsal');
  await expect(page.locator('.target-card')).toHaveCount(1);
  await page.getByLabel('State', { exact: true }).selectOption('enabled');
  await expect(page.getByRole('heading', { name: 'No matches on this page' })).toBeVisible();
  await page.getByLabel('State', { exact: true }).selectOption('disabled');
  await card(page, item.name).getByRole('button', { name: 'Edit:' }).click();
  await page.getByLabel('Name', { exact: true }).fill('Unsaved');
  await page.getByRole('button', { name: 'Cancel editing' }).click();
  await expect(page.getByRole('heading', { name: 'New target', exact: true })).toBeVisible();
  await card(page, item.name).getByRole('button', { name: 'Delete:' }).click();
  await page.getByRole('button', { name: 'Keep target' }).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await card(page, item.name).getByRole('button', { name: 'Delete:' }).click();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).not.toBeVisible();
  expect((await (await request.get(`/api/targets/${item.id}`)).json()).name).toBe(item.name);
});

test('navigates opaque cursor pages and restores page 1', async ({ page, makeTarget }) => {
  for (let index = 0; index < 26; index++) await makeTarget({ name: `Pagination ${index}` });
  await open(page);
  await expect(page.locator('.target-card')).toHaveCount(25);
  const firstIds = await page.locator('.target-card').evaluateAll(nodes => nodes.map(node => node.dataset.targetId));
  await page.getByRole('button', { name: 'Next' }).click();
  await expect(page.locator('#page-label')).toHaveText('Page 2');
  await expect(page.locator('.target-card')).toHaveCount(3);
  const secondIds = await page.locator('.target-card').evaluateAll(nodes => nodes.map(node => node.dataset.targetId));
  expect(secondIds.every(id => !firstIds.includes(id))).toBe(true);
  await page.getByRole('button', { name: 'Previous' }).click();
  await expect(page.locator('#page-label')).toHaveText('Page 1');
  expect(await page.locator('.target-card').evaluateAll(nodes => nodes.map(node => node.dataset.targetId))).toEqual(firstIds);
});

test('renders untrusted API names as text rather than HTML', async ({ page, makeTarget }) => {
  const name = '<img src=x onerror="window.injected=true">';
  await makeTarget({ name });
  await open(page);
  await expect(card(page, name)).toBeVisible();
  expect(await page.locator('#target-list img').count()).toBe(0);
  expect(await page.evaluate(() => window.injected)).toBeUndefined();
  const link = card(page, name).getByRole('link');
  await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
});

test('shows server validation failures and preserves the unsaved form', async ({ page }) => {
  await open(page);
  await page.getByLabel('Name', { exact: true }).fill('Invalid local address');
  await page.getByLabel('Website URL').fill('http://127.0.0.1');
  await page.getByRole('button', { name: 'Create target' }).click();
  await expect(page.getByRole('alert')).toContainText('rejected');
  await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Invalid local address');
  await expect(page.locator('#request-detail')).toContainText('POST · HTTP 400');
  await expect(page.locator('.target-card')).toHaveCount(2);
});

test('keeps last loaded data labelled stale on throttling and recovers on refresh', async ({ page }) => {
  await open(page);
  await page.route('**/api/targets?*', route => route.fulfill({ status: 429, contentType: 'application/json', body: '{"message":"Too Many Requests"}' }));
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('busy');
  await expect(page.locator('#list-summary')).toContainText('Last loaded data');
  await expect(page.locator('.target-card')).toHaveCount(2);
  await page.unroute('**/api/targets?*');
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.getByRole('alert')).not.toBeVisible();
  await expect(page.locator('#list-summary')).not.toContainText('Last loaded data');
});

test('disables duplicate submissions while a write is in flight', async ({ page, request }) => {
  await open(page);
  let count = 0;
  let release;
  const held = new Promise(resolve => { release = resolve; });
  await page.route('**/api/targets', async route => {
    if (route.request().method() === 'POST') { count++; await held; }
    await route.continue();
  });
  await page.getByLabel('Name', { exact: true }).fill('Single submission');
  await page.getByLabel('Website URL').fill('https://example.com');
  await page.getByRole('button', { name: 'Create target' }).click();
  try {
    await expect(page.getByRole('button', { name: 'Create target' })).toBeDisabled();
    await expect(page.locator('#connect-button')).toBeDisabled();
    await page.locator('#target-form').evaluate(form => { form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
  } finally { release(); }
  await expect(page.locator('#notice')).toContainText('Target created. Page 1 refreshed.');
  expect(count).toBe(1);
  const id = await card(page, 'Single submission').getAttribute('data-target-id');
  await request.delete(`/api/targets/${id}`);
});

test('changes the simulator label when connecting a different public endpoint', async ({ page }) => {
  await open(page);
  await page.route('https://api.example.com/**', route => route.fulfill({ status: 200,
    headers: { 'Access-Control-Allow-Origin': '*' }, contentType: 'application/json', body: '{"items":[],"next_cursor":null}' }));
  await page.getByLabel('API endpoint').fill('https://api.example.com/beta/');
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  await expect(page.locator('#mode-label')).toHaveText('Public API');
  await expect(page.locator('#mode-detail')).not.toContainText('Rehearsal');
  await expect(page.getByRole('heading', { name: 'Your queue is empty' })).toBeVisible();
});

test('blocks unsafe endpoint changes without sending requests', async ({ page }) => {
  await open(page);
  let sent = false;
  page.on('request', req => { if (req.url().includes('outside.example.com')) sent = true; });
  await page.getByLabel('API endpoint').fill('http://outside.example.com/api');
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('HTTPS API URL');
  expect(sent).toBe(false);
});

test('manual mode remembers an endpoint but sends no API requests until Connect', async ({ page }) => {
  await page.route('**/config.json', route => route.fulfill({ status: 200, contentType: 'application/json',
    body: '{"demo":false,"api_url":"","environment":""}' }));
  await page.addInitScript(() => localStorage.setItem('webhealth.endpoint', `${location.origin}/api`));
  const requests = [];
  page.on('request', req => { if (new URL(req.url()).pathname.startsWith('/api/')) requests.push(req.url()); });
  await page.goto('/');
  await expect(page.getByLabel('API endpoint')).toHaveValue('http://127.0.0.1:8787/api');
  await expect(page.locator('#mode-label')).toHaveText('Not connected');
  await expect(page.getByLabel('Name', { exact: true })).toBeDisabled();
  expect(requests).toEqual([]);
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  await expect(page.locator('#connection-status')).toContainText('Connected');
  await expect(page.locator('#mode-label')).toHaveText('Local API');
  expect(requests.length).toBe(1);
});

test('a failed next-page request retains the current cursor and page data', async ({ page, makeTarget }) => {
  for (let index = 0; index < 26; index++) await makeTarget({ name: `Cursor failure ${index}` });
  await open(page);
  const before = await page.locator('.target-card').evaluateAll(nodes => nodes.map(node => node.dataset.targetId));
  await page.route('**/api/targets?*', route => route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"Storage temporarily unavailable"}' }));
  await page.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByRole('alert')).toContainText('unavailable');
  await expect(page.locator('#page-label')).toHaveText('Page 1');
  expect(await page.locator('.target-card').evaluateAll(nodes => nodes.map(node => node.dataset.targetId))).toEqual(before);
  await page.unroute('**/api/targets?*');
  await page.getByRole('button', { name: 'Next' }).click();
  await expect(page.locator('#page-label')).toHaveText('Page 2');
});

test('a completed write followed by a failed reload remains visible as an uncertain list', async ({ page, request }) => {
  await open(page);
  await page.route('**/api/targets?*', route => route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"Storage temporarily unavailable"}' }));
  await page.getByLabel('Name', { exact: true }).fill('Write before reload failure');
  await page.getByLabel('Website URL').fill('https://example.com');
  await page.getByRole('button', { name: 'Create target' }).click();
  await expect(page.getByRole('alert')).toContainText('unavailable');
  await expect(page.locator('#notice')).toContainText('Target created. Reloading page 1');
  await expect(page.locator('#list-summary')).toContainText('Last loaded data');
  const pageData = await (await request.get('/api/targets')).json();
  const created = pageData.items.filter(item => item.name === 'Write before reload failure');
  try {
    expect(created).toHaveLength(1);
    await page.unroute('**/api/targets?*');
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await expect(card(page, created[0].name)).toBeVisible();
  } finally { for (const item of created) await request.delete(`/api/targets/${item.id}`); }
});
