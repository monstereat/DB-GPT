export interface SqlResultPayload {
  type: 'sql_result';
  columns: string[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
}

export interface SqlResultView {
  columns: Array<{
    title: string;
    dataIndex: string;
    key: string;
    ellipsis: boolean;
  }>;
  rows: Array<Record<string, unknown>>;
  rowCount: number;
  truncated: boolean;
  chart?: {
    data: Array<Record<string, unknown>>;
    xField: string;
    yField: string;
    chartType: 'bar' | 'line';
  };
}

export function filterSqlResultRows(
  result: SqlResultView,
  selectedCategory: string | null,
): Array<Record<string, unknown>> {
  const chart = result.chart;
  if (selectedCategory === null || !chart) return result.rows;
  return result.rows.filter(row => row[chart.xField] === selectedCategory);
}

export function buildSqlResultView(value: unknown): SqlResultView | null {
  if (!value || typeof value !== 'object') return null;
  const result = value as Partial<SqlResultPayload>;
  if (
    result.type !== 'sql_result' ||
    !Array.isArray(result.columns) ||
    !result.columns.every(column => typeof column === 'string') ||
    !Array.isArray(result.rows) ||
    result.rows.length > 50 ||
    !result.rows.every(row => Array.isArray(row) && row.length === result.columns?.length) ||
    !Number.isInteger(result.row_count) ||
    (result.row_count as number) < result.rows.length ||
    typeof result.truncated !== 'boolean'
  ) {
    return null;
  }

  const columnKeys: string[] = [];
  const occurrences = new Map<string, number>();
  for (const column of result.columns) {
    const occurrence = (occurrences.get(column) || 0) + 1;
    occurrences.set(column, occurrence);
    columnKeys.push(occurrence === 1 ? column : `${column}_${occurrence}`);
  }

  const columns = result.columns.map((column, index) => ({
    title: column,
    dataIndex: columnKeys[index],
    key: columnKeys[index],
    ellipsis: true,
  }));
  const rows = result.rows.map((row, rowIndex) => {
    const record: Record<string, unknown> = { key: String(rowIndex) };
    row.forEach((cell, columnIndex) => {
      record[columnKeys[columnIndex]] = cell;
    });
    return record;
  });

  const chart = result.rows.length > 1 ? buildChart(result.columns, columnKeys, result.rows) : undefined;
  return {
    columns,
    rows,
    rowCount: result.row_count as number,
    truncated: result.truncated,
    chart,
  };
}

function buildChart(columns: string[], columnKeys: string[], rows: unknown[][]): SqlResultView['chart'] {
  const dimensionIndex = columns.findIndex((_, index) => rows.some(row => typeof row[index] === 'string'));
  if (dimensionIndex < 0) return undefined;

  const metricIndex = columns.findIndex((_, index) =>
    rows.some(row => typeof row[index] === 'number' && Number.isFinite(row[index])),
  );
  if (metricIndex < 0 || metricIndex === dimensionIndex) return undefined;

  const data = rows
    .filter(
      row =>
        typeof row[dimensionIndex] === 'string' &&
        typeof row[metricIndex] === 'number' &&
        Number.isFinite(row[metricIndex]),
    )
    .map(row => ({
      [columnKeys[dimensionIndex]]: row[dimensionIndex],
      [columnKeys[metricIndex]]: row[metricIndex],
    }));
  if (data.length < 2) return undefined;

  return {
    data,
    xField: columnKeys[dimensionIndex],
    yField: columnKeys[metricIndex],
    chartType: /month|period|date|time/i.test(columns[dimensionIndex]) ? 'line' : 'bar',
  };
}
