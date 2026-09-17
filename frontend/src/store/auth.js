/**
 * Auth state — tokens, user, permissions, role helpers.
 * Cookie-based (supervisor instruction 2026-09-17): no localStorage persistence;
 * session lives in HttpOnly cookie set by backend /auth/login.
 */
import { create } from 'zustand';

function readCookie(name) {
  const match = document.cookie.split(';').find((c) => c.trim().startsWith(name + '='));
  return match ? decodeURIComponent(match.split('=')[1]) : null;
}

export const useAuthStore = create(
  (set, get) => ({
    accessToken: readCookie('access_token') || null,
    refreshToken: readCookie('refresh_token') || null,
    user: null,
    roles: [],
    permissions: [],
    vesselId: null,

    setUser: (u) => set({
      user: u,
      roles: u?.roles || [],
      permissions: u?.permissions || [],
      vesselId: u?.vessel_id || null,
    }),

    setTokens: ({ accessToken, refreshToken }) => set({
      accessToken,
      refreshToken: refreshToken ?? get().refreshToken,
    }),

    restoreFromCookie: async () => {
      const token = get().accessToken;
      if (!token) return;
      try {
        const userData = await import('../api/client').then(m => m.apiGet('/auth/me'));
        get().setUser(userData);
      } catch {
        // token invalid — leave user null; next protected call will try refresh
      }
    },

    hasPermission: (resource, action, scope = 'own') => {
      const perms = get().permissions;
      const order = ['own', 'vessel', 'fleet', 'global'];
      const target = order.indexOf(scope);
      for (const s of order.slice(target)) {
        if (perms.includes(`${resource}:${action}:${s}`)) return true;
      }
      return false;
    },

    hasRole: (...names) => names.some(n => get().roles.includes(n)),

    clear: () => set({
      accessToken: null,
      refreshToken: null,
      user: null,
      roles: [],
      permissions: [],
      vesselId: null,
    }),
  })
);
