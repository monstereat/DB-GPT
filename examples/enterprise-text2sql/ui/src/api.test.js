import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildMetricRequest,
  exportPdfReport,
  exportReport,
  loadAvailableMetrics,
  normalizeMetricCatalog,
  openAgentStream,
  parseAgentEvent,
  queryMetric,
  reportTemplateId,
} from './api.js';

test('builds only registered metric request fields', () => {
  assert.deepEqual(
    buildMetricRequest('sales_amount', '2026-04-01', '2026-07-01', 'month'),
    {
      metric_id: 'sales_amount',
      start_date: '2026-04-01',
      end_date: '2026-07-01',
      dimension: 'month',
    },
  );
});

test('includes an explicitly selected metric version', () => {
  assert.deepEqual(
    buildMetricRequest(
      'paid_refund_amount',
      '2026-05-09',
      '2026-05-11',
      'region',
      '2.0.0',
    ),
    {
      metric_id: 'paid_refund_amount',
      start_date: '2026-05-09',
      end_date: '2026-05-11',
      dimension: 'region',
      metric_version: '2.0.0',
    },
  );
});

test('loads the available metric catalog with the bearer token', async () => {
  let request;
  const result = await loadAvailableMetrics({
    token: ' token-value ',
    fetcher: async (url, init) => {
      request = { url, init };
      return {
        ok: true,
        json: async () => ({
          metrics: [{
            id: 'gross_margin_rate',
            name: '毛利率',
            unit: 'percent',
            versions: ['1.0.0'],
            default_version: '1.0.0',
          }],
        }),
      };
    },
  });

  assert.equal(request.url, '/api/metrics/available');
  assert.equal(request.init.headers.Authorization, 'Bearer token-value');
  assert.deepEqual(result, [{
    id: 'gross_margin_rate',
    name: '毛利率',
    unit: 'percent',
    versions: ['1.0.0'],
    defaultVersion: '1.0.0',
  }]);
});

test('normalizes only metrics supported by this UI', () => {
  assert.deepEqual(
    normalizeMetricCatalog({
      metrics: [
        {
          id: 'refund_rate',
          name: '退款率',
          unit: 'percent',
          versions: ['2.0.0', 'bad'],
          default_version: '2.0.0',
        },
        {
          id: 'unrenderable_metric',
          name: '未知指标',
          unit: 'percent',
          versions: ['1.0.0'],
        },
      ],
    }),
    [{
      id: 'refund_rate',
      name: '退款率',
      unit: 'percent',
      versions: ['2.0.0'],
      defaultVersion: '2.0.0',
    }],
  );
});

test('selects a report template that matches the available metric set', () => {
  assert.equal(reportTemplateId(['sales_amount', 'refund_rate']), 'sales-standard@1.0.0');
  assert.equal(reportTemplateId(['gross_margin_rate']), 'admin-margin@1.0.0');
});

test('sends the access token as a bearer credential', async () => {
  let request;
  const result = { metric: { metric_id: 'sales_amount' } };
  const data = await queryMetric({
    token: ' token-value ',
    metricId: 'sales_amount',
    startDate: '2026-04-01',
    endDate: '2026-07-01',
    fetcher: async (url, init) => {
      request = { url, init };
      return { ok: true, json: async () => result };
    },
  });

  assert.equal(request.url, '/api/metrics/query');
  assert.equal(request.init.headers.Authorization, 'Bearer token-value');
  assert.deepEqual(JSON.parse(request.init.body), {
    metric_id: 'sales_amount',
    start_date: '2026-04-01',
    end_date: '2026-07-01',
  });
  assert.equal(data, result);
});

test('opens the authorized DB-GPT ReAct stream with a selected datasource', async () => {
  let request;
  const stream = {};
  const body = await openAgentStream({
    token: ' token-value ',
    question: '华南区第二季度销售额怎么样？',
    databaseName: 'tenant-a-sales',
    convUid: 'conversation-1',
    fetcher: async (url, init) => {
      request = { url, init };
      return { ok: true, body: stream };
    },
  });

  assert.equal(request.url, '/agent-api/v1/chat/react-agent');
  assert.equal(request.init.headers.Authorization, 'Bearer token-value');
  assert.equal(request.init.headers.Accept, 'text/event-stream');
  assert.deepEqual(JSON.parse(request.init.body), {
    conv_uid: 'conversation-1',
    user_input: '华南区第二季度销售额怎么样？',
    chat_mode: 'chat_with_db_execute',
    ext_info: { database_name: 'tenant-a-sales' },
  });
  assert.equal(body, stream);
});

test('parses ReAct SSE final and SQL action metadata', () => {
  assert.deepEqual(
    parseAgentEvent('data: {"type":"final","content":"销售额为 100"}'),
    { type: 'final', content: '销售额为 100' },
  );
  assert.deepEqual(
    parseAgentEvent(
      'data: {"type":"step.meta","action":"sql_query","action_input":{"sql":"SELECT 1"}}',
    ),
    {
      type: 'step.meta',
      action: 'sql_query',
      action_input: { sql: 'SELECT 1' },
    },
  );
  assert.equal(parseAgentEvent('event: ping'), null);
});

test('parses structured SQL results from the ReAct event stream', () => {
  const result = {
    type: 'step.result',
    id: 'step-1',
    result: {
      type: 'sql_result',
      columns: ['region', 'sales'],
      rows: [['华南', '100.00']],
      row_count: 1,
      truncated: false,
    },
  };
  assert.deepEqual(parseAgentEvent(`data: ${JSON.stringify(result)}`), result);
});

test('requests a scoped Excel report with bearer authentication', async () => {
  let request;
  const report = new Blob(['xlsx']);
  const result = await exportReport({
    token: ' token-value ',
    metricIds: ['sales_amount', 'refund_rate'],
    startDate: '2026-04-01',
    endDate: '2026-07-01',
    dimension: 'region',
    fetcher: async (url, init) => {
      request = { url, init };
      return { ok: true, blob: async () => report };
    },
  });

  assert.equal(request.url, '/api/reports/export');
  assert.equal(request.init.headers.Authorization, 'Bearer token-value');
  assert.deepEqual(JSON.parse(request.init.body), {
    metrics: [{ metric_id: 'sales_amount' }, { metric_id: 'refund_rate' }],
    start_date: '2026-04-01',
    end_date: '2026-07-01',
    template_id: 'sales-standard@1.0.0',
    dimension: 'region',
  });
  assert.equal(result, report);
});

test('requests a scoped server PDF report with bearer authentication', async () => {
  let request;
  const report = new Blob(['%PDF-test']);
  const result = await exportPdfReport({
    token: ' token-value ',
    metricIds: ['sales_amount'],
    metricVersions: { sales_amount: '1.0.0' },
    startDate: '2026-04-01',
    endDate: '2026-07-01',
    dimension: 'region',
    fetcher: async (url, init) => {
      request = { url, init };
      return { ok: true, blob: async () => report };
    },
  });

  assert.equal(request.url, '/api/reports/export.pdf');
  assert.equal(request.init.headers.Authorization, 'Bearer token-value');
  assert.deepEqual(JSON.parse(request.init.body), {
    metrics: [{ metric_id: 'sales_amount', metric_version: '1.0.0' }],
    start_date: '2026-04-01',
    end_date: '2026-07-01',
    template_id: 'sales-standard@1.0.0',
    dimension: 'region',
  });
  assert.equal(result, report);
});

test('uses the admin report template when exporting gross margin', async () => {
  let request;
  await exportReport({
    token: 'admin-token',
    metricIds: ['sales_amount', 'gross_margin_rate'],
    startDate: '2026-04-01',
    endDate: '2026-07-01',
    fetcher: async (_url, init) => {
      request = init;
      return { ok: true, blob: async () => new Blob() };
    },
  });

  assert.equal(JSON.parse(request.body).template_id, 'admin-margin@1.0.0');
});

test('exports the selected version for the matching metric', async () => {
  let request;
  await exportReport({
    token: 'token-value',
    metricIds: ['paid_refund_amount'],
    metricVersions: { paid_refund_amount: '2.0.0' },
    startDate: '2026-05-09',
    endDate: '2026-05-11',
    fetcher: async (_url, init) => {
      request = init;
      return { ok: true, blob: async () => new Blob() };
    },
  });
  assert.deepEqual(JSON.parse(request.body).metrics, [
    { metric_id: 'paid_refund_amount', metric_version: '2.0.0' },
  ]);
});

test('exports the selected net sales cohort version', async () => {
  let request;
  await exportPdfReport({
    token: 'token-value',
    metricIds: ['net_sales_amount'],
    metricVersions: { net_sales_amount: '2.0.0' },
    startDate: '2026-04-01',
    endDate: '2026-07-01',
    fetcher: async (_url, init) => {
      request = init;
      return { ok: true, blob: async () => new Blob() };
    },
  });
  assert.deepEqual(JSON.parse(request.body).metrics, [
    { metric_id: 'net_sales_amount', metric_version: '2.0.0' },
  ]);
});

test('exports the selected cohort refund rate version', async () => {
  let request;
  await exportReport({
    token: 'token-value',
    metricIds: ['refund_rate'],
    metricVersions: { refund_rate: '2.0.0' },
    startDate: '2026-04-01',
    endDate: '2026-07-01',
    fetcher: async (_url, init) => {
      request = init;
      return { ok: true, blob: async () => new Blob() };
    },
  });
  assert.deepEqual(JSON.parse(request.body).metrics, [
    { metric_id: 'refund_rate', metric_version: '2.0.0' },
  ]);
});
