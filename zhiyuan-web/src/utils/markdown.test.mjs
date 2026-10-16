import assert from 'node:assert/strict';
import test from 'node:test';
import { renderMarkdown } from './markdown.mjs';

test('message markdown removes active HTML and dangerous URL schemes', () => {
  const payloads = [
    '<img src="x" onerror="alert(1)">',
    '<svg onload="alert(1)"><a href="javascript:alert(1)">unsafe</a></svg>',
    '<script>alert(1)</script>',
    '[unsafe](javascript:alert%281%29)',
    '[unsafe](data:text/html;base64,PHNjcmlwdD4=)',
    '<a href="jav&#x61;script:alert(1)">unsafe</a>',
    '<iframe srcdoc="<script>alert(1)</script>"></iframe>',
    '<form action="https://example.com"><input autofocus onfocus="alert(1)"></form>',
    '<style>body { display: none }</style>',
  ];
  for (const payload of payloads) {
    const html = renderMarkdown(payload);
    assert.doesNotMatch(html, /<(?:script|svg|img|iframe|form|input|style)\b/i);
    assert.doesNotMatch(html, /\son\w+\s*=|(?:href|src)=["'](?:javascript|data):/i);
  }
});

test('message markdown preserves ordinary text, tables, code and safe links', () => {
  const html = renderMarkdown('**建议** [来源](https://example.com/policy)\n\n| 院校 | 档位 |\n| --- | --- |\n| 示例大学 | 冲 |\n\n`<script>`');
  assert.match(html, /<strong>建议<\/strong>/);
  assert.match(html, /href="https:\/\/example.com\/policy"/);
  assert.match(html, /<table>/);
  assert.match(html, /<td>示例大学<\/td>/);
  assert.match(html, /<code>&lt;script&gt;<\/code>/);
});

test('message markdown removes attributes outside the display allowlist', () => {
  const html = renderMarkdown('<p id="login" style="position:fixed" onclick="alert(1)">hello</p>');
  assert.equal(html.trim(), '<p>hello</p>');
});
