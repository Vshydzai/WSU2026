// Public API client. No AWS credentials, automatic write retries or proxying.
export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export function normalizeEndpoint(value) {
  let url;
  try { url = new URL(value.trim()); } catch { throw new ApiError('Enter a complete API URL, including https://.'); }
  const loopback = ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname);
  if ((url.protocol !== 'https:' && !(url.protocol === 'http:' && loopback)) ||
      url.username || url.password || url.search || url.hash) {
    throw new ApiError('Use an HTTPS API URL without credentials, query parameters or a fragment. HTTP is allowed only on loopback.');
  }
  return url.href.replace(/\/+$/, '');
}

export function safeTargetUrl(value) {
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

export function validateItem(item) {
  if (!item || typeof item !== 'object' || typeof item.id !== 'string' || !/^[A-Za-z0-9_-]{1,64}$/.test(item.id) ||
      typeof item.name !== 'string' || !item.name.trim() || typeof item.url !== 'string' ||
      !safeTargetUrl(item.url) || typeof item.enabled !== 'boolean' ||
      typeof item.created_at !== 'string' || !Number.isFinite(Date.parse(item.created_at)) ||
      typeof item.updated_at !== 'string' || !Number.isFinite(Date.parse(item.updated_at))) {
    throw new ApiError('The API returned an invalid target. Check that this is the WebHealth API.');
  }
  return item;
}

export class ApiClient {
  constructor(endpoint, { fetchImpl = globalThis.fetch.bind(globalThis), timeoutMs = 20000, onRequest = () => {} } = {}) {
    this.endpoint = normalizeEndpoint(endpoint);
    this.fetchImpl = fetchImpl;
    this.timeoutMs = timeoutMs;
    this.onRequest = onRequest;
  }

  async request(method, path, { payload, expected = 200 } = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    const started = performance.now();
    let status = 0;
    try {
      const options = { method, credentials: 'omit', redirect: 'error', signal: controller.signal,
        headers: { Accept: 'application/json' } };
      if (payload !== undefined) {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(payload);
      }
      const response = await this.fetchImpl(this.endpoint + path, options);
      status = response.status;
      const raw = await response.text();
      let data;
      try { data = raw ? JSON.parse(raw) : null; } catch {
        if (response.ok) throw new ApiError('The API returned invalid JSON.', status);
      }
      if (!response.ok) {
        const descriptions = {
          400: 'The API rejected this request.', 404: 'This target no longer exists. Refresh the list.',
          429: 'The API is busy. Wait a moment, then refresh before retrying.',
          500: 'The API encountered an error. Refresh before retrying a write.',
          503: 'Storage is temporarily unavailable. Refresh before retrying a write.',
        };
        const detail = typeof data?.error === 'string' ? ` ${data.error}` : '';
        throw new ApiError((descriptions[status] || `API request failed (HTTP ${status}).`) + detail, status);
      }
      if (status !== expected) throw new ApiError(`Unexpected API status: ${status}.`, status);
      return data;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (controller.signal.aborted) {
        throw new ApiError('The request timed out. A write may have completed; refresh before retrying.');
      }
      throw new ApiError('Cannot reach the API. Check the endpoint, connection and deployed CORS settings. Refresh before retrying a write.');
    } finally {
      clearTimeout(timeout);
      this.onRequest({ method, status, durationMs: Math.round(performance.now() - started) });
    }
  }

  async list({ limit = 25, cursor = null } = {}) {
    if (!Number.isInteger(limit) || limit < 1 || limit > 100) throw new ApiError('Page size must be between 1 and 100.');
    const query = new URLSearchParams({ limit: String(limit) });
    if (cursor !== null) query.set('cursor', cursor);
    const data = await this.request('GET', `/targets?${query}`);
    if (!data || !Array.isArray(data.items) || (data.next_cursor !== null && typeof data.next_cursor !== 'string')) {
      throw new ApiError('The API returned an invalid target list.');
    }
    return { items: data.items.map(validateItem), next_cursor: data.next_cursor };
  }

  path(id) {
    if (typeof id !== 'string' || !/^[A-Za-z0-9_-]{1,64}$/.test(id)) throw new ApiError('Invalid target ID.');
    return `/targets/${encodeURIComponent(id)}`;
  }

  async get(id) { return validateItem(await this.request('GET', this.path(id))); }
  async create(payload) { return validateItem(await this.request('POST', '/targets', { payload, expected: 201 })); }
  async update(id, payload) { return validateItem(await this.request('PUT', this.path(id), { payload })); }
  async delete(id) { await this.request('DELETE', this.path(id), { expected: 204 }); }
}
