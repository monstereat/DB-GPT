import { buildSqlResultView, filterSqlResultRows } from './react-sql-result';

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const result = buildSqlResultView({
  type: 'sql_result',
  columns: ['region', 'sales_cents'],
  rows: [
    ['Guangzhou', 45000],
    ['Shenzhen', 32000],
  ],
  row_count: 2,
  truncated: false,
});

assert(result, 'valid SQL result should be normalized');
assert(result.columns.length === 2, 'table columns should be preserved');
assert(result.rows[0].region === 'Guangzhou', 'row values should map to columns');
assert(result.chart?.chartType === 'bar', 'categorical metrics should use a bar chart');
assert(result.chart?.yField === 'sales_cents', 'chart should select the numeric metric');
assert(
  filterSqlResultRows(result, 'Guangzhou').length === 1 &&
    filterSqlResultRows(result, 'Guangzhou')[0].region === 'Guangzhou',
  'chart category selection should filter only the displayed result rows',
);
assert(
  filterSqlResultRows(result, null).length === 2,
  'clearing chart category selection should restore all result rows',
);

const monthly = buildSqlResultView({
  type: 'sql_result',
  columns: ['period', 'sales_cents'],
  rows: [
    ['2026-04', 100],
    ['2026-05', 150],
  ],
  row_count: 2,
  truncated: false,
});
assert(monthly?.chart?.chartType === 'line', 'time dimensions should use a line chart');

const scalar = buildSqlResultView({
  type: 'sql_result',
  columns: ['sales_cents', 'refund_rate_pct'],
  rows: [[77000, 6.1]],
  row_count: 1,
  truncated: false,
});
assert(scalar && !scalar.chart, 'scalar metrics with different units should not be charted');
assert(
  scalar && filterSqlResultRows(scalar, 'Guangzhou').length === 1,
  'category selection should leave uncharted scalar results unchanged',
);

const duplicateColumns = buildSqlResultView({
  type: 'sql_result',
  columns: ['value', 'value'],
  rows: [[1, 2]],
  row_count: 1,
  truncated: false,
});
assert(duplicateColumns?.rows[0].value_2 === 2, 'duplicate database column labels should not overwrite values');

assert(
  buildSqlResultView({ type: 'sql_result', columns: ['x'], rows: [[1]], row_count: 0, truncated: false }) === null,
  'inconsistent row counts should be rejected',
);
assert(
  buildSqlResultView({ type: 'sql_result', columns: ['x'], rows: [[1]], row_count: 1, truncated: 'false' }) === null,
  'invalid truncation flags should be rejected',
);

console.log('react-sql-result tests passed');
