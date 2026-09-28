const SUPPORTED_METRICS = new Set([
  'sales_amount',
  'paid_refund_amount',
  'net_sales_amount',
  'refund_rate',
  'gross_margin_rate',
]);

export function normalizeMetricCatalog(catalog) {
  if (!catalog || !Array.isArray(catalog.metrics)) return [];
  return catalog.metrics.flatMap((metric) => {
    if (
      !metric ||
      !SUPPORTED_METRICS.has(metric.id) ||
      typeof metric.name !== 'string' ||
      !['CNY_cent', 'percent'].includes(metric.unit) ||
      !Array.isArray(metric.versions)
    ) {
      return [];
    }
    const versions = metric.versions.filter(
      (version) => typeof version === 'string' && /^\d+\.\d+\.\d+$/.test(version),
    );
    if (!versions.length) return [];
    return [{
      id: metric.id,
      name: metric.name,
      unit: metric.unit,
      versions,
      defaultVersion: versions.includes(metric.default_version)
        ? metric.default_version
        : versions[0],
    }];
  });
}

export function reportTemplateId(metricIds) {
  return metricIds.includes('gross_margin_rate')
    ? 'admin-margin@1.0.0'
    : 'sales-standard@1.0.0';
}

export async function loadAvailableMetrics({ token, fetcher = fetch }) {
  const response = await fetcher('/api/metrics/available', {
    headers: { Authorization: `Bearer ${token.trim()}` },
  });
  if (!response.ok) {
    if (response.status === 401) {
      throw new Error('登录凭证无效或已过期，请更新 OIDC access token。');
    }
    if (response.status === 403) {
      throw new Error('当前身份没有查看可用指标的权限。');
    }
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `加载指标失败（HTTP ${response.status}）`);
  }
  return normalizeMetricCatalog(await response.json());
}

export function buildMetricRequest(
  metricId,
  startDate,
  endDate,
  dimension,
  metricVersion,
) {
  const body = {
    metric_id: metricId,
    start_date: startDate,
    end_date: endDate,
  };
  if (dimension) body.dimension = dimension;
  if (metricVersion) body.metric_version = metricVersion;
  return body;
}

export async function queryMetric({
  token,
  metricId,
  startDate,
  endDate,
  dimension,
  metricVersion,
  fetcher = fetch,
}) {
  const response = await fetcher('/api/metrics/query', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token.trim()}`,
    },
    body: JSON.stringify(
      buildMetricRequest(metricId, startDate, endDate, dimension, metricVersion),
    ),
  });
  if (!response.ok) {
    if (response.status === 401) {
      throw new Error('登录凭证无效或已过期，请更新 OIDC access token。');
    }
    if (response.status === 403) {
      throw new Error('当前身份没有访问该租户或区域数据的权限。');
    }
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `查询失败（HTTP ${response.status}）`);
  }
  return response.json();
}

export async function openAgentStream({
  token,
  question,
  databaseName,
  convUid,
  fetcher = fetch,
  signal,
}) {
  const response = await fetcher('/agent-api/v1/chat/react-agent', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      Authorization: `Bearer ${token.trim()}`,
    },
    body: JSON.stringify({
      conv_uid: convUid,
      user_input: question,
      chat_mode: 'chat_with_db_execute',
      ext_info: { database_name: databaseName },
    }),
    signal,
  });
  if (!response.ok) {
    if (response.status === 401) {
      throw new Error('登录凭证无效或已过期，请更新 OIDC access token。');
    }
    if (response.status === 403) {
      throw new Error('当前身份无权访问所选 DB-GPT 数据源。');
    }
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `Agent 请求失败（HTTP ${response.status}）`);
  }
  if (!response.body) throw new Error('Agent 没有返回可读取的事件流。');
  return response.body;
}

export function parseAgentEvent(frame) {
  const data = frame
    .split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trim())
    .join('\n');
  if (!data) return null;
  try {
    return JSON.parse(data);
  } catch {
    return null;
  }
}

function buildReportRequest({ metricIds, startDate, endDate, dimension, metricVersions = {} }) {
  return {
    metrics: metricIds.map((metric_id) => ({
      metric_id,
      ...(metricVersions[metric_id]
        ? { metric_version: metricVersions[metric_id] }
        : {}),
    })),
    start_date: startDate,
    end_date: endDate,
    template_id: reportTemplateId(metricIds),
    ...(dimension ? { dimension } : {}),
  };
}

async function requestReport(path, {
  token,
  metricIds,
  startDate,
  endDate,
  dimension,
  metricVersions = {},
  fetcher = fetch,
}) {
  const response = await fetcher(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token.trim()}`,
    },
    body: JSON.stringify(
      buildReportRequest({
        metricIds,
        metricVersions,
        startDate,
        endDate,
        dimension,
      }),
    ),
  });
  if (!response.ok) {
    if (response.status === 401) {
      throw new Error('登录凭证无效或已过期，请更新 OIDC access token。');
    }
    if (response.status === 403) {
      throw new Error('当前身份没有访问该租户或区域数据的权限。');
    }
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `导出失败（HTTP ${response.status}）`);
  }
  return response.blob();
}

export function exportReport(options) {
  return requestReport('/api/reports/export', options);
}

export function exportPdfReport(options) {
  return requestReport('/api/reports/export.pdf', options);
}
