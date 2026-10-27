import { fetchState } from './transport.js';
import { observeProgress, resolveHealth } from './state.js';

export const POLL_INTERVAL_MS = 200;

export function createMonitor({ fetchImpl = globalThis.fetch.bind(globalThis), now = () => performance.now(), timeoutMs = 3500 } = {}) {
  let state = null;
  let observation = null;
  let error = null;
  let receivedAt = null;
  let pending = false;
  let disposed = false;
  let controller = null;
  const snapshot = () => ({ state, observation, error, receivedAt, health: resolveHealth(state, observation, now(), error) });
  return {
    snapshot,
    dispose() { disposed = true; controller?.abort(); },
    async poll() {
      if (pending || disposed) return snapshot();
      pending = true;
      controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const next = await fetchState(fetchImpl, controller.signal);
        if (!disposed) {
          observation = observeProgress(observation, next, now());
          state = next;
          error = null;
          receivedAt = new Date().toISOString();
        }
      } catch (failure) {
        if (!disposed) error = failure.name === 'AbortError' ? 'State request timed out' : failure.message || 'State endpoint unavailable';
      } finally {
        clearTimeout(timeout);
        pending = false;
      }
      return snapshot();
    },
  };
}
