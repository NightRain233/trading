// @ts-check
/**
 * Tiny stale-while-revalidate cache for page data. Switching tabs remounts a
 * page; with this it shows the last result at once and refreshes in the
 * background. Concurrent callers share one in-flight request.
 */

/** @type {Map<string, { value?: unknown; at: number; inflight?: Promise<unknown> }>} */
const store = new Map();

/**
 * Last value for a key, however old; undefined when never loaded.
 * @template T
 * @param {string} key
 * @returns {T | undefined}
 */
export function peek(key) {
  return /** @type {T | undefined} */ (store.get(key)?.value);
}

/**
 * Cached value if younger than maxAgeMs, otherwise one shared fresh load.
 * @template T
 * @param {string} key
 * @param {() => Promise<T>} loader
 * @param {number} [maxAgeMs]
 * @returns {Promise<T>}
 */
export function cached(key, loader, maxAgeMs = 60_000) {
  const entry = store.get(key);
  if (entry && entry.value !== undefined && Date.now() - entry.at < maxAgeMs) {
    return Promise.resolve(/** @type {T} */ (entry.value));
  }
  if (entry?.inflight) return /** @type {Promise<T>} */ (entry.inflight);
  const inflight = loader().then(
    value => { store.set(key, { value, at: Date.now() }); return value; },
    error => {
      const prev = store.get(key);
      store.set(key, { value: prev?.value, at: prev?.at ?? 0 });
      throw error;
    },
  );
  store.set(key, { value: entry?.value, at: entry?.at ?? 0, inflight });
  return inflight;
}

/**
 * Drop every key starting with the prefix (after a manual refresh).
 * @param {string} prefix
 */
export function invalidate(prefix) {
  for (const key of [...store.keys()]) if (key.startsWith(prefix)) store.delete(key);
}
