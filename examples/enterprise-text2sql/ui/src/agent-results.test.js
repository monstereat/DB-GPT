import assert from 'node:assert/strict';
import test from 'node:test';
import {
  agentCategoryIndex,
  buildAgentChartData,
  filterAgentResultRows,
} from './agent-results.js';

test('maps grouped SQL rows to chart labels and numeric series', () => {
  assert.deepEqual(
    buildAgentChartData({
      columns: ['region', 'sales', 'refund_rate'],
      rows: [
        ['华南', '123.45', 2.5],
        ['华东', '98.00', 1.8],
      ],
    }),
    {
      labels: ['华南', '华东'],
      series: [
        { name: 'sales', data: [123.45, 98] },
        { name: 'refund_rate', data: [2.5, 1.8] },
      ],
    },
  );
});

test('maps a single-row aggregate to metric labels', () => {
  assert.deepEqual(
    buildAgentChartData({ columns: ['sales', 'refunds'], rows: [[100, 10]] }),
    {
      labels: ['sales', 'refunds'],
      series: [{ name: '查询结果', data: [100, 10] }],
    },
  );
});

test('ignores malformed and nonnumeric SQL results', () => {
  assert.equal(buildAgentChartData({ columns: ['region'], rows: [['华南']] }), null);
  assert.equal(buildAgentChartData({ columns: ['region', 'sales'], rows: [['华南']] }), null);
  assert.equal(buildAgentChartData(null), null);
});

test('filters the existing structured result rows by the chart category', () => {
  const result = {
    columns: ['region', 'sales', 'refund_rate'],
    rows: [
      ['华南', 123, 2.5],
      ['华东', 98, 1.8],
    ],
  };
  assert.equal(agentCategoryIndex(result), 0);
  assert.deepEqual(filterAgentResultRows(result, '华南'), [['华南', 123, 2.5]]);
  assert.deepEqual(filterAgentResultRows(result), result.rows);
  assert.equal(agentCategoryIndex({ columns: ['sales'], rows: [[123]] }), -1);
});
