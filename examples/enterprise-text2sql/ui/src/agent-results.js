export function buildAgentChartData(result) {
  if (!result || !Array.isArray(result.columns) || !Array.isArray(result.rows)) {
    return null;
  }
  const columns = result.columns.map(String);
  const rows = result.rows.filter(
    (row) => Array.isArray(row) && row.length === columns.length,
  );
  if (!columns.length || !rows.length) return null;

  const numericIndexes = columns.map((_, index) => index).filter((index) =>
    rows.some(
      (row) =>
        row[index] !== null &&
        row[index] !== '' &&
        Number.isFinite(Number(row[index])),
    ),
  );
  if (!numericIndexes.length) return null;

  const categoryIndex = columns.findIndex((_, index) => !numericIndexes.includes(index));
  if (categoryIndex < 0) {
    if (rows.length === 1) {
      return {
        labels: numericIndexes.map((index) => columns[index]),
        series: [{ name: '查询结果', data: numericIndexes.map((index) => Number(rows[0][index])) }],
      };
    }
    return {
      labels: rows.map((_, index) => String(index + 1)),
      series: numericIndexes.map((index) => ({
        name: columns[index],
        data: rows.map((row) => Number(row[index])),
      })),
    };
  }

  return {
    labels: rows.map((row) => String(row[categoryIndex] ?? '')),
    series: numericIndexes.map((index) => ({
      name: columns[index],
      data: rows.map((row) => {
        const value = row[index];
        return value === null || value === '' || !Number.isFinite(Number(value))
          ? null
          : Number(value);
      }),
    })),
  };
}

export function agentCategoryIndex(result) {
  if (!result || !Array.isArray(result.columns) || !Array.isArray(result.rows)) return -1;
  const columns = result.columns.map(String);
  const rows = result.rows.filter(
    (row) => Array.isArray(row) && row.length === columns.length,
  );
  const numericIndexes = columns.map((_, index) => index).filter((index) =>
    rows.some(
      (row) =>
        row[index] !== null &&
        row[index] !== '' &&
        Number.isFinite(Number(row[index])),
    ),
  );
  return columns.findIndex((_, index) => !numericIndexes.includes(index));
}

export function filterAgentResultRows(result, selectedCategory = '') {
  if (!result || !Array.isArray(result.rows)) return [];
  const rows = result.rows.filter(
    (row) => Array.isArray(row) && row.length === result.columns?.length,
  );
  const categoryIndex = agentCategoryIndex(result);
  if (!selectedCategory || categoryIndex < 0) return rows;
  return rows.filter((row) => String(row[categoryIndex] ?? '') === selectedCategory);
}
