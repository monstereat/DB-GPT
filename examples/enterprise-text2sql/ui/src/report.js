function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => {
    return {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[character];
  });
}

export function buildPrintableReportHtml({
  generatedAt,
  startDate,
  endDate,
  summaries,
  metricName,
  metricVersion,
  definition,
  dimensionName,
  comparisonName,
  rows,
  sql,
}) {
  const summaryRows = summaries
    .map(
      (metric) => `<tr><td>${escapeHtml(metric.name)}</td><td>${escapeHtml(metric.value)}</td><td>${escapeHtml(metric.version)}</td><td>${escapeHtml(metric.definition)}</td></tr>`,
    )
    .join('');
  const detailRows = rows
    .map(
      (row) => `<tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join('')}</tr>`,
    )
    .join('');
  const detailColumns = [dimensionName, metricName, ...(comparisonName ? [comparisonName] : [])];
  const detailHeaders = detailColumns
    .map((column) => `<th>${escapeHtml(column)}</th>`)
    .join('');

  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>经营分析报告</title>
  <style>
    :root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #24343b; }
    body { margin: 0 auto; max-width: 920px; padding: 36px; }
    header { display: flex; justify-content: space-between; align-items: start; border-bottom: 2px solid #287a70; padding-bottom: 18px; }
    h1 { margin: 0 0 8px; font-size: 25px; }
    h2 { margin: 28px 0 12px; font-size: 15px; }
    p, .meta { color: #687980; font-size: 11px; line-height: 1.6; }
    button { border: 0; border-radius: 5px; background: #287a70; color: white; padding: 9px 14px; cursor: pointer; }
    table { width: 100%; border-collapse: collapse; font-size: 11px; }
    th, td { border-bottom: 1px solid #e5ebea; padding: 9px; text-align: left; vertical-align: top; }
    th { background: #f3f7f6; color: #52656b; }
    pre { overflow-wrap: anywhere; white-space: pre-wrap; background: #f5f7f7; padding: 12px; font-size: 9px; }
    @media print { body { padding: 0; } .print-button { display: none; } }
  </style>
</head>
<body>
  <header>
    <div><h1>经营分析报告</h1><div class="meta">统计区间：${escapeHtml(startDate)} 至 ${escapeHtml(endDate)}（左闭右开）</div><div class="meta">生成时间：${escapeHtml(generatedAt)}</div></div>
    <button class="print-button" type="button" onclick="window.print()">打印 / 保存为 PDF</button>
  </header>
  <p>查询结果遵循服务端 OIDC 身份和数据范围授权。指标金额单位、版本及计算口径见下表。</p>
  <h2>核心指标</h2>
  <table><thead><tr><th>指标</th><th>结果</th><th>版本</th><th>口径</th></tr></thead><tbody>${summaryRows}</tbody></table>
  <h2>${escapeHtml(metricName)} · ${escapeHtml(dimensionName)}</h2>
  <p>版本 ${escapeHtml(metricVersion)}：${escapeHtml(definition)}</p>
  <table><thead><tr>${detailHeaders}</tr></thead><tbody>${detailRows}</tbody></table>
  <h2>SQL 预览</h2><pre>${escapeHtml(sql || '无')}</pre>
</body>
</html>`;
}
