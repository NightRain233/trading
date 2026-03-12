/**
 * @typedef {{ get(name: string): string | null }} HeaderReader
 */

/**
 * @param {HeaderReader} headers
 */
export function parseBatchHeaders(headers) {
  return {
    etag: headers.get('ETag'),
    updatedAt: headers.get('X-Data-Updated-At'),
    stale: headers.get('X-Data-Stale') === '1',
    refreshTriggered: headers.get('X-Refresh-Triggered') === '1',
  };
}

/**
 * @param {{
 *   data?: Record<string, unknown> | null;
 *   updatedAt?: string | null;
 *   stale?: boolean;
 *   refreshTriggered?: boolean;
 *   etag?: string | null;
 * } | null | undefined} snapshot
 */
export function normalizeBatchSnapshot(snapshot) {
  return {
    data: snapshot?.data ?? {},
    updatedAt: snapshot?.updatedAt ?? null,
    stale: snapshot?.stale ?? true,
    refreshTriggered: snapshot?.refreshTriggered ?? false,
    etag: snapshot?.etag ?? null,
  };
}

/**
 * @param {Response} response
 */
export async function parseBatchResponse(response) {
  const meta = parseBatchHeaders(response.headers);
  if (!response.ok) {
    return normalizeBatchSnapshot({
      data: null,
      ...meta,
    });
  }

  return normalizeBatchSnapshot({
    data: await response.json(),
    ...meta,
  });
}
