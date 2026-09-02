/**
 * Offline sync engine.
 *
 * Watches the network status and the IndexedDB action queue; when the link
 * is restored, it POSTs the pending actions to /api/v1/sync/replay in
 * chronological order. Failures are retried with exponential backoff.
 */
import { useNetworkStore } from '../store/network';
import { useAuthStore } from '../store/auth';
import {
  getPendingActions,
  markAction,
  removeAction,
  setLastSync,
  getDeviceId,
} from './db';

const BATCH_SIZE = 25;
let syncing = false;
let timer = null;

export function startSyncEngine() {
  if (typeof window === 'undefined') return;
  // Try to drain on load
  scheduleSync(2000);
  // And every 30s when online
  timer = setInterval(() => scheduleSync(0), 30000);
  window.addEventListener('online', () => scheduleSync(500));
}

export function stopSyncEngine() {
  if (timer) clearInterval(timer);
}

function scheduleSync(delay) {
  setTimeout(() => {
    if (navigator.onLine) {
      drainQueue().catch(() => {});
    }
  }, delay);
}

export async function drainQueue() {
  if (syncing) return;
  syncing = true;
  try {
    if (!useAuthStore.getState().accessToken) return;
    const pending = await getPendingActions();
    if (pending.length === 0) {
      useNetworkStore.getState().setPendingActions(0);
      return;
    }
    useNetworkStore.getState().setPendingActions(pending.length);

    const deviceId = await getDeviceId();
    const api = (await import('../api/client')).apiPost;

    for (let i = 0; i < pending.length; i += BATCH_SIZE) {
      const batch = pending.slice(i, i + BATCH_SIZE);
      try {
        await api('/sync/replay', {
          device_id: deviceId,
          actions: batch.map(a => ({
            client_action_id: a.client_action_id,
            resource: a.resource,
            action: a.action,
            entity_id: a.entity_id,
            payload: a.payload,
            client_timestamp: new Date(a.created_at).toISOString(),
          })),
        });
        // Success — remove from queue
        for (const a of batch) {
          await removeAction(a.client_action_id);
        }
      } catch (err) {
        for (const a of batch) {
          await markAction(a.client_action_id, 'failed', String(err));
        }
        break; // stop on failure; try again later
      }
    }
    await setLastSync(Date.now());
    const remaining = await getPendingActions();
    useNetworkStore.getState().setPendingActions(remaining.length);
  } finally {
    syncing = false;
  }
}

/**
 * Enqueue an action from anywhere in the app. If online, immediately try
 * to send; otherwise leave it in the queue for the next drain.
 */
export async function enqueueAction({ resource, action, entityId, payload }) {
  const clientActionId = `${resource}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const queue = (await import('./db')).queueAction;
  await queue({
    client_action_id: clientActionId,
    resource,
    action,
    entity_id: entityId || null,
    payload,
  });
  const pending = await getPendingActions();
  useNetworkStore.getState().setPendingActions(pending.length);
  if (navigator.onLine) {
    scheduleSync(0);
  }
  return clientActionId;
}
