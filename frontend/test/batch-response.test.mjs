import test from 'node:test';
import assert from 'node:assert/strict';

import { normalizeBatchSnapshot, parseBatchHeaders, parseBatchResponse } from '../src/batchResponse.js';

function makeHeaders(values = {}) {
  return {
    get(name) {
      return Object.prototype.hasOwnProperty.call(values, name) ? values[name] : null;
    },
  };
}

test('parseBatchHeaders keeps updatedAt and stale metadata', () => {
  const meta = parseBatchHeaders(
    makeHeaders({
      ETag: '"abc"',
      'X-Data-Updated-At': '2026-03-11T00:00:00+00:00',
      'X-Data-Stale': '1',
      'X-Refresh-Triggered': '1',
    }),
  );

  assert.deepEqual(meta, {
    etag: '"abc"',
    updatedAt: '2026-03-11T00:00:00+00:00',
    stale: true,
    refreshTriggered: true,
  });
});

test('parseBatchResponse returns payload with metadata', async () => {
  const response = {
    ok: true,
    headers: makeHeaders({
      'X-Data-Updated-At': '2026-03-11T00:00:00+00:00',
      'X-Data-Stale': '0',
      'X-Refresh-Triggered': '0',
      ETag: '"def"',
    }),
    async json() {
      return { TEST: { price: 1.67 } };
    },
  };

  const result = await parseBatchResponse(response);

  assert.equal(result.updatedAt, '2026-03-11T00:00:00+00:00');
  assert.equal(result.stale, false);
  assert.equal(result.refreshTriggered, false);
  assert.deepEqual(result.data, { TEST: { price: 1.67 } });
});

test('normalizeBatchSnapshot keeps metadata from prefetched payload', () => {
  const snapshot = normalizeBatchSnapshot({
    data: { TEST: { price: 1.67 } },
    updatedAt: '2026-03-11T00:00:00+00:00',
    stale: true,
    refreshTriggered: true,
    etag: '"etag"',
  });

  assert.deepEqual(snapshot, {
    data: { TEST: { price: 1.67 } },
    updatedAt: '2026-03-11T00:00:00+00:00',
    stale: true,
    refreshTriggered: true,
    etag: '"etag"',
  });
});
