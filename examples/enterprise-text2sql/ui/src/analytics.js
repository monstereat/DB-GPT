export function shiftDateByYear(value, years) {
  const [year, month, day] = value.split('-').map(Number);
  const shifted = new Date(Date.UTC(year + years, month - 1, day));
  if (shifted.getUTCMonth() !== month - 1) shifted.setUTCDate(0);
  return shifted.toISOString().slice(0, 10);
}

export function buildComparisonRows(
  current,
  previous,
  metricColumn,
  dimension,
) {
  if (!current) return [];
  const groupColumn = dimension === 'month' ? 'period' : 'region';
  const groupIndex = current.result.columns.indexOf(groupColumn);
  const valueIndex = current.result.columns.indexOf(metricColumn);
  const previousRows = new Map();

  if (previous) {
    const previousGroupIndex = previous.result.columns.indexOf(groupColumn);
    const previousValueIndex = previous.result.columns.indexOf(metricColumn);
    for (const row of previous.result.rows) {
      const previousKey = String(row[previousGroupIndex]);
      const bucket = dimension === 'month' ? previousKey.slice(5) : previousKey;
      previousRows.set(bucket, row[previousValueIndex]);
    }
  }

  return current.result.rows.map((row) => {
    const key = String(row[groupIndex]);
    const bucket = dimension === 'month' ? key.slice(5) : key;
    return {
      key,
      label: dimension === 'month' ? `${key.slice(5)}月` : key,
      value: row[valueIndex] == null ? null : Number(row[valueIndex]),
      previousValue: previousRows.has(bucket)
        ? Number(previousRows.get(bucket))
        : null,
    };
  });
}
