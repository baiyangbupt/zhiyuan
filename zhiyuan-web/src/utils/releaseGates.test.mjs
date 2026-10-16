import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import semver from 'semver';
import config from '../../next.config.mjs';

const manifest = JSON.parse(readFileSync(new URL('../../package.json', import.meta.url), 'utf8'));
const lock = JSON.parse(readFileSync(new URL('../../package-lock.json', import.meta.url), 'utf8'));
const yarn = readFileSync(new URL('../../yarn.lock', import.meta.url), 'utf8');

test('webpack source lock satisfies webpack and is shared by npm and yarn', () => {
  const sources = lock.packages['node_modules/webpack-sources'];
  const webpack = lock.packages['node_modules/webpack'];
  assert.ok(semver.satisfies(sources.version, webpack.dependencies['webpack-sources']));
  const yarnSources = yarn.match(/^webpack-sources@[^\n]+:\n  version "([^"]+)"\n  resolved "([^"]+)"\n  integrity ([^\n]+)/m);
  assert.ok(yarnSources);
  assert.equal(yarnSources[1], sources.version);
  assert.equal(yarnSources[3], sources.integrity);
});

test('type checks are an executable build gate rather than an ignored warning', () => {
  assert.notEqual(config.typescript?.ignoreBuildErrors, true);
  assert.equal(manifest.scripts.typecheck, 'tsc --noEmit --incremental false');
  assert.ok(manifest.scripts['test:unit']);
});
