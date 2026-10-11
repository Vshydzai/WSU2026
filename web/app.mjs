import { ApiClient, normalizeEndpoint, safeTargetUrl } from './api-client.mjs';
import { connectionMode, filterItems, PageHistory } from './view-model.mjs';

const $ = id => document.getElementById(id);
const state = { client: null, config: {}, items: [], next: null, busy: false, loaded: false,
  stale: false, editing: null, deleting: null, history: new PageHistory() };

function message(id, text = '') {
  $(id).textContent = text;
  $(id).hidden = !text;
}

function controls() {
  $('connect-button').disabled = state.busy;
  $('endpoint').disabled = state.busy;
  $('target-fields').disabled = state.busy || !state.loaded;
  $('cancel-edit').disabled = state.busy;
  $('refresh').disabled = state.busy || !state.client;
  $('search').disabled = !state.loaded;
  $('enabled-filter').disabled = !state.loaded;
  $('previous').disabled = state.busy || !state.loaded || !state.history.hasPrevious;
  $('next').disabled = state.busy || !state.loaded || !state.next;
  $('confirm-delete').disabled = state.busy;
  $('target-list').setAttribute('aria-busy', String(state.busy));
  for (const button of document.querySelectorAll('.card-actions button')) button.disabled = state.busy;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function action(label, target, handler, className = '') {
  const button = element('button', `secondary ${className}`, label);
  button.type = 'button';
  button.setAttribute('aria-label', `${label}: ${target.name}`);
  button.disabled = state.busy;
  button.addEventListener('click', handler);
  return button;
}

function render() {
  const visible = filterItems(state.items, $('search').value, $('enabled-filter').value);
  $('target-list').replaceChildren();
  for (const item of visible) {
    const card = element('article', 'target-card');
    card.dataset.targetId = item.id;
    const header = element('header', '');
    const copy = element('div', '');
    copy.append(element('h3', '', item.name));
    const link = element('a', '', item.url);
    // API data is always inserted as text. Only validated HTTP(S) links become clickable.
    const href = safeTargetUrl(item.url);
    if (href) { link.href = href; link.target = '_blank'; link.rel = 'noopener noreferrer'; }
    copy.append(link);
    header.append(copy, element('span', `target-state${item.enabled ? '' : ' disabled'}`, item.enabled ? 'Enabled' : 'Disabled'));
    card.append(header, element('span', 'target-meta', `Updated ${new Date(item.updated_at).toLocaleString()} · ID ${item.id}`));
    const actions = element('div', 'card-actions');
    actions.append(
      action('Edit', item, () => edit(item)),
      action(item.enabled ? 'Disable' : 'Enable', item, () => mutate(async () => {
        // Fetch the latest fields before a full-replacement PUT; do not silently reuse a stale page.
        const latest = await state.client.get(item.id);
        await state.client.update(item.id, { name: latest.name, url: latest.url, enabled: !latest.enabled });
        return `Target ${latest.enabled ? 'disabled' : 'enabled'}.`;
      })),
      action('Delete', item, () => {
        state.deleting = item;
        $('delete-description').textContent = `${item.name} — ${item.url}`;
        $('delete-dialog').showModal();
      }, 'delete-button'));
    card.append(actions);
    $('target-list').append(card);
  }
  $('total-count').textContent = state.loaded ? String(state.items.length) : '—';
  $('enabled-count').textContent = state.loaded ? String(state.items.filter(item => item.enabled).length) : '—';
  $('page-label').textContent = `Page ${state.history.page}`;
  $('list-summary').textContent = state.loaded
    ? `${state.stale ? 'Last loaded data — refresh to confirm. ' : ''}${visible.length} of ${state.items.length} targets on this page. Filters apply to this page only.`
    : state.busy ? 'Loading targets…' : 'Connect an API to load targets.';
  $('empty-state').hidden = visible.length > 0 || state.busy;
  const emptyHeading = $('empty-state').querySelector('h3');
  const emptyCopy = $('empty-state').querySelector('p');
  emptyHeading.textContent = state.loaded ? (state.items.length ? 'No matches on this page' : 'Your queue is empty') : 'Your next crawl starts here';
  emptyCopy.textContent = state.loaded ? (state.items.length ? 'Adjust the filters, or check the next page.' : 'Add a public website using the target form.') : 'Connect an API, then add a public website to the target list.';
  controls();
}

async function run(task) {
  if (state.busy) return;
  state.busy = true;
  message('error');
  message('notice');
  render();
  try { await task(); } catch (error) {
    state.stale = state.loaded;
    message('error', error.message || 'The request failed. Refresh before trying again.');
  } finally { state.busy = false; render(); }
}

async function load() {
  const page = await state.client.list({ cursor: state.history.cursor });
  state.items = page.items;
  state.next = page.next_cursor;
  state.loaded = true;
  state.stale = false;
  $('connection-status').textContent = `Connected · ${state.client.endpoint}`;
}

function resetEditor() {
  state.editing = null;
  $('target-form').reset();
  $('editor-heading').textContent = 'New target';
  $('editor-kicker').textContent = 'ADD TO THE QUEUE';
  $('editor-description').textContent = 'The API validates and stores each target.';
  $('save-target').textContent = 'Create target ↗';
  $('cancel-edit').hidden = true;
}

async function connect(value) {
  await run(async () => {
    const endpoint = normalizeEndpoint(value);
    const mode = connectionMode(endpoint, state.config, location.origin);
    state.client = new ApiClient(endpoint, { onRequest: ({ method, status, durationMs }) => {
      $('latency').textContent = `${durationMs} ms`;
      $('request-detail').textContent = `${method} · ${status ? `HTTP ${status}` : 'No response'} · browser time`;
    } });
    $('endpoint').value = endpoint;
    $('mode-label').textContent = mode.label;
    $('mode-label').className = `mode-pill ${mode.kind}`;
    $('mode-detail').textContent = mode.detail;
    $('connection-status').textContent = `Connecting · ${endpoint}`;
    state.history.reset();
    state.items = [];
    state.next = null;
    state.loaded = false;
    state.stale = false;
    $('search').value = '';
    $('enabled-filter').value = 'all';
    resetEditor();
    try { await load(); } catch (error) {
      $('connection-status').textContent = `Connection failed · ${endpoint}`;
      throw error;
    }
    try { localStorage.setItem('webhealth.endpoint', endpoint); } catch { /* Storage is optional. */ }
    message('notice', mode.kind === 'demo' ? 'Local simulator connected. This rehearsal does not use AWS.' : 'API connected. Target changes take effect on the next scheduled crawler run.');
  });
}

async function edit(item) {
  await run(async () => {
    const latest = await state.client.get(item.id);
    state.editing = latest.id;
    $('target-name').value = latest.name;
    $('target-url').value = latest.url;
    $('target-enabled').checked = latest.enabled;
    $('editor-heading').textContent = 'Edit target';
    $('editor-kicker').textContent = 'UPDATE THE QUEUE';
    $('editor-description').textContent = `Editing target ${latest.id}`;
    $('save-target').textContent = 'Save changes ↗';
    $('cancel-edit').hidden = false;
  });
  if (state.editing) $('target-name').focus();
}

async function mutate(task) {
  await run(async () => {
    const notice = await task();
    resetEditor();
    state.history.reset();
    $('search').value = '';
    $('enabled-filter').value = 'all';
    message('notice', `${notice} Reloading page 1…`);
    await load();
    message('notice', `${notice} Page 1 refreshed.`);
  });
}

$('connection-form').addEventListener('submit', event => { event.preventDefault(); connect($('endpoint').value); });
$('refresh').addEventListener('click', () => run(load));
$('search').addEventListener('input', render);
$('enabled-filter').addEventListener('change', render);
$('cancel-edit').addEventListener('click', resetEditor);
$('target-form').addEventListener('submit', event => {
  event.preventDefault();
  const payload = { name: $('target-name').value.trim(), url: $('target-url').value.trim(), enabled: $('target-enabled').checked };
  if (!payload.name) { message('error', 'Enter a name with at least one visible character.'); $('target-name').focus(); return; }
  mutate(async () => {
    if (state.editing) { await state.client.update(state.editing, payload); return 'Target updated.'; }
    await state.client.create(payload);
    return 'Target created.';
  });
});

for (const [id, change] of [['next', () => state.history.next(state.next)], ['previous', () => state.history.previous()]]) {
  $(id).addEventListener('click', () => run(async () => {
    const oldIndex = state.history.index;
    const oldCursors = [...state.history.cursors];
    if (!change()) return;
    try { await load(); } catch (error) {
      state.history.index = oldIndex;
      state.history.cursors = oldCursors;
      throw error;
    }
  }));
}
$('cancel-delete').addEventListener('click', () => $('delete-dialog').close());
$('delete-dialog').addEventListener('close', () => { state.deleting = null; });
$('confirm-delete').addEventListener('click', () => {
  const item = state.deleting;
  if (!item) return;
  $('delete-dialog').close();
  mutate(async () => { await state.client.delete(item.id); return 'Target deleted.'; });
});

async function start() {
  render();
  try {
    const response = await fetch('/config.json', { credentials: 'omit', redirect: 'error' });
    if (!response.ok) throw new Error('Unable to read dashboard configuration. Restart the local server.');
    state.config = await response.json();
    if (state.config.api_url) {
      await connect(new URL(state.config.api_url, location.origin).href);
    } else {
      try { $('endpoint').value = localStorage.getItem('webhealth.endpoint') || ''; } catch { /* Optional. */ }
    }
  } catch (error) { message('error', error.message); }
}
start();
