// build.js — read usage.json (codeburn export) and generate Chinese dashboard 看板.html
// 价格一律按人民币显示（1 USD ≈ 7.1 CNY）；Chart.js 内联，单文件离线可用
const fs = require('fs');
const path = require('path');

const dir = __dirname;
const data = JSON.parse(fs.readFileSync(path.join(dir, 'usage.json'), 'utf8'));
const chartJs = fs.readFileSync(path.join(dir, 'chart.umd.min.js'), 'utf8')
  .replace(/<\/script/gi, '<\\/script');

const RATE = 7.1;
const DAY_MS = 24 * 60 * 60 * 1000;
const BEIJING_OFFSET_MS = 8 * 60 * 60 * 1000;

function parseTimestampMs(value) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Math.abs(value) < 1e11 ? value * 1000 : value;
  }
  if (typeof value !== 'string' || !value.trim()) return NaN;
  const text = value.trim();
  const localDateTime = /^(\d{4}[-/]\d{2}[-/]\d{2})(?:[ T](\d{2}:\d{2}:\d{2}(?:\.\d+)?))?$/.exec(text);
  return Date.parse(localDateTime
    ? `${localDateTime[1].replace(/\//g, '-')}T${localDateTime[2] || '00:00:00'}+08:00`
    : text);
}

function beijingDay(timestampMs) {
  return new Date(timestampMs + BEIJING_OFFSET_MS).toISOString().slice(0, 10);
}

function beijingStartDay(days, today = beijingDay(Date.now())) {
  return new Date(Date.parse(`${today}T00:00:00+08:00`) - Math.max(0, days - 1) * DAY_MS + BEIJING_OFFSET_MS)
    .toISOString().slice(0, 10);
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[ch]);
}

function scriptJson(value) {
  return JSON.stringify(value).replace(/[<>&\u2028\u2029]/g, ch => ({
    '<': '\\u003c', '>': '\\u003e', '&': '\\u0026',
    '\u2028': '\\u2028', '\u2029': '\\u2029',
  })[ch]);
}
// WorkBuddy 积分 → 人民币（官方加量包定价：200积分=10元 / 1000积分=50元，即 0.05 元/积分）
const WB_CREDIT_RATE = 0.05;

// ---------- 供应商映射：模型名 → [供应商, 国内/国外] ----------
const VENDOR_MAP = [
  [/ollama|lm[ -]?studio|llama\.cpp|local[-_/]/i, ['本地模型', '本地']],
  [/gpt|o\d|codex|chatgpt/i, ['OpenAI', '国外']],
  [/claude|sonnet|opus|haiku/i, ['Anthropic', '国外']],
  [/gemini/i, ['Google', '国外']],
  [/grok|xai/i, ['xAI', '国外']],
  [/mistral|codestral|devstral/i, ['Mistral AI', '国外']],
  [/cohere|command[- ]?r/i, ['Cohere', '国外']],
  [/perplexity|sonar/i, ['Perplexity', '国外']],
  [/meta[-/ ]?llama|llama[- ]?[0-9]/i, ['Meta', '国外']],
  [/amazon[./ -]?(?:nova|titan)|nova[- ]?(?:micro|lite|pro)/i, ['Amazon', '国外']],
  [/microsoft[./ -]?phi|\bphi[- ]?[0-9]/i, ['Microsoft', '国外']],
  [/nvidia[./ -]?nemotron|nemotron/i, ['NVIDIA', '国外']],
  [/ai21|jamba/i, ['AI21 Labs', '国外']],
  [/deepseek/i, ['深度求索', '国内']],
  [/kimi|moonshot/i, ['月之暗面', '国内']],
  [/qwen|tongyi/i, ['阿里巴巴', '国内']],
  [/glm|zhipu|chatglm/i, ['智谱 AI', '国内']],
  [/doubao|seed/i, ['字节跳动', '国内']],
  [/hunyuan|hy\d/i, ['腾讯', '国内']],
  [/ernie|wenxin/i, ['百度', '国内']],
  [/minimax|abab/i, ['MiniMax', '国内']],
  [/yi-|lingyi/i, ['零一万物', '国内']],
  [/step/i, ['阶跃星辰', '国内']],
];
function vendorOf(model) {
  if (!model) return ['未知', '-'];
  for (const [re, v] of VENDOR_MAP) if (re.test(model)) return v;
  return ['其他', '-'];
}

// ---------- helpers ----------
const fmt$ = n => '¥' + ((n || 0) * RATE).toFixed(2);   // 入参为美元
const fmtRMB = n => '¥' + (n || 0).toFixed(2);           // 入参已是人民币
const fmtTok = n => {
  n = n || 0;
  if (n >= 1e8) return (n / 1e8).toFixed(2) + ' 亿';
  if (n >= 1e4) return (n / 1e4).toFixed(1) + ' 万';
  return n.toLocaleString();
};
const shortPath = p => {
  if (!p) return '-';
  const parts = String(p).replace(/\\/g, '/').split('/').filter(Boolean);
  return parts.slice(-2).join('/');
};

const period = label => {
  const found = (data.periods || []).find(p => p.label === label);
  return found ? { ...found, daily: found.daily || [], models: found.models || [] } : { daily: [], models: [] };
};
const p30 = period('30 Days');
const bjToday = beijingDay(Date.now());
const start30Day = beijingStartDay(30, bjToday);
const in30DayWindow = timestampMs => Number.isFinite(timestampMs) && beijingDay(timestampMs) >= start30Day && beijingDay(timestampMs) <= bjToday;
const records = (data.records || []).filter(r => in30DayWindow(parseTimestampMs(r.timestamp)));

// ---------- WorkBuddy 本地用量解析 ----------
// 数据源：~/.workbuddy/projects/*/*.jsonl（每次模型调用的 usage + model）
// 参考案例：github.com/clancy-feng/workbuddy-usage-status、Snow7-G/wb-credits
function parseWorkBuddy() {
  const out = { records: [], credits: [] };
  let home;
  try { home = require('os').homedir(); } catch (e) { return out; }
  const projDir = path.join(home, '.workbuddy', 'projects');
  let dirs;
  try { dirs = fs.readdirSync(projDir); } catch (e) { return out; }
  const seenCalls = new Set();
  const seenCredits = new Set();
  for (const d of dirs) {
    const pdir = path.join(projDir, d);
    let files;
    try { files = fs.readdirSync(pdir).filter(f => f.endsWith('.jsonl')); } catch (e) { continue; }
    for (const f of files) {
      let lines;
      try { lines = fs.readFileSync(path.join(pdir, f), 'utf8').split('\n'); } catch (e) { continue; }
      for (const line of lines) {
        if (!line.includes('"usage"') && !line.includes('"credit"')) continue;
        let o;
        try { o = JSON.parse(line); } catch (e) { continue; }
        const pd = o.providerData;
        if (!pd) continue;
        const timestampMs = parseTimestampMs(o.timestamp);
        if (!Number.isFinite(timestampMs)) continue;
        const timestamp = new Date(timestampMs).toISOString();
        const u = o.message && o.message.usage;
        if (pd.model && u) {
          const inT = Number(u.inputTokens ?? u.input_tokens ?? 0);
          const outT = Number(u.outputTokens ?? u.output_tokens ?? 0);
          const cacheDetails = u.inputTokensDetails;
          const cacheDetail = Array.isArray(cacheDetails) && cacheDetails[0]
            ? (cacheDetails[0].cached_tokens ?? cacheDetails[0].cachedTokens)
            : undefined;
          const cacheRead = Number(cacheDetail ?? u.cache_read_input_tokens ?? u.cacheReadInputTokens ?? 0);
          if ([inT, outT, cacheRead].every(n => Number.isFinite(n) && n >= 0)
            && (inT > 0 || outT > 0 || cacheRead > 0)) {
            const id = pd.messageId || o.id;
            const key = id ? JSON.stringify([d, id, timestamp, pd.model, inT, outT, cacheRead]) : null;
            if (!key || !seenCalls.has(key)) {
              if (key) seenCalls.add(key);
              out.records.push({
                provider: 'workbuddy', model: pd.model, timestamp,
                inputTokens: inT, outputTokens: outT, cacheReadTokens: cacheRead,
                cacheWriteTokens: 0, cost: 0,
              });
            }
          }
        }

        const credit = Number(pd.toolResult && pd.toolResult.rawResponse && pd.toolResult.rawResponse.credit);
        if (Number.isFinite(credit) && credit > 0) {
          const id = o.id || pd.messageId;
          const key = id ? JSON.stringify([d, id, timestamp, credit]) : null;
          if (!key || !seenCredits.has(key)) {
            if (key) seenCredits.add(key);
            out.credits.push({ credit, timestamp, timestampMs, day: beijingDay(timestampMs), project: d });
          }
        }
      }
    }
  }
  return out;
}
const wbData = parseWorkBuddy();
const wbRecords = wbData.records;
const wbCredits = wbData.credits;
records.push(...wbRecords.filter(r => in30DayWindow(Date.parse(r.timestamp))));
const wbCreditTotal = wbCredits.reduce((s, x) => s + x.credit, 0);
const wbCreditByDay = {};
for (const x of wbCredits) wbCreditByDay[x.day] = (wbCreditByDay[x.day] || 0) + x.credit;

// 积分按时间窗折算（day 为北京时间 YYYY-MM-DD 字符串）
function wbCreditInDays(n) {
  const today = beijingDay(Date.now());
  const start = beijingStartDay(n, today);
  return wbCredits.filter(x => x.day >= start && x.day <= today).reduce((s, x) => s + x.credit, 0);
}
const wbRMB = c => c * WB_CREDIT_RATE;

// WorkBuddy 模型调用统计（按北京时间，dayStart 含当天）
function wbStatsBetween(dayStart) {
  let calls = 0, tokens = 0;
  for (const r of wbRecords) {
    const day = beijingDay(Date.parse(r.timestamp));
    if (day < dayStart || day > beijingDay(Date.now())) continue;
    calls++;
    tokens += r.inputTokens + r.outputTokens + r.cacheReadTokens + r.cacheWriteTokens;
  }
  return { calls, tokens };
}
const wbToday = wbStatsBetween(bjToday);
const wb7 = wbStatsBetween(beijingStartDay(7, bjToday));
const wb30 = wbStatsBetween(start30Day);

// ---------- aggregation ----------
function aggBy(recs, keyFn) {
  const m = new Map();
  for (const r of recs) {
    const k = keyFn(r);
    if (!m.has(k)) m.set(k, { cost: 0, tokens: 0, calls: 0 });
    const a = m.get(k);
    a.cost += r.cost || 0;
    a.tokens += (r.inputTokens || 0) + (r.outputTokens || 0) + (r.cacheWriteTokens || 0) + (r.cacheReadTokens || 0);
    a.calls += 1;
  }
  return [...m.entries()].map(([k, v]) => ({ key: k, ...v })).sort((a, b) =>
    b.cost - a.cost || b.tokens - a.tokens || b.calls - a.calls || String(a.key).localeCompare(String(b.key)));
}

// ---------- chart datasets ----------
function dailyAgg(recs) {
  const m = new Map();
  for (const r of recs) {
    const timestampMs = parseTimestampMs(r.timestamp);
    if (!Number.isFinite(timestampMs)) continue;
    const d = beijingDay(timestampMs);
    if (!m.has(d)) m.set(d, { Date: d, 'Cost (USD)': 0, 'Input Tokens': 0, 'Output Tokens': 0, 'Cache Read Tokens': 0, 'Cache Write Tokens': 0 });
    const a = m.get(d);
    a['Cost (USD)'] += r.cost || 0;
    a['Input Tokens'] += r.inputTokens || 0;
    a['Output Tokens'] += r.outputTokens || 0;
    a['Cache Read Tokens'] += r.cacheReadTokens || 0;
    a['Cache Write Tokens'] += r.cacheWriteTokens || 0;
  }
  return [...m.values()].sort((a, b) => a.Date.localeCompare(b.Date));
}

const wbCredits30 = wbCredits.filter(x => in30DayWindow(x.timestampMs));
const wbCreditAmount30 = wbCredits30.reduce((s, x) => s + x.credit, 0);
const chartCreditByDay = {};
for (const x of wbCredits30) chartCreditByDay[x.day] = (chartCreditByDay[x.day] || 0) + x.credit;
const dailyByDate = new Map(dailyAgg(records).map(d => [d.Date, d]));
for (const day of Object.keys(chartCreditByDay)) {
  if (!dailyByDate.has(day)) dailyByDate.set(day, { Date: day, 'Cost (USD)': 0, 'Input Tokens': 0, 'Output Tokens': 0, 'Cache Read Tokens': 0, 'Cache Write Tokens': 0 });
}
const daily = [...dailyByDate.values()].sort((a, b) => a.Date.localeCompare(b.Date));
const chartData = {
  labels: daily.map(d => String(d['Date']).slice(5)),
  cost: daily.map(d => +((d['Cost (USD)'] * RATE) + (chartCreditByDay[d.Date] || 0) * WB_CREDIT_RATE).toFixed(2)),
  tokens: daily.map(d => (d['Input Tokens'] || 0) + (d['Output Tokens'] || 0) + (d['Cache Read Tokens'] || 0) + (d['Cache Write Tokens'] || 0)),
};

const t30 = (() => {
  const t = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 };
  for (const d of daily) {
    t.input += d['Input Tokens'] || 0;
    t.output += d['Output Tokens'] || 0;
    t.cacheRead += d['Cache Read Tokens'] || 0;
    t.cacheWrite += d['Cache Write Tokens'] || 0;
  }
  return t;
})();

const clientSpendRMB = g => g.cost * RATE + (g.key === 'workbuddy' ? wbRMB(wbCreditAmount30) : 0);
const byClient = aggBy(records, r => r.provider || '未知客户端').sort((a, b) =>
  clientSpendRMB(b) - clientSpendRMB(a) || b.tokens - a.tokens || b.calls - a.calls || String(a.key).localeCompare(String(b.key)));
const byVendor = aggBy(records, r => vendorOf(r.model)[0]);
const totalCost = records.reduce((s, r) => s + (r.cost || 0), 0);
// 总账（人民币）= 各客户端现金花费 + WorkBuddy 积分折算
const grandTotal = totalCost * RATE + wbRMB(wbCreditAmount30);

// SVG 柱状图（用于分客户端/分供应商块内的每日趋势）
function barChart(rows, valKey, labelKey, color, addedRMBByDay) {
  if (!rows.length) return '<div class="empty">这段时间没有数据</div>';
  const W = 720, H = 160, pad = 30, bw = (W - pad * 2) / rows.length;
  const valueOf = r => addedRMBByDay
    ? (r[valKey] || 0) * RATE + (addedRMBByDay[r[labelKey]] || 0)
    : r[valKey];
  const max = Math.max(...rows.map(valueOf), 0.0001);
  let bars = '', labels = '';
  rows.forEach((r, i) => {
    const h = Math.max(2, (valueOf(r) / max) * (H - 55));
    const x = pad + i * bw + bw * 0.15;
    const toks = (r['Input Tokens'] || 0) + (r['Output Tokens'] || 0) + (r['Cache Read Tokens'] || 0) + (r['Cache Write Tokens'] || 0);
    const amountLabel = addedRMBByDay ? fmtRMB(valueOf(r)) : fmt$(r[valKey]);
    bars += `<rect x="${x}" y="${H - 25 - h}" width="${bw * 0.7}" height="${h}" rx="3" fill="${color}"><title>${escapeHtml(r[labelKey])}：${amountLabel} / ${fmtTok(toks)} tokens</title></rect>`;
    labels += `<text x="${x + bw * 0.35}" y="${H - 8}" font-size="10" fill="#8b8b9e" text-anchor="middle">${escapeHtml(String(r[labelKey]).slice(5))}</text>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" width="100%">${bars}${labels}</svg>`;
}

// 分客户端 / 分供应商的折叠明细块
function detailBlocks(groups, recsOf, titleOf, groupCredit) {
  if (!groups.length) return '<div class="empty">没有数据</div>';
  return groups.map((g, i) => {
    const recs = recsOf(g.key);
    const credit = groupCredit && groupCredit[g.key] ? groupCredit[g.key].amount : 0; // 积分（原始分）
    const creditCalls = groupCredit && groupCredit[g.key] ? groupCredit[g.key].calls : 0;
    const creditRMB = wbRMB(credit);
    const detailDaily = new Map(dailyAgg(recs).map(d => [d.Date, d]));
    let detailCreditByDay = null;
    if (g.key === 'workbuddy') {
      detailCreditByDay = {};
      for (const x of wbCredits30) {
        detailCreditByDay[x.day] = (detailCreditByDay[x.day] || 0) + wbRMB(x.credit);
        if (!detailDaily.has(x.day)) detailDaily.set(x.day, { Date: x.day, 'Cost (USD)': 0, 'Input Tokens': 0, 'Output Tokens': 0, 'Cache Read Tokens': 0, 'Cache Write Tokens': 0 });
      }
    }
    const models = aggBy(recs, r => r.model || '未知模型');
    const rankedRows = models.map(m => {
      const [vendor, region] = vendorOf(m.key);
      // 占比：该模型有花费就按花费占比；没花费（如 WorkBuddy 订阅不限量）就按 tokens 占比
      const byCost = m.cost > 0 && g.cost > 0;
      const shareValue = byCost ? m.cost / g.cost * 100 : m.tokens / (g.tokens || 1) * 100;
      const modelShare = shareValue.toFixed(1) + (byCost ? '%（花费）' : '%（tokens）');
      return { rank: shareValue, key: m.key, html: `<tr>
        <td>${escapeHtml(m.key)}</td>
        <td>${vendor}<span class="tag tag-${region === '国内' ? 'cn' : region === '本地' ? 'local' : 'intl'}">${region}</span></td>
        <td class="num">${fmt$(m.cost)}</td>
        <td class="num">${m.calls}</td>
        <td class="num">${fmtTok(m.tokens)}</td>
        <td class="num">${modelShare}</td>
      </tr>` };
    });
    // 积分不归属具体模型，作为 workbuddy 块里的独立一行
    const allCostRMB = g.cost * RATE + creditRMB;
    if (credit > 0) rankedRows.push({
      rank: allCostRMB > 0 ? creditRMB / allCostRMB * 100 : 0,
      key: '图片生成等工具（积分）',
      html: `<tr>
        <td>图片生成等工具（积分）</td>
        <td>WorkBuddy<span class="tag tag-cn">国内</span></td>
        <td class="num" style="color:#f0b90b">${fmtRMB(creditRMB)}</td>
        <td class="num">${creditCalls} 次</td>
        <td class="num">—</td>
        <td class="num">${allCostRMB > 0 ? (creditRMB / allCostRMB * 100).toFixed(1) + '%（花费）' : '—'}</td>
      </tr>`,
    });
    const modelRows = rankedRows
      .sort((a, b) => b.rank - a.rank || String(a.key).localeCompare(String(b.key)))
      .map(row => row.html).join('');
    const share = grandTotal ? (allCostRMB / grandTotal * 100).toFixed(1) : '0';
    return `<details class="blk" ${i === 0 ? 'open' : ''}>
      <summary><span class="blk-title">${escapeHtml(titleOf(g))}</span>
        <span class="blk-sub">${fmtRMB(allCostRMB)}${credit > 0 ? `（含积分换算 ${fmtRMB(creditRMB)}）` : ''} · ${g.calls} 次调用 · ${fmtTok(g.tokens)} tokens · 占 ${share}%</span></summary>
      <div class="blk-body">
        <h3>🤖 模型用量</h3>
        <table>
          <tr><th>模型</th><th>供应商</th><th class="num">花费</th><th class="num">调用次数</th><th class="num">总 tokens</th><th class="num">占比</th></tr>
          ${modelRows}
        </table>
        <h3>📈 每日花费</h3>
        ${barChart([...detailDaily.values()].sort((a, b) => a.Date.localeCompare(b.Date)), 'Cost (USD)', 'Date', '#43c59e', detailCreditByDay)}
      </div>
    </details>`;
  }).join('');
}

const clientBlocks = detailBlocks(byClient,
  k => records.filter(r => (r.provider || '未知客户端') === k),
  g => `🖥️ ${g.key}`,
  { workbuddy: { amount: wbCreditAmount30, calls: wbCredits30.length } });

const vendorBlocks = detailBlocks(byVendor,
  k => records.filter(r => vendorOf(r.model)[0] === k),
  g => `🏢 ${g.key}`);

// region totals
const regionAgg = { '国内': { cost: 0, tokens: 0, calls: 0 }, '国外': { cost: 0, tokens: 0, calls: 0 }, '本地': { cost: 0, tokens: 0, calls: 0 } };
for (const r of records) {
  const region = vendorOf(r.model)[1];
  if (regionAgg[region]) {
    regionAgg[region].cost += r.cost || 0;
    regionAgg[region].tokens += (r.inputTokens || 0) + (r.outputTokens || 0) + (r.cacheWriteTokens || 0) + (r.cacheReadTokens || 0);
    regionAgg[region].calls += 1;
  }
}

// ---------- summary cards ----------
const sum = {};
for (const s of data.summary || []) sum[s.Period] = s;

const cards = [
  ['今日', sum['Today'], wbCreditInDays(1), wbToday],
  ['近 7 天', sum['7 Days'], wbCreditInDays(7), wb7],
  ['近 30 天', sum['30 Days'], wbCreditInDays(30), wb30],
].map(([label, s, wbC, wbSt]) => {
  if (!s) return '';
  const cashRMB = s['Cost (USD)'] * RATE;
  const wbMoney = wbRMB(wbC);
  const totalRMB = cashRMB + wbMoney;
  const wbLine = wbSt && wbSt.calls > 0
    ? `<br>WorkBuddy 模型调用 ${wbSt.calls} 次 · ${fmtTok(wbSt.tokens)} tokens（订阅不限量，¥0）`
    : '';
  return `
  <div class="card">
    <div class="card-label">${label}总花费</div>
    <div class="card-main">${fmtRMB(totalRMB)}</div>
    <div class="card-sub">现金 ${fmtRMB(cashRMB)}${wbMoney > 0 ? ` + WorkBuddy 积分 ${wbC.toFixed(0)} 分（≈${fmtRMB(wbMoney)}）` : ''}<br>调用 ${s['API Calls']} 次 · ${s['Sessions']} 个会话 · ${s['Projects']} 个项目${wbLine}</div>
  </div>`;
}).join('');

const regionCards = Object.entries(regionAgg).map(([name, v]) => {
  // WorkBuddy 是订阅制，模型对话不花钱；其积分消耗（图片生成等）属于国内侧，折算并入
  const creditRMB = name === '国内' ? wbRMB(wbCreditInDays(30)) : 0;
  const main = v.cost * RATE + creditRMB;
  return `
  <div class="card">
    <div class="card-label">${name}模型合计（近 30 天）</div>
    <div class="card-main">${fmtRMB(main)}</div>
    <div class="card-sub">调用 ${v.calls} 次 · ${fmtTok(v.tokens)} tokens${creditRMB > 0 ? `<br>含 WorkBuddy 积分折算 ${fmtRMB(creditRMB)}（模型对话订阅不限量）` : ''}</div>
  </div>`;
}).join('');

// ---------- tables ----------
const shareValue = value => Number(String(value ?? 0).replace('%', '')) || 0;
const models = [...p30.models].sort((a, b) =>
  shareValue(b['Share (%)']) - shareValue(a['Share (%)'])
  || b['Cost (USD)'] - a['Cost (USD)']
  || String(a['Model']).localeCompare(String(b['Model'])));
const modelRows = models.map(m => {
  const [vendor, region] = vendorOf(m['Model']);
  return `
  <tr>
    <td>${escapeHtml(m['Model'])}</td>
    <td>${vendor}<span class="tag tag-${region === '国内' ? 'cn' : region === '本地' ? 'local' : 'intl'}">${region}</span></td>
    <td class="num">${fmt$(m['Cost (USD)'])}</td>
    <td class="num">${m['API Calls']}</td>
    <td class="num">${fmtTok((m['Input Tokens'] || 0) + (m['Output Tokens'] || 0) + (m['Cache Read Tokens'] || 0) + (m['Cache Write Tokens'] || 0))}</td>
    <td class="num">${m['Share (%)']}%</td>
  </tr>`;
}).join('');

const clientRows = byClient.map(c => `
  <tr><td>${escapeHtml(c.key)}</td><td class="num">${fmt$(c.cost)}</td><td class="num">${c.calls}</td><td class="num">${fmtTok(c.tokens)}</td></tr>`).join('');

const vendorRows = byVendor.map(v => `
  <tr><td>${escapeHtml(v.key)}</td><td class="num">${fmt$(v.cost)}</td><td class="num">${v.calls}</td><td class="num">${fmtTok(v.tokens)}</td></tr>`).join('');

const projects = [...(data.projects || [])].sort((a, b) =>
  shareValue(b['Share (%)']) - shareValue(a['Share (%)'])
  || b['Cost (USD)'] - a['Cost (USD)']
  || String(a['Project']).localeCompare(String(b['Project']))).slice(0, 10);
const projRows = projects.map(p => `
  <tr>
    <td title="${escapeHtml(p['Project'])}">${escapeHtml(shortPath(p['Project']))}</td>
    <td class="num">${fmt$(p['Cost (USD)'])}</td>
    <td class="num">${p['API Calls']}</td>
    <td class="num">${p['Sessions']}</td>
    <td class="num">${p['Share (%)']}%</td>
  </tr>`).join('');

function hbarList(items, nameFn, valFn, valFmt, color) {
  if (!items.length) return '<div class="empty">没有数据</div>';
  const rankedItems = [...items].sort((a, b) => valFn(b) - valFn(a) || String(nameFn(a)).localeCompare(String(nameFn(b))));
  const max = Math.max(...rankedItems.map(valFn), 0.0001);
  return rankedItems.map(it => {
    const w = Math.max(1.5, (valFn(it) / max) * 100);
    return `<div class="row">
      <div class="rowname" title="${escapeHtml(nameFn(it))}">${escapeHtml(nameFn(it))}</div>
      <div class="track"><div class="fill" style="width:${w}%;background:${color}"></div></div>
      <div class="rowval">${valFmt(valFn(it))}</div>
    </div>`;
  }).join('');
}
const toolRows = hbarList(data.tools || [], t => t['Tool'], t => t['Calls'], v => v + ' 次', '#5b8def');

// ---------- html ----------
const generated = new Date(data.generated).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });
const snapshotTime = parseTimestampMs(data.generated);
const freshnessWarning = !Number.isFinite(snapshotTime)
  ? '无法识别 CodeBurn 快照时间，现金用量可能不是最新。请刷新统计。'
  : Date.now() - snapshotTime > 60 * 60 * 1000
    ? `CodeBurn 快照生成于 ${generated}，已超过 60 分钟；现金用量可能不是最新，请点击刷新数据。`
    : '';
const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Tokens 用量看板（中文）</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #16161f; color: #e6e6ee; font-family: "Microsoft YaHei", "微软雅黑", sans-serif; padding: 24px; max-width: 1080px; margin: 0 auto; }
  h1 { font-size: 22px; margin-bottom: 4px; }
  .meta { color: #8b8b9e; font-size: 12px; margin-bottom: 20px; }
  .data-warning { border-left: 3px solid #e1a76b; background: #302a20; color: #f0c98e; padding: 9px 12px; margin: 8px 0 14px; font-size: 13px; }
  .topbar { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
  .refresh-btn { background: #5b8def; color: #fff; border: none; border-radius: 8px; padding: 10px 22px; font-size: 14px; cursor: pointer; font-family: inherit; }
  .refresh-btn:hover { background: #6f9cf2; }
  .refresh-btn:disabled { background: #3a4a6b; color: #9aa7c7; cursor: default; }
  #refreshState { font-size: 12px; color: #8b8b9e; margin-left: 10px; }
  .cards { display: flex; gap: 14px; flex-wrap: wrap; margin: 20px 0 24px; }
  .card { background: #1f1f2b; border: 1px solid #2c2c3a; border-radius: 10px; padding: 16px 20px; flex: 1; min-width: 200px; }
  .card-label { color: #8b8b9e; font-size: 13px; }
  .card-main { font-size: 26px; font-weight: bold; margin: 6px 0; color: #ffd166; }
  .card-sub { color: #8b8b9e; font-size: 12px; }
  h2 { font-size: 16px; margin: 24px 0 10px; color: #c9c9dd; }
  .panel { background: #1f1f2b; border: 1px solid #2c2c3a; border-radius: 10px; padding: 16px; overflow-x: auto; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  @media (max-width: 800px) { .grid { grid-template-columns: 1fr; } }
  .chart-box { position: relative; height: 260px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #2c2c3a; white-space: nowrap; }
  th { color: #8b8b9e; font-weight: normal; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .row { display: flex; align-items: center; gap: 10px; margin: 8px 0; font-size: 13px; }
  .rowname { width: 220px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #c9c9dd; }
  .track { flex: 1; background: #2a2a38; border-radius: 4px; height: 12px; overflow: hidden; }
  .fill { height: 100%; border-radius: 4px; }
  .rowval { width: 160px; text-align: right; color: #8b8b9e; white-space: nowrap; }
  .empty { color: #8b8b9e; font-size: 13px; padding: 10px 0; }
  .tip { color: #6a6a80; font-size: 12px; margin-top: 24px; line-height: 1.8; }
  .tag { display: inline-block; font-size: 11px; padding: 1px 7px; border-radius: 8px; margin-left: 8px; vertical-align: middle; }
  .tag-cn { background: #2c4a3a; color: #43c59e; }
  .tag-intl { background: #3a3a55; color: #9aa7c7; }
  .tag-local { background: #4a3a2c; color: #e1a76b; }
  details.blk { background: #1f1f2b; border: 1px solid #2c2c3a; border-radius: 10px; margin-bottom: 12px; overflow: hidden; }
  details.blk summary { cursor: pointer; padding: 14px 18px; list-style: none; display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; }
  details.blk summary::-webkit-details-marker { display: none; }
  details.blk summary::before { content: '▸'; color: #5b8def; transition: transform 0.15s; }
  details.blk[open] summary::before { content: '▾'; }
  .blk-title { font-size: 15px; font-weight: bold; color: #e6e6ee; }
  .blk-sub { font-size: 12px; color: #8b8b9e; }
  .blk-body { padding: 4px 18px 16px 34px; }
  .blk-body h3 { font-size: 13px; color: #8b8b9e; margin: 14px 0 8px; font-weight: normal; }
</style>
</head>
<body>
<div class="topbar">
  <div>
    <h1>🧮 Tokens 用量看板</h1>
    <div class="meta">数据来源：CodeBurn 本地统计 · 生成时间：${escapeHtml(generated)}（北京时间） · 金额按 1 美元 ≈ ¥7.1 折算</div>
  </div>
  <div><button id="refreshBtn" class="refresh-btn" style="display:none">🔄 刷新数据</button><span id="refreshState"></span></div>
</div>

${freshnessWarning ? `<div class="data-warning" role="status">⚠ ${escapeHtml(freshnessWarning)}</div>` : ''}
<div class="cards">${cards}</div>
<div class="cards">${regionCards}</div>

<h2>🪙 WorkBuddy 积分消耗</h2>
<div class="panel">
  <div class="cards" style="margin-top:0">
    <div class="card">
      <div class="card-label">累计消耗积分</div>
      <div class="card-main" style="color:#f0b90b">${wbCreditTotal.toFixed(2)}</div>
      <div class="card-sub">全部来自图片生成（${wbCredits.length} 次，平均 ${wbCredits.length ? (wbCreditTotal / wbCredits.length).toFixed(2) : 0} 分/张）</div>
    </div>
    <div class="card">
      <div class="card-label">单日最多</div>
      <div class="card-main" style="color:#f0b90b">${(() => { const e = Object.entries(wbCreditByDay).sort((a, b) => b[1] - a[1])[0]; return e ? e[1].toFixed(2) : '0.00'; })()}</div>
      <div class="card-sub">${(() => { const e = Object.entries(wbCreditByDay).sort((a, b) => b[1] - a[1])[0]; return e ? e[0] : '—'; })()}</div>
    </div>
    <div class="card">
      <div class="card-label">模型对话扣费</div>
      <div class="card-main" style="color:#3ecf8e">0.00</div>
      <div class="card-sub">订阅制不限量（本地日志中 LLM 调用 credit 恒为 0）</div>
    </div>
    <div class="card">
      <div class="card-label">积分折合人民币</div>
      <div class="card-main" style="color:#f0b90b">${fmtRMB(wbRMB(wbCreditTotal))}</div>
      <div class="card-sub">按官方加量包 0.05 元/积分（1000 积分=50 元）折算，已计入上方总花费</div>
    </div>
  </div>
  <h3 style="margin:14px 0 6px;color:#8b8b9e;font-size:13px">按日消耗明细</h3>
  ${(() => {
    const rows = Object.entries(wbCreditByDay).sort((a, b) => a[0].localeCompare(b[0]));
    if (!rows.length) return '<div class="empty">没有积分消耗记录</div>';
    const W = 720, H = 160, pad = 30, bw = (W - pad * 2) / rows.length;
    const max = Math.max(...rows.map(([, v]) => v), 0.0001);
    let bars = '', labels = '';
    rows.forEach(([d, v], i) => {
      const h = Math.max(2, (v / max) * (H - 55));
      const x = pad + i * bw + bw * 0.15;
      bars += `<rect x="${x}" y="${H - 25 - h}" width="${bw * 0.7}" height="${h}" rx="3" fill="#f0b90b"><title>${d}：${v.toFixed(2)} 积分</title></rect>`;
      labels += `<text x="${x + bw * 0.35}" y="${H - 8}" font-size="10" fill="#8b8b9e" text-anchor="middle">${d.slice(5)}</text>`;
    });
    return `<svg viewBox="0 0 ${W} ${H}" width="100%">${bars}${labels}</svg>`;
  })()}
</div>

<h2>📊 图表看板（近 30 天）</h2>
<div class="grid">
  <div class="panel"><h2 style="margin-top:0">📈 每日花费趋势</h2><div class="chart-box"><canvas id="chDaily"></canvas></div></div>
  <div class="panel"><h2 style="margin-top:0">🏢 供应商花费占比</h2><div class="chart-box"><canvas id="chVendor"></canvas></div></div>
  <div class="panel"><h2 style="margin-top:0">🖥️ 各客户端花费</h2><div class="chart-box"><canvas id="chClient"></canvas></div></div>
  <div class="panel"><h2 style="margin-top:0">🧩 Tokens 构成</h2><div class="chart-box"><canvas id="chTokens"></canvas></div></div>
</div>

<h2>🖥️ 分客户端统计（点开看每个客户端的明细）</h2>
${clientBlocks}

<h2>🏢 分供应商统计（点开看每家公司的明细）</h2>
${vendorBlocks}

<h2>📁 项目花费排行（近 30 天 Top 10）</h2>
<div class="panel"><table>
  <tr><th>项目</th><th class="num">花费</th><th class="num">调用次数</th><th class="num">会话数</th><th class="num">占比</th></tr>
  ${projRows || '<tr><td colspan="5" class="empty">没有数据</td></tr>'}
</table></div>

<h2>🔧 工具调用排行</h2>
<div class="panel">${toolRows}</div>

<div class="tip">
  提示：<br>
  1. 本看板由本地 CodeBurn 数据生成，不会上传任何信息。<br>
  2. 点右上角「刷新数据」可重新统计并更新本页面。<br>
  3. 客户端日志由 CodeBurn 0.9.27 读取：包括 Claude Code、Codex、Cursor、Gemini CLI、Copilot、Kiro、OpenCode、Qwen、Kimi Code、Goose、Cline、Antigravity、Zed 等；另支持 WorkBuddy 本地 JSONL。具体名单见项目 README。<br>
  4. 供应商名称按模型 ID 关键词分类，不代表本软件能调用或运行该模型；未知名称归入「其他」。
</div>

<script>${chartJs}</script>
<script>
var CD = ${scriptJson({
  labels: chartData.labels,
  cost: chartData.cost,
  tokens: chartData.tokens,
  tokParts: [
    (t30.input / 1e4).toFixed(1),
    (t30.output / 1e4).toFixed(1),
    (t30.cacheRead / 1e4).toFixed(1),
    (t30.cacheWrite / 1e4).toFixed(1),
  ],
  vendors: byVendor.map(v => v.key),
  vendorCost: byVendor.map(v => +(v.cost * RATE).toFixed(2)),
  clients: byClient.map(c => c.key),
  clientCost: byClient.map(c => +clientSpendRMB(c).toFixed(2)),
})};
var PALETTE = ['#5b8def','#43c59e','#a06ee1','#e1856b','#ffd166','#e15b8d','#4dd0e1','#8bc34a','#ff8a65','#7986cb'];
Chart.defaults.color = '#8b8b9e';
Chart.defaults.borderColor = '#2c2c3a';
Chart.defaults.font.family = '"Microsoft YaHei", "微软雅黑", sans-serif';
var cny = function (v) { return '¥' + Number(v).toFixed(2); };
var wan = function (v) { return v + ' 万'; };

// 每日趋势：柱=花费，线=tokens（右轴，单位万）
new Chart(document.getElementById('chDaily'), {
  data: {
    labels: CD.labels,
    datasets: [
      { type: 'bar', label: '花费（元）', data: CD.cost, backgroundColor: '#5b8def', borderRadius: 4, yAxisID: 'y' },
      { type: 'line', label: 'tokens（万）', data: CD.tokens.map(function (t) { return +(t / 1e4).toFixed(1); }), borderColor: '#ffd166', backgroundColor: '#ffd166', pointRadius: 3, tension: 0.3, yAxisID: 'y1' },
    ]
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { position: 'bottom' } },
    scales: {
      y: { position: 'left', ticks: { callback: function (v) { return '¥' + v; } } },
      y1: { position: 'right', grid: { drawOnChartArea: false }, ticks: { callback: function (v) { return v + '万'; } } },
    }
  }
});

new Chart(document.getElementById('chVendor'), {
  type: 'doughnut',
  data: { labels: CD.vendors, datasets: [{ data: CD.vendorCost, backgroundColor: PALETTE, borderColor: '#1f1f2b', borderWidth: 2 }] },
  options: { responsive: true, maintainAspectRatio: false, cutout: '55%',
    plugins: { legend: { position: 'bottom' }, tooltip: { callbacks: { label: function (c) { return ' ' + c.label + '：' + cny(c.parsed); } } } } }
});

new Chart(document.getElementById('chClient'), {
  type: 'bar',
  data: { labels: CD.clients, datasets: [{ data: CD.clientCost, backgroundColor: '#43c59e', borderRadius: 4 }] },
  options: { responsive: true, maintainAspectRatio: false, indexAxis: 'y',
    plugins: { legend: { display: false }, tooltip: { callbacks: { label: function (c) { return ' ' + cny(c.parsed.x); } } } },
    scales: { x: { ticks: { callback: function (v) { return '¥' + v; } } } } }
});

new Chart(document.getElementById('chTokens'), {
  type: 'doughnut',
  data: { labels: ['输入 tokens', '输出 tokens', '缓存读取', '缓存写入'],
    datasets: [{ data: CD.tokParts, backgroundColor: ['#5b8def','#43c59e','#a06ee1','#e1856b'], borderColor: '#1f1f2b', borderWidth: 2 }] },
  options: { responsive: true, maintainAspectRatio: false, cutout: '55%',
    plugins: { legend: { position: 'bottom' }, tooltip: { callbacks: { label: function (c) { return ' ' + c.label + '：' + c.parsed + ' 万'; } } } } }
});

// 刷新按钮：任何打开方式都显示；直连打开时点击给出明确指引
(function () {
  var btn = document.getElementById('refreshBtn');
  var state = document.getElementById('refreshState');
  btn.style.display = 'inline-block';
  btn.addEventListener('click', function () {
    if (!(location.protocol === 'http:' || location.protocol === 'https:')) {
      state.textContent = '⚠️ 当前是直接双击打开的页面，无法在线刷新。请双击桌面的「Tokens用量统计中文看板.exe」重新统计并打开。';
      return;
    }
    btn.disabled = true;
    state.textContent = '正在重新统计，请稍候……';
    fetch('/refresh', { method: 'POST' })
      .then(function (r) {
        if (r.ok) { state.textContent = ''; location.reload(); }
        else { state.textContent = '⚠️ 统计服务没响应。请确认 exe 的黑色窗口还开着（关了它刷新就失效），重开 exe 即可。'; btn.disabled = false; }
      })
      .catch(function () { state.textContent = '⚠️ 统计服务没响应。请确认 exe 的黑色窗口还开着（关了它刷新就失效），重开 exe 即可。'; btn.disabled = false; });
  });
})();
</script>
</body>
</html>`;

fs.writeFileSync(path.join(dir, '看板.html'), html, 'utf8');
console.log('OK: 看板.html generated');
