/**
 * Auth state — tokens, user, permissions, role helpers.
 * Persists to localStorage so a refresh doesn't drop the session.
 */
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export const useAuthStore = create(
  persist(
    (set, get) => ({
      accessToken: null,
      refreshToken: null,
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

      hasPermission: (resource, action, scope = 'own') => {
        const perms = get().permissions;
        // Allow matching at any broader scope: own < vessel < fleet < global
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
    }),
    {
      name: 'avs-auth',
      storage: createJSONStorage(() => localStorage),
    }
  )
);
