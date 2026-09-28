import assert from 'node:assert/strict';
import test from 'node:test';
import { buildComparisonRows, shiftDateByYear } from './analytics.js';

test('aligns current and previous year metrics by month of year', () => {
  const current = {
    result: {
      columns: ['period', 'sales_cents'],
      rows: [
        ['2026-04', 10000],
        ['2026-05', 32000],
        ['2026-06', 35000],
      ],
    },
  };
  const previous = {
    result: {
      columns: ['period', 'sales_cents'],
      rows: [['2025-04', 8000]],
    },
  };

  assert.deepEqual(
    buildComparisonRows(current, previous, 'sales_cents', 'month'),
    [
      {
        key: '2026-04',
        label: '04月',
        value: 10000,
        previousValue: 8000,
      },
      {
        key: '2026-05',
        label: '05月',
        value: 32000,
        previousValue: null,
      },
      {
        key: '2026-06',
        label: '06月',
        value: 35000,
        previousValue: null,
      },
    ],
  );
});

test('shifts leap-day boundaries to the last valid day in the target month', () => {
  assert.equal(shiftDateByYear('2024-02-29', -1), '2023-02-28');
  assert.equal(shiftDateByYear('2025-04-01', -1), '2024-04-01');
});
