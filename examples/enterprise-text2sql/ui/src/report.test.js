import assert from 'node:assert/strict';
import test from 'node:test';
import { buildPrintableReportHtml } from './report.js';

test('builds a printable report with metric version and scope messaging', () => {
  const html = buildPrintableReportHtml({
    generatedAt: '2026-09-25T10:00:00.000Z',
    startDate: '2026-04-01',
    endDate: '2026-07-01',
    summaries: [
      { name: '退款额', value: '¥ 20.00', version: '2.0.0', definition: '订单 cohort' },
    ],
    metricName: '退款额',
    metricVersion: '2.0.0',
    definition: '按原订单日期统计',
    dimensionName: '区域',
    rows: [['广州', '¥ 20.00']],
    sql: 'SELECT amount FROM refunds',
  });

  assert.match(html, /打印 \/ 保存为 PDF/);
  assert.match(html, /OIDC 身份和数据范围授权/);
  assert.match(html, /2\.0\.0/);
  assert.match(html, /SELECT amount FROM refunds/);
});

test('escapes API values before inserting them into printable HTML', () => {
  const html = buildPrintableReportHtml({
    generatedAt: '',
    startDate: '',
    endDate: '',
    summaries: [],
    metricName: '<img src=x onerror=alert(1)>',
    metricVersion: '1.0.0',
    definition: '<script>alert(1)</script>',
    dimensionName: '区域',
    rows: [['<svg onload=alert(1)>', '&']],
    sql: 'SELECT "unsafe"',
  });

  assert.doesNotMatch(html, /<img src=x|<script>|<svg onload/);
  assert.match(html, /&lt;script&gt;/);
});
