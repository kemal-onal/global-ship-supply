/**
 * IndexedDB layer for offline-first ordering.
 *
 * On a ship at sea, the VSAT connection drops. Crew must still be able to
 * browse the catalog (cached), build a cart, and submit orders. The orders
 * are queued here and replayed to the backend when connectivity returns.
 *
 * Schema:
 *   catalog_cache     — product rows the user has recently viewed
 *   carts             — local carts (in-progress orders)
 *   order_queue       — pending actions (create_order, update_order, etc.)
 *   sync_meta         — last sync time, cursor, device id
 */
import { openDB } from 'idb';

const DB_NAME = 'avs-offline';
const DB_VERSION = 1;

let _dbPromise = null;
export function getDB() {
  if (!_dbPromise) {
    _dbPromise = openDB(DB_NAME, DB_VERSION, {
      upgrade(db) {
        if (!db.objectStoreNames.contains('catalog_cache')) {
          const store = db.createObjectStore('catalog_cache', { keyPath: 'id' });
          store.createIndex('category', 'category_id');
          store.createIndex('sku', 'sku', { unique: false });
        }
        if (!db.objectStoreNames.contains('carts')) {
          db.createObjectStore('carts', { keyPath: 'id' });
        }
        if (!db.objectStoreNames.contains('order_queue')) {
          const s = db.createObjectStore('order_queue', { keyPath: 'client_action_id' });
          s.createIndex('created_at', 'created_at');
          s.createIndex('status', 'status');
        }
        if (!db.objectStoreNames.contains('sync_meta')) {
          db.createObjectStore('sync_meta', { keyPath: 'key' });
        }
      },
    });
  }
  return _dbPromise;
}

export async function cacheProducts(products) {
  const db = await getDB();
  const tx = db.transaction('catalog_cache', 'readwrite');
  for (const p of products) {
    await tx.store.put({ ...p, _cached_at: Date.now() });
  }
  await tx.done;
}

export async function getCachedProducts({ q, categoryId, limit = 50, offset = 0 } = {}) {
  const db = await getDB();
  const all = await db.getAll('catalog_cache');
  let filtered = all;
  if (q) {
    const needle = q.toLowerCase();
    filtered = filtered.filter(
      p =>
        p.name?.toLowerCase().includes(needle) ||
        p.sku?.toLowerCase().includes(needle) ||
        p.manufacturer?.toLowerCase().includes(needle)
    );
  }
  if (categoryId) {
    filtered = filtered.filter(p => p.category_id === categoryId);
  }
  return {
    items: filtered.slice(offset, offset + limit),
    total: filtered.length,
    offline: true,
  };
}

export async function queueAction(action) {
  const db = await getDB();
  await db.put('order_queue', {
    ...action,
    status: 'pending',
    created_at: Date.now(),
  });
}

export async function getPendingActions() {
  const db = await getDB();
  return db.getAllFromIndex('order_queue', 'created_at');
}

export async function markAction(actionId, status, error = null) {
  const db = await getDB();
  const existing = await db.get('order_queue', actionId);
  if (existing) {
    existing.status = status;
    existing.error = error;
    existing.attempted_at = Date.now();
    await db.put('order_queue', existing);
  }
}

export async function removeAction(actionId) {
  const db = await getDB();
  await db.delete('order_queue', actionId);
}

export async function clearAllOfflineData() {
  const db = await getDB();
  await Promise.all([
    db.clear('catalog_cache'),
    db.clear('carts'),
    db.clear('order_queue'),
  ]);
}

export async function getDeviceId() {
  const db = await getDB();
  const meta = await db.get('sync_meta', 'device_id');
  if (meta) return meta.value;
  const value = `web-${crypto.randomUUID()}`;
  await db.put('sync_meta', { key: 'device_id', value });
  return value;
}

export async function setLastSync(timestamp) {
  const db = await getDB();
  await db.put('sync_meta', { key: 'last_sync', value: timestamp });
}
