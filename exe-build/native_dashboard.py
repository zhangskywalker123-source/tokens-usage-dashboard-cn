# -*- coding: utf-8 -*-
"""Tokens 用量看板 - 原生窗口版（单文件 exe，无浏览器、无 HTML）

双击运行：统计本机各 AI 工具 token 用量（CodeBurn 数据 + WorkBuddy 本地日志），
直接在原生窗口里展示中文看板。内置 Node 运行时（CodeBurn），刷新时重新统计。
"""
import os
import re
import sys
import json
import math
import time
import shutil
import tempfile
import threading
import subprocess
import traceback
from datetime import datetime, timezone, timedelta
import tkinter as tk
from tkinter import ttk, messagebox

APP_NAME = "Tokens 用量统计中文看板"
RATE = 7.1                       # 1 USD ≈ 7.1 CNY
WB_CREDIT_RATE = 0.05            # WorkBuddy 积分 0.05 元/分（官方加量包定价）
DAY_MS = 24 * 60 * 60 * 1000
BJ = timezone(timedelta(hours=8))

# 诊断：设置 TOKEN_DASH_DEBUG_FILE 环境变量后，把启动里程碑写入该文件
def _dbglog(msg):
    path = os.environ.get('TOKEN_DASH_DEBUG_FILE')
    if not path:
        return
    try:
        with open(path, 'a', encoding='utf-8') as f:
            f.write('%.3f %s\n' % (time.time(), msg))
    except OSError:
        pass

# ---------- 配色（深色主题） ----------
BG = '#16161f'
PANEL = '#1f1f2b'
BORDER = '#2c2c3a'
FG = '#e6e6ee'
SUB = '#8b8b9e'
ACCENT = '#5b8def'
GREEN = '#43c59e'
YELLOW = '#ffd166'
GOLD = '#f0b90b'
PALETTE = ['#5b8def', '#43c59e', '#a06ee1', '#e1856b', '#ffd166',
           '#e15b8d', '#4dd0e1', '#8bc34a', '#ff8a65', '#7986cb']
FONT = 'Microsoft YaHei UI'

# ---------- 供应商映射：模型名 → (供应商, 国内/国外/本地) ----------
VENDOR_MAP = [
    (r'ollama|qwen3|llava', ('本地模型', '本地')),
    (r'gpt|o\d|codex|chatgpt', ('OpenAI', '国外')),
    (r'claude|sonnet|opus|haiku', ('Anthropic', '国外')),
    (r'gemini', ('Google', '国外')),
    (r'deepseek', ('深度求索', '国内')),
    (r'kimi|moonshot', ('月之暗面', '国内')),
    (r'qwen|tongyi', ('阿里巴巴', '国内')),
    (r'glm|zhipu|chatglm', ('智谱 AI', '国内')),
    (r'doubao|seed', ('字节跳动', '国内')),
    (r'hunyuan|hy\d', ('腾讯', '国内')),
    (r'ernie|wenxin', ('百度', '国内')),
    (r'minimax|abab', ('MiniMax', '国内')),
    (r'yi-|lingyi', ('零一万物', '国内')),
    (r'step', ('阶跃星辰', '国内')),
    (r'llama|mistral|grok|command', ('其他国外', '国外')),
]


def vendor_of(model):
    if not model:
        return ('未知', '-')
    for pat, v in VENDOR_MAP:
        if re.search(pat, str(model), re.I):
            return v
    return ('其他', '-')


# ---------- 时间工具 ----------
def parse_ts_ms(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
        return v * 1000 if abs(v) < 1e11 else v
    if not isinstance(v, str) or not v.strip():
        return None
    text = v.strip()
    m = re.match(r'^(\d{4})[-/](\d{2})[-/](\d{2})(?:[ T](\d{2}:\d{2}:\d{2}(?:\.\d+)?))?$', text)
    try:
        if m:
            iso = '%s-%s-%sT%s' % (m.group(1), m.group(2), m.group(3), m.group(4) or '00:00:00')
            dt = datetime.fromisoformat(iso).replace(tzinfo=BJ)
        else:
            dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=BJ)
        return dt.timestamp() * 1000
    except ValueError:
        return None


def bj_day(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).astimezone(BJ).strftime('%Y-%m-%d')


def bj_now_day():
    return bj_day(time.time() * 1000)


def bj_start_day(days, today=None):
    today = today or bj_now_day()
    base = datetime.strptime(today, '%Y-%m-%d').replace(tzinfo=BJ).timestamp() * 1000
    return bj_day(base - max(0, days - 1) * DAY_MS)


# ---------- 格式化 ----------
def fmt_rmb(n):
    return '¥%.2f' % (n or 0)


def fmt_usd(usd):
    return '¥%.2f' % ((usd or 0) * RATE)


def fmt_tok(n):
    n = n or 0
    if n >= 1e8:
        return '%.2f 亿' % (n / 1e8)
    if n >= 1e4:
        return '%.1f 万' % (n / 1e4)
    return format(int(n), ',')


def short_path(p):
    if not p:
        return '-'
    parts = [x for x in re.split(r'[/\\]', str(p)) if x]
    return '/'.join(parts[-2:])


# ---------- WorkBuddy 本地用量解析 ----------
# 数据源：~/.workbuddy/projects/*/*.jsonl（每次模型调用的 usage + model）
def parse_workbuddy(progress_cb=None):
    out = {'records': [], 'credits': []}
    proj_dir = os.path.join(os.path.expanduser('~'), '.workbuddy', 'projects')
    if not os.path.isdir(proj_dir):
        return out
    # 先收集全部 jsonl 文件，便于显示真实进度
    file_list = []
    for d in os.listdir(proj_dir):
        pdir = os.path.join(proj_dir, d)
        if not os.path.isdir(pdir):
            continue
        try:
            for f in os.listdir(pdir):
                if f.endswith('.jsonl'):
                    file_list.append((pdir, f))
        except OSError:
            continue
    total = len(file_list)
    seen_calls = set()
    seen_credits = set()
    for idx, (pdir, f) in enumerate(file_list, 1):
        if progress_cb:
            progress_cb(idx, total, f)
            try:
                with open(os.path.join(pdir, f), encoding='utf-8') as fh:
                    lines = fh.read().split('\n')
            except OSError:
                continue
            for line in lines:
                if '"usage"' not in line and '"credit"' not in line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                pd_ = o.get('providerData') or {}
                ts = parse_ts_ms(o.get('timestamp'))
                if ts is None:
                    continue
                ts_iso = datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat()
                u = (o.get('message') or {}).get('usage') or {}
                model = pd_.get('model')
                if model and u:
                    in_t = float(u.get('inputTokens', u.get('input_tokens', 0)) or 0)
                    out_t = float(u.get('outputTokens', u.get('output_tokens', 0)) or 0)
                    cd = u.get('inputTokensDetails')
                    if isinstance(cd, list) and cd:
                        cache = float(cd[0].get('cached_tokens', cd[0].get('cachedTokens', 0)) or 0)
                    else:
                        cache = float(u.get('cache_read_input_tokens', u.get('cacheReadInputTokens', 0)) or 0)
                    vals = (in_t, out_t, cache)
                    if all(math.isfinite(x) and x >= 0 for x in vals) and (in_t > 0 or out_t > 0 or cache > 0):
                        id_ = pd_.get('messageId') or o.get('id')
                        key = (d, id_, ts, model, in_t, out_t, cache) if id_ else None
                        if key is None or key not in seen_calls:
                            if key:
                                seen_calls.add(key)
                            out['records'].append({
                                'provider': 'workbuddy', 'model': model, 'timestamp': ts_iso,
                                'inputTokens': in_t, 'outputTokens': out_t,
                                'cacheReadTokens': cache, 'cacheWriteTokens': 0, 'cost': 0,
                            })
                raw = ((pd_.get('toolResult') or {}).get('rawResponse') or {})
                try:
                    credit = float(raw.get('credit', 0) or 0)
                except (TypeError, ValueError):
                    credit = 0.0
                if math.isfinite(credit) and credit > 0:
                    id_ = o.get('id') or pd_.get('messageId')
                    key = (d, id_, ts, credit) if id_ else None
                    if key is None or key not in seen_credits:
                        if key:
                            seen_credits.add(key)
                        out['credits'].append({
                            'credit': credit, 'timestampMs': ts,
                            'day': bj_day(ts), 'project': d,
                        })
    return out


# ---------- 聚合 ----------
def agg_by(recs, key_fn):
    m = {}
    for r in recs:
        k = key_fn(r)
        a = m.setdefault(k, {'cost': 0.0, 'tokens': 0.0, 'calls': 0})
        a['cost'] += r.get('cost') or 0
        a['tokens'] += (r.get('inputTokens') or 0) + (r.get('outputTokens') or 0) \
            + (r.get('cacheWriteTokens') or 0) + (r.get('cacheReadTokens') or 0)
        a['calls'] += 1
    rows = [{'key': k, **v} for k, v in m.items()]
    rows.sort(key=lambda a: (-a['cost'], -a['tokens'], -a['calls'], str(a['key'])))
    return rows


def build_data(exe_dir, status_cb=None, prog_cb=None):
    def say(msg):
        if status_cb:
            status_cb(msg)
    def prog(frac):
        if prog_cb:
            prog_cb(max(0.0, min(1.0, frac)))

    usage_path = os.path.join(exe_dir, 'usage.json')
    if not os.path.isfile(usage_path):
        return {'error': '未找到 usage.json'}
    with open(usage_path, encoding='utf-8') as f:
        data = json.load(f)

    today = bj_now_day()
    start30 = bj_start_day(30, today)

    def in_win(ts):
        return ts is not None and bj_day(ts) >= start30 and bj_day(ts) <= today

    say('正在解析 WorkBuddy 本地日志……')
    records = [r for r in (data.get('records') or []) if in_win(parse_ts_ms(r.get('timestamp')))]
    wb = parse_workbuddy(progress_cb=lambda i, n, _f: prog(i / n if n else 1))
    prog(1)
    wb_records = wb['records']
    wb_credits = wb['credits']
    records += [r for r in wb_records if in_win(parse_ts_ms(r.get('timestamp')))]

    wb_credit_total = sum(x['credit'] for x in wb_credits)
    wb_credit_by_day = {}
    for x in wb_credits:
        wb_credit_by_day[x['day']] = wb_credit_by_day.get(x['day'], 0) + x['credit']

    def wb_credit_in_days(n):
        start = bj_start_day(n, today)
        return sum(x['credit'] for x in wb_credits if start <= x['day'] <= today)

    def wb_stats_between(day_start):
        calls, tokens = 0, 0
        for r in wb_records:
            day = bj_day(parse_ts_ms(r['timestamp']))
            if day is None or day < day_start or day > today:
                continue
            calls += 1
            tokens += r['inputTokens'] + r['outputTokens'] + r['cacheReadTokens'] + r['cacheWriteTokens']
        return {'calls': calls, 'tokens': tokens}

    wb30_list = [x for x in wb_credits if in_win(x['timestampMs'])]
    wb_credit_amount30 = sum(x['credit'] for x in wb30_list)
    credit_by_day30 = {}
    for x in wb30_list:
        credit_by_day30[x['day']] = credit_by_day30.get(x['day'], 0) + x['credit']

    # 每日序列（cost 已并入积分折算人民币）
    daily = {}
    t30 = {'input': 0.0, 'output': 0.0, 'cacheRead': 0.0, 'cacheWrite': 0.0}
    for r in records:
        ts = parse_ts_ms(r.get('timestamp'))
        if ts is None:
            continue
        d = bj_day(ts)
        a = daily.setdefault(d, {'cost': 0.0, 'tokens': 0.0})
        a['cost'] += r.get('cost') or 0
        tok = (r.get('inputTokens') or 0) + (r.get('outputTokens') or 0) \
            + (r.get('cacheReadTokens') or 0) + (r.get('cacheWriteTokens') or 0)
        a['tokens'] += tok
        t30['input'] += r.get('inputTokens') or 0
        t30['output'] += r.get('outputTokens') or 0
        t30['cacheRead'] += r.get('cacheReadTokens') or 0
        t30['cacheWrite'] += r.get('cacheWriteTokens') or 0
    for d in credit_by_day30:
        daily.setdefault(d, {'cost': 0.0, 'tokens': 0.0})
    days_sorted = sorted(daily.keys())
    chart = {
        'labels': [d[5:] for d in days_sorted],
        'cost': [round(daily[d]['cost'] * RATE + credit_by_day30.get(d, 0) * WB_CREDIT_RATE, 2) for d in days_sorted],
        'tokens': [daily[d]['tokens'] for d in days_sorted],
    }

    def client_spend_rmb(g):
        return g['cost'] * RATE + (wb_credit_amount30 * WB_CREDIT_RATE if g['key'] == 'workbuddy' else 0)

    by_client = agg_by(records, lambda r: r.get('provider') or '未知客户端')
    by_client.sort(key=lambda a: (-client_spend_rmb(a), -a['tokens'], -a['calls'], str(a['key'])))
    by_vendor = agg_by(records, lambda r: vendor_of(r.get('model'))[0])

    total_cost = sum(r.get('cost') or 0 for r in records)
    grand_total = total_cost * RATE + wb_credit_amount30 * WB_CREDIT_RATE

    # 客户端 / 供应商的明细（模型行 + 每日 RMB 序列）
    def group_detail(key, recs):
        models = agg_by(recs, lambda r: r.get('model') or '未知模型')
        g_cost = sum(r.get('cost') or 0 for r in recs)
        g_tokens = sum((r.get('inputTokens') or 0) + (r.get('outputTokens') or 0)
                       + (r.get('cacheReadTokens') or 0) + (r.get('cacheWriteTokens') or 0) for r in recs)
        credit = credit_by_day30 if key == 'workbuddy' else None
        rows = []
        for m in models:
            vendor, region = vendor_of(m['key'])
            by_cost = m['cost'] > 0 and g_cost > 0
            share = (m['cost'] / g_cost * 100) if by_cost else (m['tokens'] / (g_tokens or 1) * 100)
            rows.append({
                'model': m['key'], 'vendor': vendor, 'region': region,
                'cost': fmt_usd(m['cost']), 'calls': m['calls'], 'tokens': fmt_tok(m['tokens']),
                'share': '%.1f%s' % (share, '%（花费）' if by_cost else '%（tokens）'),
                '_rank': share,
            })
        credit_calls = len(wb30_list) if key == 'workbuddy' else 0
        credit_amount = wb_credit_amount30 if key == 'workbuddy' else 0
        credit_rmb = credit_amount * WB_CREDIT_RATE
        all_cost_rmb = g_cost * RATE + credit_rmb
        if credit_amount > 0:
            rows.append({
                'model': '图片生成等工具（积分）', 'vendor': 'WorkBuddy', 'region': '国内',
                'cost': fmt_rmb(credit_rmb), 'calls': '%d 次' % credit_calls, 'tokens': '—',
                'share': '%.1f%%（花费）' % (credit_rmb / all_cost_rmb * 100) if all_cost_rmb > 0 else '—',
                '_rank': credit_rmb / all_cost_rmb * 100 if all_cost_rmb > 0 else 0,
            })
        rows.sort(key=lambda a: (-a['_rank'], str(a['model'])))
        dd = {}
        for r in recs:
            ts = parse_ts_ms(r.get('timestamp'))
            if ts is None:
                continue
            d = bj_day(ts)
            dd[d] = dd.get(d, 0.0) + (r.get('cost') or 0) * RATE
        if credit:
            for d, c in credit.items():
                dd[d] = dd.get(d, 0.0) + c * WB_CREDIT_RATE
        return {
            'rows': rows,
            'daily_rmb': [(d, round(dd[d], 2)) for d in sorted(dd.keys())],
            'credit_rmb': credit_rmb, 'credit_amount': credit_amount,
            'all_cost_rmb': all_cost_rmb,
            'share': '%.1f' % (all_cost_rmb / grand_total * 100) if grand_total else '0.0',
        }

    say('正在汇总统计……')
    client_details = {g['key']: group_detail(g['key'], [r for r in records if (r.get('provider') or '未知客户端') == g['key']]) for g in by_client}
    vendor_details = {}
    for g in by_vendor:
        recs = [r for r in records if vendor_of(r.get('model'))[0] == g['key']]
        vendor_details[g['key']] = group_detail(g['key'], recs)

    region_agg = {name: {'cost': 0.0, 'tokens': 0.0, 'calls': 0} for name in ('国内', '国外', '本地')}
    for r in records:
        region = vendor_of(r.get('model'))[1]
        if region in region_agg:
            a = region_agg[region]
            a['cost'] += r.get('cost') or 0
            a['tokens'] += (r.get('inputTokens') or 0) + (r.get('outputTokens') or 0) \
                + (r.get('cacheReadTokens') or 0) + (r.get('cacheWriteTokens') or 0)
            a['calls'] += 1

    sum_map = {}
    for s in data.get('summary') or []:
        sum_map[s.get('Period')] = s

    def num(v):
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    cards = []
    for label, period, wb_c, wb_st in (
            ('今日', 'Today', wb_credit_in_days(1), wb_stats_between(today)),
            ('近 7 天', '7 Days', wb_credit_in_days(7), wb_stats_between(bj_start_day(7, today))),
            ('近 30 天', '30 Days', wb_credit_in_days(30), wb_stats_between(start30))):
        s = sum_map.get(period)
        if not s:
            continue
        cash = num(s.get('Cost (USD)')) * RATE
        wb_money = wb_c * WB_CREDIT_RATE
        wb_line = ''
        if wb_st['calls'] > 0:
            wb_line = '\nWorkBuddy 模型调用 %d 次 · %s tokens（订阅不限量，¥0）' % (wb_st['calls'], fmt_tok(wb_st['tokens']))
        cards.append({
            'label': label + '总花费', 'main': fmt_rmb(cash + wb_money),
            'sub': '现金 %s%s\n调用 %s 次 · %s 个会话 · %s 个项目%s' % (
                fmt_rmb(cash),
                (' + WorkBuddy 积分 %d 分（≈%s）' % (wb_c, fmt_rmb(wb_money))) if wb_money > 0 else '',
                s.get('API Calls'), s.get('Sessions'), s.get('Projects'), wb_line),
        })

    region_cards = []
    for name in ('国内', '国外', '本地'):
        v = region_agg[name]
        credit_rmb = wb_credit_in_days(30) * WB_CREDIT_RATE if name == '国内' else 0
        sub = '调用 %d 次 · %s tokens' % (v['calls'], fmt_tok(v['tokens']))
        if credit_rmb > 0:
            sub += '\n含 WorkBuddy 积分折算 %s（模型对话订阅不限量）' % fmt_rmb(credit_rmb)
        region_cards.append({'label': '%s模型合计（近 30 天）' % name,
                             'main': fmt_rmb(v['cost'] * RATE + credit_rmb), 'sub': sub})

    share_value = lambda v: num(str(v).replace('%', ''))
    projects = sorted(data.get('projects') or [],
                      key=lambda a: (-share_value(a.get('Share (%)')), -num(a.get('Cost (USD)')), str(a.get('Project'))))[:10]

    try:
        generated = datetime.fromisoformat(str(data.get('generated')).replace('Z', '+00:00'))
        generated = generated.astimezone(BJ).strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        generated = str(data.get('generated'))

    day_max = max(wb_credit_by_day.items(), key=lambda kv: kv[1]) if wb_credit_by_day else (None, 0)
    return {
        'cards': cards, 'region_cards': region_cards,
        'wb': {
            'total': wb_credit_total, 'count': len(wb_credits),
            'avg': wb_credit_total / len(wb_credits) if wb_credits else 0,
            'day_max': day_max, 'rmb': wb_credit_total * WB_CREDIT_RATE,
            'by_day': sorted(wb_credit_by_day.items()),
        },
        'chart': chart,
        'tok_parts': [('输入 tokens', t30['input'] / 1e4), ('输出 tokens', t30['output'] / 1e4),
                      ('缓存读取', t30['cacheRead'] / 1e4), ('缓存写入', t30['cacheWrite'] / 1e4)],
        'vendors': [(g['key'], round(g['cost'] * RATE, 2)) for g in by_vendor],
        'clients': [(g['key'], round(client_spend_rmb(g), 2)) for g in by_client],
        'by_client': by_client, 'by_vendor': by_vendor,
        'client_details': client_details, 'vendor_details': vendor_details,
        'grand_total': grand_total,
        'projects': projects,
        'tools': sorted(data.get('tools') or [], key=lambda t: -num(t.get('Calls'))),
        'generated': generated,
    }


# ---------- exe 内嵌运行时（Node + CodeBurn，打包为 zip 以缩小体积、加快启动解压） ----------
def find_dirs():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable), sys._MEIPASS
    override = os.environ.get('TOKEN_DASH_DIR')
    if override and os.path.isdir(override):
        return override, override
    return os.path.dirname(os.path.abspath(__file__)), os.path.dirname(os.path.abspath(__file__))


def _runtime_zip_candidates(meipass):
    # 打包后：datas 把 runtime.zip 放到 meipass 根目录；开发模式在 bundle/ 下
    return [os.path.join(meipass, 'runtime.zip'), os.path.join(meipass, 'bundle', 'runtime.zip')]


def ensure_runtime(exe_dir, meipass, log, prog_cb=None):
    """确保 exe 旁的 _runtime 完整；首次运行从内嵌 zip 解压（带进度）。"""
    runtime_dir = os.path.join(exe_dir, '_runtime')
    node = os.path.join(runtime_dir, 'node.exe')
    cli = os.path.join(runtime_dir, 'node_modules', 'codeburn', 'dist', 'cli.js')
    if os.path.isfile(node) and os.path.isfile(cli):
        return runtime_dir
    import zipfile
    zip_path = next((p for p in _runtime_zip_candidates(meipass) if os.path.isfile(p)), None)
    if zip_path is None:
        raise FileNotFoundError('内置运行时不存在（runtime.zip 未找到）。')
    log('首次运行，正在准备运行环境（只需一次，约 10 秒）……')
    t = time.time()
    os.makedirs(exe_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        total = max(1, len(names))
        for idx, name in enumerate(names, 1):
            zf.extract(name, runtime_dir)
            if prog_cb and (idx % 200 == 0 or idx == total):
                prog_cb(idx / total)
    if not (os.path.isfile(node) and os.path.isfile(cli)):
        raise RuntimeError('运行时文件不完整，请删除程序旁的 _runtime 文件夹后重试。')
    log('环境准备完成（%.1f 秒）' % (time.time() - t))
    return runtime_dir


def collect(exe_dir, runtime_dir, log):
    """运行 codeburn export，原子替换 usage.json。"""
    node = os.path.join(runtime_dir, 'node.exe')
    cli = os.path.join(runtime_dir, 'node_modules', 'codeburn', 'dist', 'cli.js')
    env = dict(os.environ)
    env['NODE_PATH'] = os.path.join(runtime_dir, 'node_modules')
    usage_json = os.path.join(exe_dir, 'usage.json')
    fd, staged = tempfile.mkstemp(prefix='.usage-', suffix='.json', dir=exe_dir)
    os.close(fd)
    try:
        log('正在扫描本机各 AI 工具的用量数据（codex / claude / cursor 等）……')
        r = subprocess.run([node, cli, 'export', '--format', 'json', '-o', staged],
                           cwd=exe_dir, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if r.returncode != 0 or not os.path.isfile(staged):
            return False, r.stdout.decode('utf-8', 'ignore')[-800:]
        with open(staged, encoding='utf-8') as f:
            usage = json.load(f)
        if not isinstance(usage, dict) or not isinstance(usage.get('records'), list):
            return False, 'CodeBurn 导出的数据格式不正确。'
        os.replace(staged, usage_json)
        return True, ''
    except (OSError, ValueError) as exc:
        return False, str(exc)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)


# ---------- UI ----------
class ScrollFrame(tk.Frame):
    def __init__(self, master, **kw):
        super().__init__(master, bg=BG, **kw)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        self.vbar = tk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.vbar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.inner.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.bind_all('<MouseWheel>', self._wheel)

    def _wheel(self, e):
        self.canvas.yview_scroll(int(-e.delta / 120), 'units')


class Collapsible(tk.Frame):
    """可折叠区块：标题行 + 正文。"""
    def __init__(self, master, title, sub, open_=False):
        super().__init__(master, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        self.body = tk.Frame(self, bg=PANEL)
        head = tk.Frame(self, bg=PANEL)
        head.pack(fill='x')
        self._arrow = tk.Label(head, text='▾' if open_ else '▸', bg=PANEL, fg=ACCENT,
                               font=(FONT, 12), cursor='hand2')
        self._arrow.pack(side='left', padx=(10, 4))
        tk.Label(head, text=title, bg=PANEL, fg=FG, font=(FONT, 12, 'bold')).pack(side='left')
        tk.Label(head, text=sub, bg=PANEL, fg=SUB, font=(FONT, 10)).pack(side='left', padx=12)
        self._bind_toggle(head)
        self._bind_toggle(self._arrow)
        if open_:
            self.body.pack(fill='x', padx=10, pady=(0, 12))

    def _bind_toggle(self, w):
        w.bind('<Button-1>', self._toggle)
        for ch in w.winfo_children():
            self._bind_toggle(ch)

    def _toggle(self, _e=None):
        if self.body.winfo_manager():
            self.body.pack_forget()
            self._arrow.configure(text='▸')
        else:
            self.body.pack(fill='x', padx=10, pady=(0, 12))
            self._arrow.configure(text='▾')


def make_card(parent, label, main, sub, main_color=YELLOW, width=190):
    f = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
    f.pack(side='left', padx=(0, 12), pady=4, fill='both', expand=True)
    tk.Label(f, text=label, bg=PANEL, fg=SUB, font=(FONT, 10), wraplength=width).pack(anchor='w', padx=12, pady=(10, 0))
    tk.Label(f, text=main, bg=PANEL, fg=main_color, font=(FONT, 20, 'bold')).pack(anchor='w', padx=12)
    tk.Label(f, text=sub, bg=PANEL, fg=SUB, font=(FONT, 9), justify='left').pack(anchor='w', padx=12, pady=(0, 10))
    return f


def draw_bars(canvas, items, color=ACCENT, value_fmt=None, h=150, label_every=1):
    """items: [(label, value)]，纯柱图。"""
    canvas.delete('all')
    canvas.update_idletasks()
    W = max(canvas.winfo_width(), 400)
    H = h
    canvas.configure(height=H)
    if not items:
        canvas.create_text(W / 2, H / 2, text='这段时间没有数据', fill=SUB, font=(FONT, 11))
        return
    pad = 30
    n = len(items)
    bw = (W - pad * 2) / n
    mx = max(v for _, v in items) or 1e-9
    for i, (lab, v) in enumerate(items):
        bh = max(2, v / mx * (H - 55))
        x = pad + i * bw + bw * 0.15
        canvas.create_rectangle(x, H - 25 - bh, x + bw * 0.7, H - 25, fill=color, outline='')
        if i % label_every == 0 or n <= 12:
            canvas.create_text(x + bw * 0.35, H - 8, text=lab, fill=SUB,
                               font=(FONT, 8), anchor='n')
    mxv = max(v for _, v in items)
    if value_fmt:
        canvas.create_text(pad, 8, text=value_fmt(mxv), fill=SUB, font=(FONT, 8), anchor='w')


def draw_bar_line(canvas, labels, bars, line, h=230):
    """柱=花费（左轴），线=tokens 万（右轴）。"""
    canvas.delete('all')
    canvas.update_idletasks()
    W = max(canvas.winfo_width(), 400)
    H = h
    canvas.configure(height=H)
    if not bars:
        canvas.create_text(W / 2, H / 2, text='没有数据', fill=SUB, font=(FONT, 11))
        return
    pad_l, pad_r, pad_b, pad_t = 46, 46, 26, 14
    n = len(bars)
    bw = (W - pad_l - pad_r) / n
    mx_b = max(bars) or 1e-9
    mx_l = max(line) or 1e-9
    base = H - pad_b
    step = max(1, math.ceil(n / 12))
    for i, v in enumerate(bars):
        x = pad_l + i * bw + bw * 0.15
        bh = max(1, v / mx_b * (H - pad_t - pad_b - 10))
        canvas.create_rectangle(x, base - bh, x + bw * 0.7, base, fill=ACCENT, outline='')
        if i % step == 0:
            canvas.create_text(x + bw * 0.35, H - 12, text=labels[i], fill=SUB, font=(FONT, 8), anchor='n')
    pts = []
    for i, v in enumerate(line):
        x = pad_l + i * bw + bw * 0.5
        y = base - (v / mx_l if mx_l else 0) * (H - pad_t - pad_b - 10)
        pts += [x, y]
    if len(pts) >= 4:
        canvas.create_line(*pts, fill=YELLOW, width=2)
    for i in range(0, n):
        x = pad_l + i * bw + bw * 0.5
        y = base - (line[i] / mx_l if mx_l else 0) * (H - pad_t - pad_b - 10)
        canvas.create_oval(x - 2.5, y - 2.5, x + 2.5, y + 2.5, fill=YELLOW, outline='')
    canvas.create_text(4, pad_t, text='¥%.0f' % mx_b, fill=SUB, font=(FONT, 8), anchor='w')
    canvas.create_text(W - 4, pad_t, text='%.0f万' % mx_l, fill=YELLOW, font=(FONT, 8), anchor='e')
    canvas.create_line(pad_l, base, W - pad_r, base, fill=BORDER)


def draw_pie(canvas, items, h=230, val_fmt=None):
    """items: [(label, value)]，饼图 + 右侧图例。"""
    canvas.delete('all')
    canvas.update_idletasks()
    W = max(canvas.winfo_width(), 400)
    H = h
    canvas.configure(height=H)
    items = [(l, v) for l, v in items if v > 0]
    if not items:
        canvas.create_text(W / 2, H / 2, text='没有数据', fill=SUB, font=(FONT, 11))
        return
    if val_fmt is None:
        val_fmt = lambda v: '¥%.2f' % v
    total = sum(v for _, v in items)
    cx, cy, r = H / 2 - 8, H / 2, min(H / 2 - 14, 82)
    start = 0.0
    for i, (lab, v) in enumerate(items):
        color = PALETTE[i % len(PALETTE)]
        if i == len(items) - 1:
            # 末段收到 359.99：Tk 的 arc extent=360 会画成空（已实测确认）
            extent = 359.99 - start
        else:
            extent = v / total * 360
        if extent > 0.01:
            canvas.create_arc(cx - r, cy - r, cx + r, cy + r, start=start, extent=extent,
                              fill=color, outline=BG)
        start += v / total * 360
    lx = H + 6
    ly = 16
    for i, (lab, v) in enumerate(items[:10]):
        color = PALETTE[i % len(PALETTE)]
        canvas.create_rectangle(lx, ly + i * 20, lx + 10, ly + i * 20 + 10, fill=color, outline='')
        txt = '%s  %s（%.1f%%）' % (lab, val_fmt(v), v / total * 100)
        canvas.create_text(lx + 16, ly + i * 20 + 5, text=txt, fill=FG, font=(FONT, 9), anchor='w')


def hbar_rows(parent, items, name_fn, val_fn, val_fmt, color=ACCENT):
    if not items:
        tk.Label(parent, text='没有数据', bg=PANEL, fg=SUB, font=(FONT, 10)).pack(anchor='w', padx=6, pady=6)
        return
    mx = max(val_fn(it) for it in items) or 1e-9
    for it in items:
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill='x', pady=2)
        tk.Label(row, text=name_fn(it), bg=PANEL, fg=FG, font=(FONT, 10),
                 width=26, anchor='w').pack(side='left')
        track_w = 380
        cv = tk.Canvas(row, width=track_w, height=14, bg=PANEL, highlightthickness=0)
        cv.pack(side='left', padx=6)
        w = max(2, val_fn(it) / mx * track_w)
        cv.create_rectangle(0, 1, w, 13, fill=color, outline='')
        tk.Label(row, text=val_fmt(val_fn(it)), bg=PANEL, fg=SUB, font=(FONT, 10),
                 width=14, anchor='e').pack(side='left')


def make_table(parent, columns, rows, widths=None):
    """columns: [(key, 标题, 宽度, 是否右对齐)]"""
    style = ttk.Style(parent)
    style.theme_use('clam')
    style.configure('Treeview', background=PANEL, foreground=FG, fieldbackground=PANEL,
                    bordercolor=BORDER, rowheight=26, font=(FONT, 10))
    style.configure('Treeview.Heading', background='#262633', foreground=SUB, relief='flat', font=(FONT, 10))
    style.map('Treeview', background=[('selected', '#2c3e5e')])
    cols = [c[0] for c in columns]
    tv = ttk.Treeview(parent, columns=cols, show='headings', height=min(len(rows) + 1, 14))
    for key, title, w, right in columns:
        tv.heading(key, text=title)
        tv.column(key, width=w, anchor='e' if right else 'w')
    for r in rows:
        tv.insert('', 'end', values=[r.get(c[0], '') for c in columns])
    tv.pack(fill='x', padx=4, pady=4)
    return tv


class Dashboard(tk.Tk):
    def __init__(self, exe_dir, runtime_dir):
        super().__init__()
        self.exe_dir = exe_dir
        self.runtime_dir = runtime_dir
        self.title(APP_NAME)
        self.geometry('1180x840')
        self.minsize(980, 640)
        self.configure(bg=BG)
        self._busy = False

        head = tk.Frame(self, bg=BG)
        head.pack(fill='x', padx=18, pady=(14, 4))
        tk.Label(head, text='🧮 Tokens 用量看板', bg=BG, fg=FG, font=(FONT, 18, 'bold')).pack(side='left')
        self.meta_var = tk.StringVar(value='正在加载数据……')
        tk.Label(head, textvariable=self.meta_var, bg=BG, fg=SUB, font=(FONT, 10)).pack(side='left', padx=14)
        self.status_var = tk.StringVar(value='')
        tk.Label(head, textvariable=self.status_var, bg=BG, fg=YELLOW, font=(FONT, 10)).pack(side='left', padx=8)
        self.refresh_btn = tk.Button(head, text='🔄 刷新数据', bg=ACCENT, fg='#fff', relief='flat',
                                     font=(FONT, 11), padx=18, pady=6, cursor='hand2',
                                     activebackground='#6f9cf2', command=self.on_refresh)
        self.refresh_btn.pack(side='right')

        self.scroll = ScrollFrame(self)
        self.scroll.pack(fill='both', expand=True, padx=18, pady=6)
        self._build_loading_ui()

        tk.Label(self,
                 text='提示：本看板由本地 CodeBurn 数据 + WorkBuddy 本地日志生成，不上传任何信息。'
                      '供应商识别靠模型名关键字，识别不了的归入「其他」。WorkBuddy 模型对话订阅不限量（¥0.00 正常），'
                      '积分只统计图片生成等按次扣费工具，按 0.05 元/分折算。',
                 bg=BG, fg='#6a6a80', font=(FONT, 9), wraplength=1100, justify='left'
                 ).pack(fill='x', padx=18, pady=(0, 10))

    # ---------- 加载进度 ----------
    def _build_loading_ui(self):
        box = tk.Frame(self.scroll.inner, bg=BG)
        tk.Label(box, text='⏳ 正在加载数据……', bg=BG, fg=FG, font=(FONT, 16, 'bold')).pack(pady=(60, 12))
        self.prog = ttk.Progressbar(box, mode='indeterminate', length=460)
        self.prog.pack(pady=6)
        self.prog.start(14)
        self.load_var = tk.StringVar(value='正在初始化……')
        tk.Label(box, textvariable=self.load_var, bg=BG, fg=SUB, font=(FONT, 10)).pack(pady=4)
        tk.Label(box, text='首次运行、或刚点过「刷新数据」时会慢一些，之后打开都很快。',
                 bg=BG, fg='#6a6a80', font=(FONT, 9)).pack(pady=(2, 30))
        box.pack(fill='x')
        self._loading_box = box

    def _set_load(self, text=None, frac=None, indet=False):
        """只能在主线程调用。frac=0~1 显示真实百分比；indet=True 改回走马灯。"""
        if not self._loading_box.winfo_exists():
            return
        if text is not None:
            self.load_var.set(text)
        if indet:
            self.prog.stop()
            self.prog.configure(mode='indeterminate')
            self.prog.start(14)
        elif frac is not None:
            self.prog.stop()
            self.prog.configure(mode='determinate', maximum=100)
            self.prog['value'] = frac * 100
        self.update_idletasks()

    def set_status(self, msg):
        self.status_var.set(msg)
        self.update_idletasks()

    def load(self):
        """后台线程加载数据，主线程刷新进度条；完成后渲染看板。"""
        if self._busy:
            return
        self._busy = True
        self.refresh_btn.configure(state='disabled', text='正在加载…')
        self.meta_var.set('正在加载数据……')
        for w in self.scroll.inner.winfo_children():
            w.destroy()
        self._build_loading_ui()
        exe_dir = self.exe_dir

        def work():
            def say(msg):
                self.after(0, lambda m=msg: self._set_load(text=m))
            def prog(frac):
                self.after(0, lambda v=frac: self._set_load(frac=v))
            _dbglog('build_data start')
            try:
                data = build_data(exe_dir, status_cb=say, prog_cb=prog)
            except Exception:
                err = traceback.format_exc()
                _dbglog('build_data FAILED')
                self.after(0, lambda: self._load_failed(err))
                return
            _dbglog('build_data done')
            self.after(0, lambda: self._load_done(data))

        threading.Thread(target=work, daemon=True).start()

    def _load_done(self, data):
        self.data = data
        self._busy = False
        self.refresh_btn.configure(state='normal', text='🔄 刷新数据')
        self.render()

    def _load_failed(self, err):
        self._busy = False
        self.refresh_btn.configure(state='normal', text='🔄 刷新数据')
        self.render_error('数据解析失败', err)

    def render_error(self, title, detail):
        for w in self.scroll.inner.winfo_children():
            w.destroy()
        tk.Label(self.scroll.inner, text=title, bg=BG, fg='#e15b8d', font=(FONT, 14, 'bold')).pack(anchor='w', pady=10)
        tk.Label(self.scroll.inner, text=detail[-1500:], bg=BG, fg=SUB, font=('Consolas', 9),
                 justify='left').pack(anchor='w')

    def section(self, title):
        tk.Label(self.scroll.inner, text=title, bg=BG, fg='#c9c9dd', font=(FONT, 14, 'bold')
                 ).pack(anchor='w', pady=(18, 6))
        return tk.Frame(self.scroll.inner, bg=BG)

    def panel(self, parent, **kw):
        f = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1, **kw)
        return f

    def render(self):
        for w in self.scroll.inner.winfo_children():
            w.destroy()
        d = self.data
        if 'error' in d:
            self.render_error(d['error'], '请先确认本程序文件夹里有 usage.json（点「刷新数据」可自动生成）。')
            self.meta_var.set('数据缺失')
            return
        self.meta_var.set('数据来源：CodeBurn 本地统计 + WorkBuddy 本地日志 · 生成时间：%s（北京时间） · 汇率 1 美元≈¥7.1' % d['generated'])
        self.set_status('')

        # 汇总卡
        row = tk.Frame(self.scroll.inner, bg=BG)
        for c in d['cards']:
            make_card(row, c['label'], c['main'], c['sub'])
        row.pack(fill='x', pady=(6, 0))
        row2 = tk.Frame(self.scroll.inner, bg=BG)
        for c in d['region_cards']:
            make_card(row2, c['label'], c['main'], c['sub'], main_color=GREEN)
        row2.pack(fill='x')

        # WorkBuddy 积分
        sec = self.section('🪙 WorkBuddy 积分消耗')
        wb = d['wb']
        day_max_label = wb['day_max'][0] if wb['day_max'][0] else '—'
        cards = [
            ('累计消耗积分', '%.2f' % wb['total'], '全部来自图片生成（%d 次，平均 %.2f 分/张）' % (wb['count'], wb['avg']), GOLD),
            ('单日最多', '%.2f' % (wb['day_max'][1] if wb['day_max'] else 0), day_max_label, GOLD),
            ('模型对话扣费', '0.00', '订阅制不限量（本地日志中 LLM 调用 credit 恒为 0）', GREEN),
            ('积分折合人民币', fmt_rmb(wb['rmb']), '按官方加量包 0.05 元/积分折算，已计入上方总花费', GOLD),
        ]
        for c in cards:
            make_card(sec, c[0], c[1], c[2], main_color=c[3])
        sec.pack(fill='x')
        tk.Label(self.scroll.inner, text='按日消耗明细', bg=BG, fg=SUB, font=(FONT, 10)).pack(anchor='w', pady=(8, 0))
        cv = tk.Canvas(self.scroll.inner, bg=PANEL, highlightthickness=0, height=150)
        cv.pack(fill='x', pady=(0, 4))
        items = [(k[5:], v) for k, v in wb['by_day']]
        every = max(1, math.ceil(len(items) / 20))
        draw_bars(cv, items, color=GOLD, value_fmt=lambda v: '%.1f 分' % v, label_every=every)

        # 图表
        sec = self.section('📊 图表看板（近 30 天）')
        grid = tk.Frame(sec, bg=BG)
        grid.pack(fill='x')
        p1 = self.panel(grid)
        p1.pack(side='left', fill='both', expand=True, padx=(0, 6), pady=4)
        tk.Label(p1, text='📈 每日花费趋势（柱=元，线=tokens 万）', bg=PANEL, fg='#c9c9dd', font=(FONT, 11)).pack(anchor='w', padx=10, pady=(8, 0))
        c1 = tk.Canvas(p1, bg=PANEL, highlightthickness=0, height=230)
        c1.pack(fill='both', expand=True, padx=6, pady=(0, 8))
        self.after_idle(lambda: draw_bar_line(c1, d['chart']['labels'], d['chart']['cost'],
                                              [t / 1e4 for t in d['chart']['tokens']]))

        p2 = self.panel(grid)
        p2.pack(side='left', fill='both', expand=True, padx=(6, 0), pady=4)
        tk.Label(p2, text='🏢 供应商花费占比', bg=PANEL, fg='#c9c9dd', font=(FONT, 11)).pack(anchor='w', padx=10, pady=(8, 0))
        c2 = tk.Canvas(p2, bg=PANEL, highlightthickness=0, height=230)
        c2.pack(fill='both', expand=True, padx=6, pady=(0, 8))
        self.after_idle(lambda: draw_pie(c2, d['vendors']))

        grid2 = tk.Frame(sec, bg=BG)
        grid2.pack(fill='x')
        p3 = self.panel(grid2)
        p3.pack(side='left', fill='both', expand=True, padx=(0, 6), pady=4)
        tk.Label(p3, text='🖥️ 各客户端花费（人民币）', bg=PANEL, fg='#c9c9dd', font=(FONT, 11)).pack(anchor='w', padx=10, pady=(8, 0))
        c3 = tk.Canvas(p3, bg=PANEL, highlightthickness=0, height=200)
        c3.pack(fill='both', expand=True, padx=6, pady=(0, 8))
        self.after_idle(lambda: draw_pie(c3, d['clients'], h=200))

        p4 = self.panel(grid2)
        p4.pack(side='left', fill='both', expand=True, padx=(6, 0), pady=4)
        tk.Label(p4, text='🧩 Tokens 构成（万）', bg=PANEL, fg='#c9c9dd', font=(FONT, 11)).pack(anchor='w', padx=10, pady=(8, 0))
        c4 = tk.Canvas(p4, bg=PANEL, highlightthickness=0, height=200)
        c4.pack(fill='both', expand=True, padx=6, pady=(0, 8))
        self.after_idle(lambda: draw_pie(c4, [(l, round(v, 1)) for l, v in d['tok_parts']], h=200,
                                         val_fmt=lambda v: '%.1f 万' % v))
        sec.pack(fill='x')

        # 分客户端
        sec = self.section('🖥️ 分客户端统计（点开看每个客户端的明细）')
        for i, g in enumerate(d['by_client']):
            det = d['client_details'][g['key']]
            sub = '%s%s · %d 次调用 · %s tokens · 占 %s%%' % (
                fmt_rmb(det['all_cost_rmb']),
                '（含积分换算 %s）' % fmt_rmb(det['credit_rmb']) if det['credit_amount'] > 0 else '',
                g['calls'], fmt_tok(g['tokens']), det['share'])
            blk = Collapsible(sec, '🖥️ ' + str(g['key']), sub, open_=(i == 0))
            blk.pack(fill='x', pady=4)
            self._fill_detail(blk.body, det)
        sec.pack(fill='x')

        # 分供应商
        sec = self.section('🏢 分供应商统计（点开看每家公司的明细）')
        for i, g in enumerate(d['by_vendor']):
            det = d['vendor_details'][g['key']]
            sub = '%s · %d 次调用 · %s tokens · 占 %s%%' % (
                fmt_rmb(det['all_cost_rmb']), g['calls'], fmt_tok(g['tokens']), det['share'])
            blk = Collapsible(sec, '🏢 ' + str(g['key']), sub, open_=(i == 0))
            blk.pack(fill='x', pady=4)
            self._fill_detail(blk.body, det)
        sec.pack(fill='x')

        # 项目 Top10
        sec = self.section('📁 项目花费排行（近 30 天 Top 10）')
        p = self.panel(sec)
        rows = [{'project': short_path(pr.get('Project')), 'cost': fmt_usd(pr.get('Cost (USD)')),
                 'calls': pr.get('API Calls'), 'sessions': pr.get('Sessions'),
                 'share': '%s%%' % pr.get('Share (%)')} for pr in d['projects']]
        make_table(p, [('project', '项目', 300, False), ('cost', '花费', 110, True),
                       ('calls', '调用次数', 90, True), ('sessions', '会话数', 80, True),
                       ('share', '占比', 90, True)], rows)
        p.pack(fill='x')
        sec.pack(fill='x')

        # 工具排行
        sec = self.section('🔧 工具调用排行')
        p = self.panel(sec)
        hbar_rows(p, d['tools'], lambda t: str(t.get('Tool')), lambda t: float(t.get('Calls') or 0),
                  lambda v: '%g 次' % v, color=ACCENT)
        p.pack(fill='x')
        sec.pack(fill='x')

    def _fill_detail(self, body, det):
        tk.Label(body, text='🤖 模型用量', bg=PANEL, fg=SUB, font=(FONT, 10)).pack(anchor='w', pady=(4, 2))
        rows = [{'model': r['model'], 'vendor': r['vendor'], 'cost': r['cost'], 'calls': r['calls'],
                 'tokens': r['tokens'], 'share': r['share']} for r in det['rows']]
        make_table(body, [('model', '模型', 240, False), ('vendor', '供应商', 130, False),
                          ('cost', '花费', 100, True), ('calls', '调用次数', 90, True),
                          ('tokens', '总 tokens', 110, True), ('share', '占比', 110, True)], rows)
        tk.Label(body, text='📈 每日花费', bg=PANEL, fg=SUB, font=(FONT, 10)).pack(anchor='w', pady=(10, 2))
        cv = tk.Canvas(body, bg=PANEL, highlightthickness=0, height=150)
        cv.pack(fill='x')
        items = [(k[5:], v) for k, v in det['daily_rmb']]
        every = max(1, math.ceil(len(items) / 20))
        draw_bars(cv, items, color=GREEN, value_fmt=lambda v: '¥%.2f' % v, label_every=every)

    def on_refresh(self):
        if self._busy or not self.runtime_dir:
            return
        self.refresh_btn.configure(state='disabled', text='正在刷新…')

        def work():
            def log(msg):
                self.after(0, lambda m=msg: self.set_status(m))
            ok, err = collect(self.exe_dir, self.runtime_dir, log)
            if ok:
                self.after(0, self.load)
            else:
                self.after(0, lambda: self._refresh_failed(err))

        threading.Thread(target=work, daemon=True).start()

    def _refresh_failed(self, err):
        self._busy = False
        self.refresh_btn.configure(state='normal', text='🔄 刷新数据')
        self.set_status('刷新失败')
        messagebox.showerror(APP_NAME, '统计失败：\n' + (err or '未知错误'))


def main():
    exe_dir, meipass = find_dirs()
    _dbglog('main start exe_dir=%s' % exe_dir)
    # 窗口立即显示 + 加载进度条，运行环境准备在后台线程进行
    app = Dashboard(exe_dir, None)
    _dbglog('Dashboard created (window exists)')
    app.set_status('正在检查运行环境……')

    def log(msg):
        app.after(0, lambda m=msg: app._set_load(text=m))

    def prog(frac):
        app.after(0, lambda v=frac: app._set_load(frac=v))

    def work():
        try:
            runtime_dir = ensure_runtime(exe_dir, meipass, log, prog_cb=prog)
        except Exception as exc:
            print('ensure_runtime failed:', repr(exc))
            # 默认参数绑定 exc：except 块结束后异常变量会被删除，闭包延迟引用会 NameError
            app.after(0, lambda e=exc: messagebox.showerror(APP_NAME, '运行环境准备失败：\n%s' % e))
            return
        app.runtime_dir = runtime_dir
        _dbglog('ensure_runtime done')
        app.after(0, app.load)

    threading.Thread(target=work, daemon=True).start()
    app.mainloop()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        tb = traceback.format_exc()
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard_error.log'),
                      'w', encoding='utf-8') as f:
                f.write(tb)
        except OSError:
            pass
        try:
            import tkinter as _tk
            r = _tk.Tk()
            r.withdraw()
            messagebox.showerror(APP_NAME, '程序出错：\n%s\n\n详情已写入 dashboard_error.log' % tb[-800:])
            r.destroy()
        except Exception:
            pass
