/**
 * Theme store — light / dark / system, with persistence.
 */
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

const apply = (theme) => {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  const resolved =
    theme === 'system'
      ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : theme;
  root.classList.toggle('dark', resolved === 'dark');
  root.style.colorScheme = resolved;
};

export const useThemeStore = create(
  persist(
    (set, get) => ({
      theme: 'light',
      setTheme: (t) => {
        apply(t);
        set({ theme: t });
      },
      init: () => apply(get().theme),
    }),
    {
      name: 'avs-theme',
      storage: createJSONStorage(() => localStorage),
    }
  )
);
