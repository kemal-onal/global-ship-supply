/**
 * Centralized API client.
 *
 * Talks to the FastAPI backend (proxied through Vite at /api/v1).
 * Automatically attaches the JWT access token and refreshes on 401.
 */
import { useAuthStore } from '../store/auth';

const BASE = '/api/v1';

let refreshPromise = null;

async function refreshAccessToken() {
  if (refreshPromise) return refreshPromise;
  const { refreshToken, setTokens, clear } = useAuthStore.getState();
  if (!refreshToken) {
    clear();
    throw new Error('No refresh token');
  }
  refreshPromise = (async () => {
    try {
      const r = await fetch(`${BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!r.ok) {
        clear();
        throw new Error('Refresh failed');
      }
      const data = await r.json();
      setTokens({ accessToken: data.access_token, refreshToken: data.refresh_token });
      return data.access_token;
    } finally {
      refreshPromise = null;
    }
  })();
  return refreshPromise;
}

export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.status = status;
    this.payload = payload;
  }
}

export async function api(path, { method = 'GET', body, query, headers = {}, signal } = {}) {
  const url = new URL(`${BASE}${path}`, window.location.origin);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== '') {
        url.searchParams.set(k, v);
      }
    }
  }

  const doFetch = async (token) => {
    const h = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...headers,
    };
    if (token) h['Authorization'] = `Bearer ${token}`;
    return fetch(url.pathname + url.search, {
      method,
      headers: h,
      body: body ? JSON.stringify(body) : undefined,
      signal,
    });
  };

  let token = useAuthStore.getState().accessToken;
  let response = await doFetch(token);

  // 401 -> try refresh once
  if (response.status === 401 && !path.endsWith('/auth/refresh') && !path.endsWith('/auth/login')) {
    try {
      token = await refreshAccessToken();
      response = await doFetch(token);
    } catch {
      // refresh failed
    }
  }

  const contentType = response.headers.get('content-type') || '';
  let payload = null;
  if (contentType.includes('application/json')) {
    payload = await response.json();
  } else {
    payload = await response.text();
  }

  if (!response.ok) {
    const message = (payload && payload.detail) || response.statusText;
    throw new ApiError(typeof message === 'string' ? message : 'Request failed', response.status, payload);
  }
  return payload;
}

export const apiGet = (path, opts) => api(path, { ...opts, method: 'GET' });
export const apiPost = (path, body, opts) => api(path, { ...opts, method: 'POST', body });
export const apiPatch = (path, body, opts) => api(path, { ...opts, method: 'PATCH', body });
export const apiDelete = (path, opts) => api(path, { ...opts, method: 'DELETE' });
