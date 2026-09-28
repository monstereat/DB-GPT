<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import {
  exportPdfReport as requestPdfReport,
  exportReport as requestReport,
  loadAvailableMetrics,
  openAgentStream,
  parseAgentEvent,
  queryMetric,
} from './api.js';
import { createAgentConversation } from './agent-conversation.js';
import { agentCategoryIndex, buildAgentChartData, filterAgentResultRows } from './agent-results.js';
import { buildComparisonRows, shiftDateByYear } from './analytics.js';
import { buildPrintableReportHtml } from './report.js';
import { completeOidcCallback, createOidcAuthorizationUrl } from './oidc.js';

const publicMetricOptions = [
  { id: 'sales_amount', name: '销售额', unit: 'CNY_cent', versions: ['1.0.0'] },
  { id: 'paid_refund_amount', name: '已支付退款额', unit: 'CNY_cent', versions: ['1.0.0', '2.0.0'] },
  { id: 'net_sales_amount', name: '净销售额', unit: 'CNY_cent', versions: ['1.0.0', '2.0.0'] },
  { id: 'refund_rate', name: '退款率', unit: 'percent', versions: ['1.0.0', '2.0.0'] },
];
const metricOptions = ref(publicMetricOptions.map((metric) => ({ ...metric })));
const dimensions = [
  { id: 'region', name: '区域分布' },
  { id: 'month', name: '月度趋势' },
];

const token = ref('');
const oidcIssuer = ref('');
const oidcClientId = ref('');
const oidcBusy = ref(false);
const oidcExpiresAt = ref(null);
const startDate = ref('2026-04-01');
const endDate = ref('2026-07-01');
const selectedMetric = ref('sales_amount');
const selectedMetricVersion = ref('1.0.0');
const selectedDimension = ref('region');
const compareYear = ref(false);
const selectedRegion = ref('');
const summaries = ref({});
const breakdown = ref(null);
const comparisonBreakdown = ref(null);
const loading = ref(false);
const exporting = ref(false);
const pdfExporting = ref(false);
const agentBusy = ref(false);
const agentQuestion = ref('华南区第二季度销售额和退款率怎么样？');
const agentExampleQuestions = [
  { label: '完成订单总数', question: '第二季度完成了多少笔订单？' },
  { label: '月度销售额', question: '第二季度每月销售额是多少？' },
  { label: '商品类别销量', question: '第二季度各商品类别销量是多少？' },
  { label: '平均退款金额', question: '第二季度平均退款金额是多少？' },
];
const databaseName = ref('');
const agentSql = ref('');
const agentResult = ref(null);
const selectedAgentCategory = ref('');
const agentStatus = ref('');
const agentError = ref('');
const agentConversation = reactive(createAgentConversation());
const errorMessage = ref('');
const activeSql = ref('');
const chartElement = ref(null);
const agentChartElement = ref(null);
let chart;
let agentChart;
let agentRequestController;
let metricCatalogRequest = 0;
let echartsApi;
let echartsLoading;

const activeMetric = computed(
  () => metricOptions.value.find((item) => item.id === selectedMetric.value) ?? metricOptions.value[0],
);
const activeMetricVersions = computed(() => activeMetric.value.versions);
const breakdownRows = computed(() => {
  return buildComparisonRows(
    breakdown.value,
    comparisonBreakdown.value,
    outputColumn(selectedMetric.value),
    selectedDimension.value,
  )
    .filter((item) => !selectedRegion.value || item.key === selectedRegion.value);
});
const agentResultRows = computed(() =>
  filterAgentResultRows(agentResult.value, selectedAgentCategory.value),
);
const agentCategoryName = computed(() => {
  const index = agentCategoryIndex(agentResult.value);
  return index < 0 ? '' : String(agentResult.value.columns[index]);
});
const updatedAt = ref('');

function cleanOidcCallbackUrl() {
  const callbackUrl = new URL(window.location.href);
  for (const key of ['code', 'state', 'session_state', 'iss', 'error', 'error_description']) {
    callbackUrl.searchParams.delete(key);
  }
  window.history.replaceState({}, document.title, callbackUrl);
}

async function handleOidcCallback() {
  const params = new URLSearchParams(window.location.search);
  if (!params.has('code') && !params.has('error')) return;
  oidcBusy.value = true;
  errorMessage.value = '';
  try {
    const result = await completeOidcCallback();
    token.value = result.accessToken;
    oidcIssuer.value = result.issuer;
    oidcClientId.value = result.clientId;
    oidcExpiresAt.value = result.expiresIn ? Date.now() + result.expiresIn * 1000 : null;
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'OIDC 登录失败。';
  } finally {
    cleanOidcCallbackUrl();
    oidcBusy.value = false;
  }
}

async function loginWithOidc() {
  oidcBusy.value = true;
  errorMessage.value = '';
  try {
    const redirectUri = `${window.location.origin}${window.location.pathname}`;
    const authorizationUrl = await createOidcAuthorizationUrl({
      issuer: oidcIssuer.value,
      clientId: oidcClientId.value,
      redirectUri,
    });
    window.location.assign(authorizationUrl);
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '无法开始 OIDC 登录。';
    oidcBusy.value = false;
  }
}

function logoutOidc() {
  token.value = '';
  oidcExpiresAt.value = null;
}

function outputColumn(metricId) {
  return {
    sales_amount: 'sales_cents',
    paid_refund_amount: 'refunded_cents',
    net_sales_amount: 'net_sales_cents',
    refund_rate: 'refund_rate_pct',
    gross_margin_rate: 'gross_margin_rate_pct',
  }[metricId];
}

function metricVersionLabel(metricId, version) {
  if (metricId === 'paid_refund_amount') {
    return version === '1.0.0' ? '退款发生日' : '原订单日';
  }
  if (metricId === 'net_sales_amount') {
    return version === '1.0.0' ? '退款发生日' : '原订单 cohort';
  }
  if (metricId === 'refund_rate') {
    return version === '1.0.0' ? '退款发生日' : '原订单 cohort';
  }
  return '';
}

function formatValue(value, unit) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  const number = Number(value);
  if (unit === 'CNY_cent') {
    return `¥ ${(number / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  return `${number.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}%`;
}

async function runAnalysis() {
  if (!token.value.trim()) {
    errorMessage.value = '请先粘贴 OIDC access token。凭证只保存在当前页面内存中。';
    return;
  }
  if (!startDate.value || !endDate.value || startDate.value >= endDate.value) {
    errorMessage.value = '结束日期必须晚于开始日期。';
    return;
  }

  loading.value = true;
  errorMessage.value = '';
  selectedRegion.value = '';
  try {
    const comparisonStart = shiftDateByYear(startDate.value, -1);
    const comparisonEnd = shiftDateByYear(endDate.value, -1);
    const [sales, refunds, netSales, refundRate, selected, previous, grossMargin] = await Promise.all([
      queryMetric({ token: token.value, metricId: 'sales_amount', startDate: startDate.value, endDate: endDate.value }),
      queryMetric({ token: token.value, metricId: 'paid_refund_amount', metricVersion: selectedMetric.value === 'paid_refund_amount' ? selectedMetricVersion.value : undefined, startDate: startDate.value, endDate: endDate.value }),
      queryMetric({ token: token.value, metricId: 'net_sales_amount', startDate: startDate.value, endDate: endDate.value }),
      queryMetric({ token: token.value, metricId: 'refund_rate', startDate: startDate.value, endDate: endDate.value }),
      queryMetric({ token: token.value, metricId: selectedMetric.value, metricVersion: selectedMetricVersion.value, dimension: selectedDimension.value, startDate: startDate.value, endDate: endDate.value }),
      selectedDimension.value === 'month' && compareYear.value
        ? queryMetric({ token: token.value, metricId: selectedMetric.value, metricVersion: selectedMetricVersion.value, dimension: 'month', startDate: comparisonStart, endDate: comparisonEnd })
        : Promise.resolve(null),
      metricOptions.value.some((metric) => metric.id === 'gross_margin_rate')
        ? queryMetric({ token: token.value, metricId: 'gross_margin_rate', startDate: startDate.value, endDate: endDate.value })
        : Promise.resolve(null),
    ]);
    summaries.value = {
      sales_amount: sales,
      paid_refund_amount: refunds,
      net_sales_amount: netSales,
      refund_rate: refundRate,
      ...(grossMargin ? { gross_margin_rate: grossMargin } : {}),
    };
    breakdown.value = selected;
    comparisonBreakdown.value = previous;
    activeSql.value = selected.metric.sql;
    updatedAt.value = new Intl.DateTimeFormat('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    }).format(new Date());
    await nextTick();
    renderChart();
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '查询失败，请稍后重试。';
  } finally {
    loading.value = false;
  }
}

async function exportReport() {
  if (!token.value.trim()) {
    errorMessage.value = '请先粘贴 OIDC access token。凭证只保存在当前页面内存中。';
    return;
  }
  exporting.value = true;
  errorMessage.value = '';
  try {
    const report = await requestReport({
      token: token.value,
      metricIds: metricOptions.value.map((metric) => metric.id),
      metricVersions: { [selectedMetric.value]: selectedMetricVersion.value },
      startDate: startDate.value,
      endDate: endDate.value,
      dimension: selectedDimension.value,
    });
    const url = URL.createObjectURL(report);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'enterprise-analytics-report.xlsx';
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '报告导出失败。';
  } finally {
    exporting.value = false;
  }
}

async function exportPdf() {
  if (!breakdown.value) {
    errorMessage.value = '请先运行分析，再生成 PDF 报告。';
    return;
  }
  if (!token.value.trim()) {
    errorMessage.value = '请先粘贴 OIDC access token。凭证只保存在当前页面内存中。';
    return;
  }
  pdfExporting.value = true;
  errorMessage.value = '';
  try {
    const report = await requestPdfReport({
      token: token.value,
      metricIds: metricOptions.value.map((metric) => metric.id),
      metricVersions: { [selectedMetric.value]: selectedMetricVersion.value },
      startDate: startDate.value,
      endDate: endDate.value,
      dimension: selectedDimension.value,
    });
    const url = URL.createObjectURL(report);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'enterprise-analytics-report.pdf';
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'PDF 导出失败。';
  } finally {
    pdfExporting.value = false;
  }
}

function printReport() {
  if (!breakdown.value) {
    errorMessage.value = '请先运行分析，再打印报告。';
    return;
  }
  const printWindow = window.open('', '_blank');
  if (!printWindow) {
    errorMessage.value = '浏览器阻止了报告窗口，请允许此页面打开新窗口后重试。';
    return;
  }
  printWindow.opener = null;
  const reportHtml = buildPrintableReportHtml({
    generatedAt: new Date().toISOString(),
    startDate: startDate.value,
    endDate: endDate.value,
    summaries: metricOptions.value.map((metric) => {
      const summary = summaries.value[metric.id];
      return {
        name: metric.name,
        value: summary
          ? formatValue(summary.result.rows?.[0]?.[0], metric.unit)
          : '—',
        version: summary?.metric.metric_version || '—',
        definition: summary?.metric.definition || '未查询',
      };
    }),
    metricName: activeMetric.value.name,
    metricVersion: breakdown.value.metric.metric_version,
    definition: breakdown.value.metric.definition,
    dimensionName: selectedDimension.value === 'month' ? '月份' : '区域',
    comparisonName:
      selectedDimension.value === 'month' && compareYear.value ? '去年同期' : null,
    rows: breakdownRows.value.map((row) => [
      row.label,
      formatValue(row.value, activeMetric.value.unit),
      ...(selectedDimension.value === 'month' && compareYear.value
        ? [formatValue(row.previousValue, activeMetric.value.unit)]
        : []),
    ]),
    sql: activeSql.value,
  });
  printWindow.document.open();
  printWindow.document.write(reportHtml);
  printWindow.document.close();
}

function handleAgentEvent(event) {
  if (!event) return;
  agentConversation.applyEvent(event);
  if (event.type === 'step.result' && event.result?.type === 'sql_result') {
    agentResult.value = event.result;
    selectedAgentCategory.value = '';
    void nextTick().then(renderAgentChart);
  }
  if (event.type === 'step.meta') {
    if ((event.action || '').toLowerCase() === 'sql_query') {
      const input = event.action_input;
      if (typeof input === 'string') {
        try {
          agentSql.value = JSON.parse(input).sql || input;
        } catch {
          agentSql.value = input;
        }
      } else if (input && typeof input === 'object') {
        agentSql.value = input.sql || '';
      }
    }
    agentStatus.value = event.action || 'Agent 正在处理';
  }
  if (event.type === 'done') agentStatus.value = '分析完成';
}

async function askAgent() {
  if (!token.value.trim()) {
    agentError.value = '请先粘贴 OIDC access token。';
    return;
  }
  if (!databaseName.value.trim()) {
    agentError.value = '请输入 DB-GPT 中已授权的数据源名称。';
    return;
  }
  if (!agentQuestion.value.trim()) {
    agentError.value = '请输入业务问题。';
    return;
  }

  agentBusy.value = true;
  agentError.value = '';
  agentConversation.begin(agentQuestion.value.trim());
  agentSql.value = '';
  agentChart?.dispose();
  agentChart = undefined;
  agentResult.value = null;
  selectedAgentCategory.value = '';
  agentStatus.value = '正在连接 DB-GPT Agent';
  const controller = new AbortController();
  agentRequestController = controller;
  try {
    const stream = await openAgentStream({
      token: token.value,
      question: agentQuestion.value.trim(),
      databaseName: databaseName.value.trim(),
      convUid: agentConversation.conversationId,
      signal: controller.signal,
    });
    const reader = stream.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() || '';
      for (const frame of frames) handleAgentEvent(parseAgentEvent(frame));
      if (done) break;
    }
    if (buffer.trim()) handleAgentEvent(parseAgentEvent(buffer));
  } catch (error) {
    if (error?.name !== 'AbortError') {
      agentError.value = error instanceof Error ? error.message : 'Agent 请求失败。';
      agentStatus.value = '请求失败';
      agentConversation.fail(agentError.value);
    }
  } finally {
    if (agentRequestController === controller) {
      agentRequestController = undefined;
      agentBusy.value = false;
    }
  }
}

async function ensureEcharts() {
  if (!echartsApi) {
    echartsLoading ??= Promise.all([
      import('echarts/core'),
      import('echarts/charts'),
      import('echarts/components'),
      import('echarts/renderers'),
    ]).then(([core, charts, components, renderers]) => {
      core.use([
        charts.BarChart,
        charts.LineChart,
        components.LegendComponent,
        components.GridComponent,
        components.TooltipComponent,
        renderers.CanvasRenderer,
      ]);
      echartsApi = core;
      return core;
    });
    await echartsLoading;
  }
}

async function renderChart() {
  if (!chartElement.value || !breakdown.value) return;
  await ensureEcharts();
  if (!chartElement.value || !breakdown.value) return;
  if (!chart) chart = echartsApi.init(chartElement.value);
  const rows = breakdownRows.value;
  const isRate = activeMetric.value.unit === 'percent';
  const isMonthly = selectedDimension.value === 'month';
  chart.setOption({
    animationDuration: 420,
    grid: { left: 48, right: 20, top: compareYear.value && isMonthly ? 42 : 24, bottom: 38 },
    legend: {
      show: compareYear.value && isMonthly,
      top: 5,
      right: 18,
      textStyle: { color: '#718087', fontSize: 9 },
    },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value) => formatValue(value, activeMetric.value.unit),
      backgroundColor: '#182630',
      borderWidth: 0,
      textStyle: { color: '#f4f7f8' },
    },
    xAxis: {
      type: 'category',
      data: rows.map((item) => item.label),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#dce3e7' } },
      axisLabel: { color: '#697981', interval: 0 },
    },
    yAxis: {
      type: 'value',
      min: isRate ? 0 : undefined,
      axisLabel: {
        color: '#89979d',
        formatter: (value) => (isRate ? `${value}%` : `¥${Math.round(value / 100000)}k`),
      },
      splitLine: { lineStyle: { color: '#eef1f2', type: 'dashed' } },
    },
    series: isMonthly
      ? [
          {
            name: String(startDate.value.slice(0, 4)),
            type: 'line',
            data: rows.map((item) => item.value),
            smooth: true,
            symbolSize: 7,
            lineStyle: { width: 3, color: '#287a70' },
            itemStyle: { color: '#287a70' },
            areaStyle: { color: 'rgba(40,122,112,.08)' },
          },
          ...(compareYear.value
            ? [{
                name: String(Number(startDate.value.slice(0, 4)) - 1),
                type: 'line',
                data: rows.map((item) => item.previousValue),
                smooth: true,
                symbolSize: 6,
                lineStyle: { width: 2, type: 'dashed', color: '#d17c45' },
                itemStyle: { color: '#d17c45' },
              }]
            : []),
        ]
      : [
          {
            name: activeMetric.value.name,
            type: 'bar',
            data: rows.map((item) => item.value),
            barMaxWidth: 46,
            itemStyle: { color: '#287a70', borderRadius: [6, 6, 0, 0] },
            emphasis: { itemStyle: { color: '#d17c45' } },
          },
        ],
  }, true);
  chart.off('click');
  chart.on('click', ({ name }) => {
    const clickedRow = rows.find((item) => item.label === name);
    if (!clickedRow) return;
    selectedRegion.value = selectedRegion.value === clickedRow.key ? '' : clickedRow.key;
  });
}

async function renderAgentChart() {
  if (!agentChartElement.value || !agentResult.value) return;
  const data = buildAgentChartData(agentResult.value);
  if (!data) return;
  await ensureEcharts();
  if (!agentChartElement.value) return;
  if (!agentChart || agentChart.isDisposed()) {
    agentChart = echartsApi.init(agentChartElement.value);
  }
  agentChart.setOption({
    animationDuration: 350,
    color: ['#287a70', '#d17c45', '#6179a5', '#9a6da8'],
    grid: { left: 52, right: 20, top: 24, bottom: 42 },
    tooltip: { trigger: 'axis' },
    legend: { show: data.series.length > 1, top: 0 },
    xAxis: {
      type: 'category',
      data: data.labels,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#dce3e7' } },
      axisLabel: { color: '#697981', interval: 0 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#89979d' },
      splitLine: { lineStyle: { color: '#eef1f2', type: 'dashed' } },
    },
    series: data.series.map((item) => ({
      name: item.name,
      type: 'bar',
      data: item.data,
      barMaxWidth: 46,
      itemStyle: { borderRadius: [5, 5, 0, 0] },
    })),
  }, true);
  agentChart.off('click');
  if (agentCategoryIndex(agentResult.value) >= 0) {
    agentChart.on('click', ({ name }) => {
      selectedAgentCategory.value =
        selectedAgentCategory.value === String(name) ? '' : String(name);
    });
  }
}

watch(selectedMetric, (metricId) => {
  const metric = metricOptions.value.find((item) => item.id === metricId);
  selectedMetricVersion.value = metric?.defaultVersion ?? metric?.versions[0] ?? '1.0.0';
  breakdown.value = null;
  comparisonBreakdown.value = null;
  activeSql.value = '';
  selectedRegion.value = '';
});

watch(token, async (identityToken) => {
  const requestId = ++metricCatalogRequest;
  metricOptions.value = publicMetricOptions.map((metric) => ({ ...metric }));
  selectedMetric.value = 'sales_amount';
  selectedMetricVersion.value = '1.0.0';
  summaries.value = {};
  breakdown.value = null;
  comparisonBreakdown.value = null;
  activeSql.value = '';
  selectedRegion.value = '';
  updatedAt.value = '';
  errorMessage.value = '';
  if (!identityToken.trim()) return;
  try {
    const available = await loadAvailableMetrics({ token: identityToken });
    if (requestId !== metricCatalogRequest) return;
    if (available.length) metricOptions.value = available;
  } catch (error) {
    if (requestId !== metricCatalogRequest) return;
    errorMessage.value = error instanceof Error ? error.message : '无法加载可用指标。';
  }
}, { flush: 'sync' });

watch([token, databaseName], () => {
  agentRequestController?.abort();
  agentRequestController = undefined;
  agentBusy.value = false;
  agentConversation.reset();
  agentSql.value = '';
  agentChart?.dispose();
  agentChart = undefined;
  agentResult.value = null;
  agentStatus.value = '';
  agentError.value = '';
});

watch(selectedDimension, () => {
  breakdown.value = null;
  comparisonBreakdown.value = null;
  activeSql.value = '';
  selectedRegion.value = '';
});

watch(compareYear, () => {
  if (breakdown.value) void runAnalysis();
});

watch(breakdownRows, () => {
  if (breakdown.value) void renderChart();
});

function handleResize() {
  chart?.resize();
  agentChart?.resize();
}

onBeforeUnmount(() => {
  agentRequestController?.abort();
  window.removeEventListener('resize', handleResize);
  chart?.dispose();
  agentChart?.dispose();
});
onMounted(() => void handleOidcCallback());
window.addEventListener('resize', handleResize);
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <a class="brand" href="#top" aria-label="DB-GPT 经营分析首页">
        <span class="brand-mark">D</span>
        <span>DB-GPT <b>ANALYTICS</b></span>
      </a>
      <div class="topbar-right">
        <span class="environment"><i></i> SYNTHETIC DATA</span>
        <span class="user-chip"><span class="user-avatar">A</span> 分析工作台</span>
      </div>
    </header>

    <div id="top" class="layout">
      <aside class="sidebar">
        <div class="workspace-label">WORKSPACE</div>
        <button class="nav-item active"><span class="nav-icon">▦</span> 经营分析</button>
        <button class="nav-item" disabled><span class="nav-icon">◷</span> 查询历史</button>
        <div class="sidebar-bottom">
          <div class="source-card">
            <span class="source-dot"></span>
            <div><b>电商演示数据</b><small>只读 · SQLite</small></div>
            <span class="source-menu">···</span>
          </div>
          <div class="sidebar-foot">数据仅用于本地演示</div>
        </div>
      </aside>

      <main class="main-content">
        <div class="page-heading">
          <div>
            <div class="eyebrow">BUSINESS INTELLIGENCE <span>·</span> {{ startDate }} — {{ endDate }}</div>
            <h1>经营分析</h1>
            <p>从可信指标到业务结果，让每个数字都有清晰口径。</p>
          </div>
          <div class="updated" v-if="updatedAt"><span class="live-dot"></span>更新于 {{ updatedAt }}</div>
        </div>

        <section class="auth-panel" aria-label="OIDC 身份认证">
          <label>
            <span>OIDC ISSUER</span>
            <input v-model="oidcIssuer" type="url" autocomplete="url" placeholder="https://id.example.com/realms/analytics" />
          </label>
          <label>
            <span>PUBLIC CLIENT ID</span>
            <input v-model="oidcClientId" autocomplete="off" placeholder="dbgpt-analytics-spa" />
          </label>
          <label class="token-field">
            <span>OIDC ACCESS TOKEN</span>
            <input v-model="token" type="password" autocomplete="off" placeholder="OIDC 登录后自动填入，也可粘贴短期 token" />
          </label>
          <div class="auth-actions">
            <button class="run-button" type="button" :disabled="oidcBusy" @click="loginWithOidc">
              {{ oidcBusy ? '正在连接身份提供方' : 'OIDC 登录' }}
            </button>
            <button class="report-button" type="button" :disabled="!token" @click="logoutOidc">清除凭证</button>
          </div>
        </section>
        <div class="token-note">
          Access token 只保存在当前页面内存，刷新后清除<span v-if="oidcExpiresAt">；预计 {{ new Date(oidcExpiresAt).toLocaleTimeString('zh-CN') }} 到期</span>。仅登录回跳事务暂存于当前标签页会话。
        </div>

        <section class="control-panel" aria-label="分析条件">
          <label>
            <span>开始日期</span>
            <input v-model="startDate" type="date" />
          </label>
          <label>
            <span>结束日期（不含）</span>
            <input v-model="endDate" type="date" />
          </label>
          <label>
            <span>指标</span>
            <select v-model="selectedMetric">
              <option v-for="metric in metricOptions" :key="metric.id" :value="metric.id">{{ metric.name }}</option>
            </select>
          </label>
          <label v-if="activeMetricVersions.length > 1">
            <span>口径版本</span>
            <select v-model="selectedMetricVersion">
              <option v-for="version in activeMetricVersions" :key="version" :value="version">{{ version }}{{ metricVersionLabel(activeMetric.id, version) ? ` · ${metricVersionLabel(activeMetric.id, version)}` : '' }}</option>
            </select>
          </label>
          <label>
            <span>图表维度</span>
            <select v-model="selectedDimension">
              <option v-for="dimension in dimensions" :key="dimension.id" :value="dimension.id">{{ dimension.name }}</option>
            </select>
          </label>
          <label class="compare-control" :class="{ disabled: selectedDimension !== 'month' }">
            <span>趋势比较</span>
            <span class="checkbox-line">
              <input v-model="compareYear" type="checkbox" :disabled="selectedDimension !== 'month'" />
              同比去年
            </span>
          </label>
          <button class="run-button" :disabled="loading" @click="runAnalysis">
            <span v-if="loading" class="spinner"></span>
            <span v-else class="play-icon">▶</span>
            {{ loading ? '分析中' : '运行分析' }}
          </button>
        </section>
        <section class="panel agent-panel" aria-label="DB-GPT 自然语言分析">
          <div class="panel-heading">
            <div>
              <div class="panel-kicker">DB-GPT REACT AGENT</div>
              <h2>自然语言分析</h2>
            </div>
            <span class="unit-label">{{ agentStatus || '复用当前 OIDC 身份' }}</span>
          </div>
          <div class="agent-inputs">
            <label>
              <span>DB-GPT 数据源名称</span>
              <input v-model="databaseName" autocomplete="off" placeholder="输入当前用户可访问的数据源" />
            </label>
            <label class="agent-question-field">
              <span>业务问题</span>
              <textarea v-model="agentQuestion" rows="2" placeholder="例如：华南区第二季度销售额和退款率怎么样？"></textarea>
            </label>
            <button class="run-button" type="button" :disabled="agentBusy" @click="askAgent">
              <span v-if="agentBusy" class="spinner"></span>
              <span v-else class="play-icon">▶</span>
              {{ agentBusy ? 'Agent 分析中' : '询问 Agent' }}
            </button>
          </div>
          <div class="agent-suggestions" aria-label="演示问题">
            <span>试试这些问题</span>
            <button
              v-for="example in agentExampleQuestions"
              :key="example.question"
              type="button"
              :title="example.question"
              :disabled="agentBusy"
              @click="agentQuestion = example.question"
            >
              {{ example.label }}
            </button>
          </div>
          <p class="agent-scope-note">Agent 使用 DB-GPT 数据源连接；该路径依赖数据源只读权限及数据库侧租户/区域策略。下方固定指标 API 仍由演示 tenant executor 独立隔离。</p>
          <div v-if="agentError" class="agent-error" role="alert">{{ agentError }}</div>
          <div v-if="agentConversation.turns.length" class="agent-transcript" aria-live="polite">
            <article v-for="(turn, turnIndex) in agentConversation.turns" :key="`${turnIndex}-${turn.question}`" class="agent-turn">
              <div class="agent-turn-question">{{ turn.question }}</div>
              <div v-if="turn.answer" class="agent-answer">{{ turn.answer }}</div>
              <div v-else-if="turn.status" class="agent-turn-status">{{ turn.status }}</div>
              <div v-if="turn.error" class="agent-error">{{ turn.error }}</div>
            </article>
          </div>
          <div v-if="agentResult" class="agent-result">
            <div class="agent-result-heading">
              <b>Agent 查询结果</b>
              <span>{{ agentResult.row_count }} 行{{ agentResult.truncated ? ' · 图表展示前 50 行' : '' }}</span>
            </div>
            <div v-if="agentCategoryName" class="agent-result-filter">
              <span>{{ selectedAgentCategory ? `${agentCategoryName}：${selectedAgentCategory}` : '点击图表类目筛选结果表' }}</span>
              <button v-if="selectedAgentCategory" type="button" @click="selectedAgentCategory = ''">清除筛选</button>
            </div>
            <div v-if="buildAgentChartData(agentResult)" ref="agentChartElement" class="agent-chart"></div>
            <div class="table-wrap agent-result-table">
              <table>
                <thead><tr><th v-for="column in agentResult.columns" :key="column">{{ column }}</th></tr></thead>
                <tbody>
                  <tr v-for="(row, rowIndex) in agentResultRows" :key="rowIndex">
                    <td v-for="(value, columnIndex) in row" :key="columnIndex">{{ value ?? '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <details v-if="agentSql" class="sql-disclosure agent-sql" open>
            <summary><span>Agent 执行的 SQL</span><span class="sql-caret">⌄</span></summary>
            <pre>{{ agentSql }}</pre>
          </details>
        </section>

        <div v-if="errorMessage" class="error-banner" role="alert">
          <span>!</span>{{ errorMessage }}
        </div>

        <section class="metric-grid" aria-label="核心经营指标">
          <article v-for="metric in metricOptions" :key="metric.id" class="metric-card">
            <div class="metric-top"><span>{{ metric.name }}</span><span class="metric-menu">↗</span></div>
            <strong>{{ summaries[metric.id] ? formatValue(summaries[metric.id].result.rows?.[0]?.[0], metric.unit) : '—' }}</strong>
            <div class="metric-foot">
              <span class="metric-period">{{ startDate }} 至 {{ endDate }}</span>
              <span class="metric-version">v{{ summaries[metric.id]?.metric.metric_version || '1.0.0' }}</span>
            </div>
          </article>
        </section>

        <div class="analysis-grid">
          <section class="panel chart-panel">
            <div class="panel-heading">
              <div>
                <div class="panel-kicker">{{ selectedDimension === 'month' ? 'MONTHLY TREND' : 'REGIONAL BREAKDOWN' }}</div>
                <h2>{{ activeMetric.name }} · {{ selectedDimension === 'month' ? '月度趋势' : '区域分布' }}</h2>
              </div>
              <button v-if="selectedRegion" class="clear-filter" @click="selectedRegion = ''">清除 {{ selectedRegion }} 筛选 ×</button>
              <span v-else class="unit-label">{{ selectedDimension === 'month' ? '按月聚合 · 左闭右开' : '点击柱形筛选区域' }}</span>
            </div>
            <div v-if="breakdown" ref="chartElement" class="chart"></div>
            <div v-else class="chart-empty"><span class="empty-chart-icon">▥</span><b>等待查询数据</b><small>选择时间范围并运行分析</small></div>
            <div class="chart-legend"><span class="legend-swatch"></span>{{ activeMetric.name }} <span>·</span> {{ activeMetric.unit === 'percent' ? '%' : 'CNY' }}<span v-if="selectedDimension === 'month' && compareYear">· 同比去年</span></div>
          </section>

          <section class="panel definition-panel">
            <div class="panel-heading">
              <div>
                <div class="panel-kicker">METRIC GOVERNANCE</div>
                <h2>指标口径</h2>
              </div>
              <span class="version-pill">{{ breakdown?.metric.metric_version || '1.0.0' }}</span>
            </div>
            <div v-if="breakdown" class="definition-content">
              <div class="definition-name">{{ breakdown.metric.definition }}</div>
              <div class="definition-meta">
                <div><span>指标 ID</span><code>{{ breakdown.metric.metric_id }}</code></div>
                <div><span>口径版本</span><b>{{ breakdown.metric.metric_version }}</b></div>
                <div><span>统计区间</span><b>{{ startDate }} — {{ endDate }}（左闭右开）</b></div>
                <div><span>数据来源</span><b>合成电商数据集</b></div>
              </div>
            </div>
            <div v-else class="definition-placeholder">运行查询后查看指标定义、版本与统计区间。</div>
            <details class="sql-disclosure" :open="Boolean(activeSql)">
              <summary><span>SQL 预览</span><span class="sql-caret">⌄</span></summary>
              <pre>{{ activeSql || '查询生成的 SQL 将显示在这里。' }}</pre>
            </details>
          </section>
        </div>

        <section class="panel table-panel">
          <div class="panel-heading table-heading">
            <div>
              <div class="panel-kicker">QUERY RESULT</div>
              <h2>{{ selectedDimension === 'month' ? '月度明细' : '区域明细' }} <span v-if="selectedRegion" class="selected-region">/ {{ selectedDimension === 'month' ? `${selectedRegion.slice(5)}月` : selectedRegion }}</span></h2>
            </div>
            <div class="table-actions">
              <span class="row-count" v-if="breakdown">{{ breakdownRows.length }} {{ selectedDimension === 'month' ? '个月份' : '个区域' }}</span>
              <button class="report-button" type="button" :disabled="!breakdown || loading || pdfExporting" @click="exportPdf">
                {{ pdfExporting ? '生成中…' : '下载 PDF' }}
              </button>
              <button class="report-button" type="button" :disabled="!breakdown || loading" @click="printReport">打印报告</button>
              <button class="report-button" type="button" :disabled="exporting || loading" @click="exportReport">
                {{ exporting ? '生成中…' : '导出 Excel' }}
              </button>
            </div>
          </div>
          <div v-if="breakdown" class="table-wrap">
            <table>
              <thead><tr><th>{{ selectedDimension === 'month' ? '月份' : '区域' }}</th><th class="number-cell">{{ activeMetric.name }}</th><th class="number-cell">{{ selectedDimension === 'month' && compareYear ? '去年同期' : '指标版本' }}</th></tr></thead>
              <tbody>
                <tr v-for="row in breakdownRows" :key="row.key" :class="{ 'row-selected': selectedRegion === row.key }" @click="selectedRegion = selectedRegion === row.key ? '' : row.key">
                  <td><span class="region-badge">{{ row.label.slice(0, 1) }}</span>{{ row.label }}</td>
                  <td class="number-cell value-cell">{{ formatValue(row.value, activeMetric.unit) }}</td>
                  <td class="number-cell version-cell">{{ selectedDimension === 'month' && compareYear ? formatValue(row.previousValue, activeMetric.unit) : breakdown.metric.metric_version }}</td>
                </tr>
                <tr v-if="breakdownRows.length === 0"><td colspan="3" class="no-data">当前筛选范围没有结果。</td></tr>
              </tbody>
            </table>
          </div>
          <div v-else class="table-empty">暂无查询结果</div>
        </section>

        <footer class="page-footer">
          <span><i class="footer-shield">✓</i> 查询通过只读策略执行，结果受当前身份的数据范围约束。</span>
          <span>DB-GPT · Enterprise Analytics Demo</span>
        </footer>
      </main>
    </div>
  </div>
</template>
