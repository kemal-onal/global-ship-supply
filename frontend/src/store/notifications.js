/**
 * Notifications state — items, unread count, panel open/close.
 *
 * Not persisted: we want the count to always reflect the DB, not a
 * stale localStorage value from a previous session.
 */
import { create } from 'zustand'
import {
  getUnreadCount,
  listNotifications,
  markAllRead as apiMarkAllRead,
  markRead as apiMarkRead,
} from '../services/notifications'

export const useNotificationsStore = create((set, get) => ({
  items: [],
  unreadCount: 0,
  loading: false,
  panelOpen: false,
  lastFetched: null,

  openPanel: () => {
    set({ panelOpen: true })
    // Fire-and-forget; UI shows a spinner via `loading`.
    get().fetchList()
  },
  closePanel: () => set({ panelOpen: false }),
  togglePanel: () => {
    const next = !get().panelOpen
    set({ panelOpen: next })
    if (next) get().fetchList()
  },

  fetchList: async () => {
    set({ loading: true })
    try {
      const items = await listNotifications({ limit: 50 })
      set({ items, loading: false, lastFetched: Date.now() })
    } catch (err) {
      set({ loading: false })
      // Surfacing the error to the console is enough; the UI just
      // shows the empty state.
      console.error('[notifications] fetchList failed', err)
    }
  },

  refreshUnreadCount: async () => {
    try {
      const { count } = await getUnreadCount()
      set({ unreadCount: count })
    } catch (err) {
      // Don't spam the console on every poll — just log once.
      console.error('[notifications] refreshUnreadCount failed', err)
    }
  },

  markRead: async (id) => {
    // Optimistic update: flip local read state, decrement badge.
    set(state => {
      const items = state.items.map(n =>
        n.id === id && !n.read_at
          ? { ...n, read_at: new Date().toISOString() }
          : n
      )
      const wasUnread = state.items.find(n => n.id === id && !n.read_at)
      return {
        items,
        unreadCount: wasUnread ? Math.max(0, state.unreadCount - 1) : state.unreadCount,
      }
    })
    try {
      await apiMarkRead(id)
    } catch (err) {
      console.error('[notifications] markRead failed', err)
      // Re-sync from the server so we don't lie about the count.
      get().refreshUnreadCount()
    }
  },

  markAllRead: async () => {
    // Optimistic: clear all unread locally.
    set(state => {
      const now = new Date().toISOString()
      return {
        items: state.items.map(n => (n.read_at ? n : { ...n, read_at: now })),
        unreadCount: 0,
      }
    })
    try {
      await apiMarkAllRead()
    } catch (err) {
      console.error('[notifications] markAllRead failed', err)
      get().refreshUnreadCount()
    }
  },
}))
