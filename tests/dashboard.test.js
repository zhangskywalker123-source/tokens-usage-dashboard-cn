const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');

const projectRoot = path.resolve(__dirname, '..');
const dayMs = 24 * 60 * 60 * 1000;

function beijingDate(offsetDays = 0, hour = 12) {
  const date = new Date(Date.now() + 8 * 60 * 60 * 1000 + offsetDays * dayMs);
  const day = date.toISOString().slice(0, 10);
  return `${day} ${String(hour).padStart(2, '0')}:00:00`;
}

function writeJsonl(file, rows) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, rows.map(row => JSON.stringify(row)).join('\n') + '\n', 'utf8');
}

test('builds a safe dashboard with consistent Beijing windows and WorkBuddy totals', t => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'token-dashboard-test-'));
  t.after(() => fs.rmSync(temp, { recursive: true, force: true }));

  const output = path.join(temp, 'output');
  const home = path.join(temp, 'home');
  fs.mkdirSync(output);
  fs.copyFileSync(path.join(projectRoot, 'build.js'), path.join(output, 'build.js'));
  fs.copyFileSync(path.join(projectRoot, 'chart.umd.min.js'), path.join(output, 'chart.umd.min.js'));

  const today = beijingDate(0, 1);
  const yesterday = beijingDate(-1, 23);
  const duplicateCall = {
    id: 'same-call', timestamp: today,
    providerData: { messageId: 'same-call', model: 'ollama/qwen3.5:9b' },
    message: { usage: { inputTokens: 100, outputTokens: 50, inputTokensDetails: [{ cached_tokens: 20 }] } },
  };
  const independentCall = {
    timestamp: today,
    providerData: { model: 'ollama/qwen3.5:9b' },
    message: { usage: { input_tokens: 100, output_tokens: 50 } },
  };
  const oldCall = {
    timestamp: beijingDate(-31),
    providerData: { model: 'old-workbuddy-model' },
    message: { usage: { inputTokens: 10000, outputTokens: 10000 } },
  };
  const additionalCalls = [
    {
      timestamp: today,
      providerData: { model: 'deepseek-r1' },
      message: { usage: { inputTokens: 450, outputTokens: 50 } },
    },
    {
      timestamp: today,
      providerData: { model: 'gemini-2.5' },
      message: { usage: { inputTokens: 100 } },
    },
  ];
  const credits = [
    { id: 'credit-duplicate', timestamp: today, providerData: { toolResult: { rawResponse: { credit: 5.71 } } } },
    { id: 'credit-duplicate', timestamp: today, providerData: { toolResult: { rawResponse: { credit: 5.71 } } } },
    { timestamp: yesterday, providerData: { toolResult: { rawResponse: { credit: 1.11 } } } },
    { timestamp: yesterday, providerData: { toolResult: { rawResponse: { credit: 2.22 } } } },
    { timestamp: beijingDate(-31), providerData: { toolResult: { rawResponse: { credit: 100 } } } },
  ];
  writeJsonl(path.join(home, '.workbuddy', 'projects', 'local-project', 'events.jsonl'), [
    duplicateCall, { ...duplicateCall, message: { usage: { input_tokens: 100, output_tokens: 50, cache_read_input_tokens: 20 } } },
    oldCall, ...additionalCalls,
    independentCall, ...credits,
  ]);

  const malicious = '</script><script>alert("x")</script><img src=x onerror=alert(1)>';
  const usage = {
    schema: 'codeburn.export.v2', generated: new Date().toISOString(),
    summary: [
      { Period: 'Today', 'Cost (USD)': 0, 'API Calls': 0, Sessions: 0, Projects: 0 },
      { Period: '7 Days', 'Cost (USD)': 1, 'API Calls': 1, Sessions: 1, Projects: 1 },
      { Period: '30 Days', 'Cost (USD)': 10, 'API Calls': 1, Sessions: 1, Projects: 1 },
    ],
    periods: [
      { label: 'Today', daily: [], models: [] },
      { label: '7 Days', daily: [], models: [] },
      { label: '30 Days', daily: [], models: [
        { Model: 'small-cost', 'Cost (USD)': 1, 'API Calls': 1, 'Input Tokens': 100, 'Output Tokens': 0, 'Cache Read Tokens': 0, 'Cache Write Tokens': 0, 'Share (%)': 10 },
        { Model: 'large-cost', 'Cost (USD)': 5, 'API Calls': 5, 'Input Tokens': 500, 'Output Tokens': 0, 'Cache Read Tokens': 0, 'Cache Write Tokens': 0, 'Share (%)': 50 },
      ] },
    ],
    records: [{
      provider: malicious, model: malicious, timestamp: new Date().toISOString(),
      inputTokens: 0, outputTokens: 0, cacheReadTokens: 0, cacheWriteTokens: 0, cost: 0,
    }],
    projects: [
      { Project: `C:\\${malicious}`, 'Cost (USD)': 1, 'API Calls': 1, Sessions: 1, 'Share (%)': 10 },
      { Project: 'C:\\code\\large-project', 'Cost (USD)': 5, 'API Calls': 5, Sessions: 2, 'Share (%)': 50 },
    ],
    tools: [
      { Tool: 'tool-small', Calls: 1 },
      { Tool: 'tool-largest', Calls: 99 },
      { Tool: 'tool-mid', Calls: 10 },
    ],
  };
  fs.writeFileSync(path.join(output, 'usage.json'), JSON.stringify(usage), 'utf8');

  const node = process.execPath;
  const run = spawnSync(node, ['build.js'], {
    cwd: output,
    encoding: 'utf8',
    env: { ...process.env, USERPROFILE: home, HOME: home },
  });
  assert.equal(run.status, 0, run.stderr || run.stdout);

  const html = fs.readFileSync(path.join(output, '看板.html'), 'utf8');
  assert.match(html, /本地模型/);
  assert.match(html, /3 次<\/td>/);
  assert.match(html, /¥0\.45/);
  assert.match(html, /¥71\.45/);
  assert.match(html, /¥0\.29 \/ 920 tokens/);
  assert.doesNotMatch(html, /old-workbuddy-model/);
  assert.match(html, /5\.71 积分/);
  assert.match(html, /3\.33 积分/);
  assert.doesNotMatch(html, /100\.00 分（≈¥5\.00）/);
  assert.doesNotMatch(html, /<script>alert\("x"\)<\/script>/);
  assert.doesNotMatch(html, /<img src=x onerror=alert\(1\)>/);
  assert.match(html, /\\u003c\/script/);

  const clientSection = html.slice(
    html.indexOf('<h2>🖥️ 分客户端统计'),
    html.indexOf('<h2>🏢 分供应商统计'),
  );
  const workbuddyGroup = clientSection.indexOf('<summary><span class="blk-title">🖥️ workbuddy</span>');
  const zeroSpendGroup = clientSection.indexOf('<summary><span class="blk-title">🖥️ &lt;/script&gt;');
  assert.ok(workbuddyGroup >= 0 && zeroSpendGroup >= 0 && workbuddyGroup < zeroSpendGroup,
    'client groups should rank using the displayed total including WorkBuddy credits');
  const creditRank = clientSection.indexOf('<td>图片生成等工具（积分）</td>');
  const deepseekRank = clientSection.indexOf('<td>deepseek-r1</td>');
  const qwenRank = clientSection.indexOf('<td>ollama/qwen3.5:9b</td>');
  const geminiRank = clientSection.indexOf('<td>gemini-2.5</td>');
  assert.ok(creditRank < deepseekRank && deepseekRank < qwenRank && qwenRank < geminiRank,
    'detail rows should descend by their displayed percentage');

  const projectSection = html.slice(html.indexOf('项目花费排行'), html.indexOf('工具调用排行'));
  assert.ok(projectSection.indexOf('large-project</td>') < projectSection.indexOf('&lt;/script&gt;'),
    'project table should descend by share');
  const toolSection = html.slice(html.indexOf('工具调用排行'));
  assert.ok(toolSection.indexOf('tool-largest</div>') < toolSection.indexOf('tool-mid</div>')
    && toolSection.indexOf('tool-mid</div>') < toolSection.indexOf('tool-small</div>'),
  'tool ranking should descend by call count');

  const cdMatch = html.match(/var CD = (\{[^;]+\});/);
  assert.ok(cdMatch, 'embedded chart data should remain valid JSON');
  const chartData = JSON.parse(cdMatch[1]);
  assert.ok(chartData.cost.includes(0.29), 'daily totals include WorkBuddy credit conversion');
  assert.ok(chartData.tokens.includes(920), 'daily token chart includes deduplicated and independent calls');
});
