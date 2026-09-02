/**
 * Online / Offline state and queue state — drives the offline indicator
 * and the sync engine. Persisted via the offline IndexedDB layer.
 */
import { create } from 'zustand';

export const useNetworkStore = create((set) => ({
  online: typeof navigator !== 'undefined' ? navigator.onLine : true,
  vsat: 'good', // good | fair | poor | unknown
  pendingActions: 0,
  setOnline: (online) => set({ online }),
  setVsat: (vsat) => set({ vsat }),
  setPendingActions: (n) => set({ pendingActions: n }),

  init: () => {
    if (typeof window === 'undefined') return;
    window.addEventListener('online', () => useNetworkStore.getState().setOnline(true));
    window.addEventListener('offline', () => useNetworkStore.getState().setOnline(false));
    // RTT-based VSAT quality hint: poor RTT -> poor connection
    let lastBeat = performance.now();
    setInterval(() => {
      const now = performance.now();
      const drift = now - lastBeat - 5000;
      const quality = drift > 3000 ? 'poor' : drift > 1000 ? 'fair' : 'good';
      lastBeat = now;
      const { online, setVsat } = useNetworkStore.getState();
      setVsat(online ? quality : 'offline');
    }, 5000);
  },
}));
