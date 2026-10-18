import test from 'node:test';
import assert from 'node:assert/strict';
import { cached, invalidate, peek } from '../src/swrCache.js';

test('cached shares one in-flight load and serves fresh values', async () => {
  let calls = 0;
  const loader = () => new Promise(resolve => setTimeout(() => resolve(++calls), 5));
  const [a, b] = await Promise.all([cached('k1', loader), cached('k1', loader)]);
  assert.equal(a, 1);
  assert.equal(b, 1);
  assert.equal(await cached('k1', loader), 1);
  assert.equal(calls, 1);
  assert.equal(peek('k1'), 1);
});

test('stale values reload and invalidate clears by prefix', async () => {
  let calls = 0;
  const loader = async () => ++calls;
  await cached('p:a', loader);
  assert.equal(await cached('p:a', loader, 0), 2);
  invalidate('p:');
  assert.equal(peek('p:a'), undefined);
});

test('a failed load keeps the previous value', async () => {
  await cached('k2', async () => 'old');
  await assert.rejects(cached('k2', async () => { throw new Error('down'); }, 0));
  assert.equal(peek('k2'), 'old');
});
