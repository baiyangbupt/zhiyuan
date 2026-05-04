import test from 'node:test';
import assert from 'node:assert/strict';

import { createFetchQueue } from './fetchQueue.mjs';

test('fetch queue reruns once after a concurrent refresh request arrives', async () => {
  const calls = [];
  let releaseFirst;

  const firstRunDone = new Promise(resolve => {
    releaseFirst = resolve;
  });

  const queue = createFetchQueue(async page => {
    calls.push(page ?? 'current');
    if (calls.length === 1) {
      await firstRunDone;
    }
  });

  const firstPromise = queue.enqueue();
  await Promise.resolve();
  const secondPromise = queue.enqueue();

  assert.deepEqual(calls, ['current']);

  releaseFirst();
  await firstPromise;
  await secondPromise;
  await new Promise(resolve => setTimeout(resolve, 0));

  assert.deepEqual(calls, ['current', 1]);
});

test('fetch queue keeps latest requested page while one request is in flight', async () => {
  const calls = [];
  let releaseFirst;

  const firstRunDone = new Promise(resolve => {
    releaseFirst = resolve;
  });

  const queue = createFetchQueue(async page => {
    calls.push(page ?? 'current');
    if (calls.length === 1) {
      await firstRunDone;
    }
  });

  const firstPromise = queue.enqueue(3);
  await Promise.resolve();
  void queue.enqueue(5);
  void queue.enqueue(7);

  releaseFirst();
  await firstPromise;
  await new Promise(resolve => setTimeout(resolve, 0));

  assert.deepEqual(calls, [3, 7]);
});

