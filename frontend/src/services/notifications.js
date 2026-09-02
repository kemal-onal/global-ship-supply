/**
 * Notifications API — thin wrapper around the centralised client.
 *
 * The backend endpoints:
 *   GET    /notifications?limit&offset&unread_only  -> Notification[]
 *   GET    /notifications/unread-count             -> { count: number }
 *   PATCH  /notifications/{id}/read                -> Notification
 *   PATCH  /notifications/read-all                 -> { updated: number }
 */
import { apiGet, apiPatch } from '../api/client'

export function listNotifications({ limit = 50, offset = 0, unreadOnly = false } = {}) {
  return apiGet('/notifications', {
    query: { limit, offset, unread_only: unreadOnly },
  })
}

export function getUnreadCount() {
  return apiGet('/notifications/unread-count')
}

export function markRead(id) {
  return apiPatch(`/notifications/${id}/read`)
}

export function markAllRead() {
  return apiPatch('/notifications/read-all')
}
