import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('./tool.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, esModuleInterop: true },
}).outputText;

function loadTool(storage = {}, browser = true) {
  const exports = {};
  const context = {
    exports,
    require(name) {
      if (name === 'js-cookie') return { get: () => '' };
      if (name === '@/constants/constants') return { EXPERT_DETAIL: {} };
      throw new Error(`Unexpected dependency: ${name}`);
    },
    ...(browser ? { window: {}, localStorage: { getItem: key => storage[key] ?? null } } : {}),
  };
  vm.runInNewContext(compiled, context);
  return exports;
}

test('stored login credential remains a string', () => {
  assert.equal(loadTool({ ytell_token: '"login-credential"' }).getYuzhiToken(), 'login-credential');
  assert.equal(loadTool({ ytell_token: 'legacy-raw-token' }).getYuzhiToken(), 'legacy-raw-token');
});

test('missing or malformed login credentials never become HTTP header objects', () => {
  for (const value of [null, 'null', '{}', '[]', '123', 'true']) {
    assert.equal(loadTool({ ytell_token: value }).getYuzhiToken(), '');
  }
  assert.equal(loadTool({}, false).getYuzhiToken(), '');
});

test('saas credentials are read from the existing prefixed storage key', () => {
  const tool = loadTool({ ytell_b_saasInfo_pc: JSON.stringify({ uToken: 'saas-token', institutionId: 42 }) });
  assert.equal(tool.getSaasInfo().uToken, 'saas-token');
  assert.equal(tool.getSaasInfo().institutionId, '42');
});

test('malformed saas storage safely produces empty header values', () => {
  for (const value of [null, 'null', '{}', '[]', 'true', '"text"', '{"uToken":{},"institutionId":[]}']) {
    const info = loadTool({ ytell_b_saasInfo_pc: value }).getSaasInfo();
    assert.equal(info.uToken, '');
    assert.equal(info.institutionId, '');
  }
  assert.equal(loadTool({}, false).getSaasInfo().uToken, '');
});
