#!/usr/bin/env python3
"""mcp_bench.py — what the MCP server (tools/wavemcp.py) saves an AI agent: the same waveform tasks solved by an agent
with the wavelens MCP tools and without them (the shell and the wavelens command-line tools only), tokens counted.

The tasks have answers known in advance: two on the APB example (a 3.6 KB VCD, make example EX=apb), one on the FSM
example's FST (enum state names in the dump, make example EX=fsm) and five on a generated dump (bench.vcd, 40 000 cycles, ~170 signals, ~4 MB: a stream with frames and backpressure, a FIFO level, a
req / ack handshake with one late ack, an error pulse; gen_vcd() knows the answers). An answer is the last
"ANSWER: key=value …" line of the agent's reply.

  python3 -I tests/mcp_bench.py --build out --scripted          # each task through the MCP tools by a script: answers
                                                                # checked, the bytes the tools return (no agent, no cost)
  python3 -I tests/mcp_bench.py --build out --agent claude --model sonnet --jobs 4   # agents: costs tokens
  python3 -I tests/mcp_bench.py --build out --agent codex --tasks b3,b4 --reps 2
  python3 -I tests/mcp_bench.py --build out --report            # the table of every run so far (BUILD/mcp_bench/runs.jsonl)

An agent run: a fresh directory under BUILD/mcp_bench/runs/ with the task's files, the same prompt in both modes (it
names the wavelens command-line tools), the MCP server attached or not; claude -p (--strict-mcp-config, no settings,
the tools Bash Read Grep Glob Write) or codex exec (sandbox workspace-write). Tokens: claude's usage (input + cache
writes + cache reads + output) and cost; codex's turn usage (input incl. cached + output).
"""
import argparse, concurrent.futures as cf, json, os, random, re, shutil, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
SERVER = os.path.join(ROOT, 'tools', 'wavemcp.py')
CLOCK_NS, CYCLES = 10, 40000


# ---------------- the generated dump ----------------
def gen_vcd(path, cycles=CYCLES, seed=7):
    """bench.vcd: clk 100 MHz (rises at 5 + 10c ns), registered signals change on the rising edge; -> the answers.
    tb.dut: an AXI-Stream-like source (s_tvalid s_tready s_tdata s_tlast; valid holds until a handshake), a FIFO level
    (fifo.count: +1 a handshake, -1 the sink), a req / ack handshake (ctl.req a one-cycle pulse, ctl.ack 1..4 cycles
    later; one ack 7 cycles late), an error pulse (err), a state (ctl.state), counters and 150 registers that rarely
    change."""
    R = random.Random(seed)
    sigs = [('tb', 'clk', 1), ('tb', 'rst_n', 1),
            ('tb.dut', 's_tvalid', 1), ('tb.dut', 's_tready', 1), ('tb.dut', 's_tlast', 1), ('tb.dut', 's_tdata', 32),
            ('tb.dut', 'err', 1), ('tb.dut.fifo', 'count', 8), ('tb.dut.fifo', 'full', 1), ('tb.dut.fifo', 'empty', 1),
            ('tb.dut.ctl', 'req', 1), ('tb.dut.ctl', 'ack', 1), ('tb.dut.ctl', 'state', 2),
            ('tb.dut.perf', 'cyc_cnt', 16), ('tb.dut.perf', 'beat_cnt', 16), ('tb.dut.perf', 'half_cnt', 16), ('tb.dut.perf', 'lfsr', 16)]
    sigs += [('tb.dut.regs', f'r{i:03d}', 16) for i in range(150)]
    code = {}
    def ident(i):
        s, i = '', i + 1
        while i:
            i, r = divmod(i - 1, 94)
            s += chr(33 + r)
        return s
    for i, (sc, n, _) in enumerate(sigs):
        code[sc + '.' + n] = ident(i)
    width = {sc + '.' + n: w for sc, n, w in sigs}
    out = ['$date bench $end', '$version mcp_bench.py $end', '$timescale 1ns $end']
    open_sc = []
    for sc, n, w in sigs:
        parts = sc.split('.')
        while open_sc and open_sc != parts[:len(open_sc)]:
            out.append('$upscope $end'); open_sc.pop()
        while len(open_sc) < len(parts):
            open_sc.append(parts[len(open_sc)]); out.append(f'$scope module {open_sc[-1]} $end')
        out.append(f'$var wire {w} {code[sc + "." + n]} {n}' + (f' [{w - 1}:0]' if w > 1 else '') + ' $end')
    out += ['$upscope $end'] * len(open_sc) + ['$enddefinitions $end']
    cur = {}
    def val(p, v):
        w = width[p]
        return f'{v}{code[p]}' if w == 1 else f'b{format(v, "b")} {code[p]}'
    out.append('#0')
    out.append('$dumpvars')
    st = {p: 0 for p in width}
    st['tb.dut.fifo.empty'] = 1
    st['tb.dut.perf.lfsr'] = 0xACE1
    for p, v in st.items():
        out.append(val(p, v))
    out.append('$end')
    cur.update(st)
    truth = {'mhz': 100, 'reset_release_ns': None, 'frames': 0, 'reqs': 0, 'violations': 0, 'first_req_ns': None,
             'err_ns': None, 'fifo_at_err': None, 'fifo_max': 0, 'fifo_max_ns': None}
    beats_left, n_req, req_wait, bad_req = 0, 0, None, 150
    c_err = int(cycles * 0.79)
    pending_done = False
    for c in range(cycles):
        t_rise = 5 + CLOCK_NS * c
        old = dict(cur)
        new = dict(cur)
        new['tb.clk'] = 1
        if c == 10:
            new['tb.rst_n'] = 1
            truth['reset_release_ns'] = t_rise
        run = old['tb.rst_n'] == 1
        hs = old['tb.dut.s_tvalid'] and old['tb.dut.s_tready']
        if run:
            if hs:
                beats_left -= 1
                new['tb.dut.s_tdata'] = (old['tb.dut.s_tdata'] + 1) & 0xFFFFFFFF
                new['tb.dut.perf.beat_cnt'] = (old['tb.dut.perf.beat_cnt'] + 1) & 0xFFFF
                if old['tb.dut.s_tlast']:
                    truth['frames'] += 1
                    pending_done = True
            if beats_left > 0:
                hold = old['tb.dut.s_tvalid'] and not hs
                new['tb.dut.s_tvalid'] = 1 if hold else int(R.random() > 0.1)
            else:
                new['tb.dut.s_tvalid'] = 0
                if R.random() < 0.03:
                    beats_left = R.randint(4, 64)
                    new['tb.dut.s_tvalid'] = int(R.random() > 0.1)
            new['tb.dut.s_tlast'] = int(new['tb.dut.s_tvalid'] and beats_left == 1)
            new['tb.dut.s_tready'] = int(R.random() < 0.8)
            cnt = old['tb.dut.fifo.count'] + (1 if hs else 0)
            if cnt > 0 and R.random() < 0.75:
                cnt -= 1
            cnt = min(cnt, 255)
            new['tb.dut.fifo.count'] = cnt
            new['tb.dut.fifo.empty'] = int(cnt == 0)
            new['tb.dut.fifo.full'] = int(cnt >= 16)
            if cnt > truth['fifo_max']:
                truth['fifo_max'], truth['fifo_max_ns'] = cnt, t_rise
            new['tb.dut.ctl.state'] = 3 if pending_done else 0 if beats_left <= 0 else 1 if new['tb.dut.s_tvalid'] else 2
            pending_done = False
            # req / ack
            new['tb.dut.ctl.req'] = 0
            new['tb.dut.ctl.ack'] = 0
            if req_wait is not None:
                req_wait -= 1
                if req_wait == 0:
                    new['tb.dut.ctl.ack'] = 1
                    req_wait = None
            elif not old['tb.dut.ctl.ack'] and R.random() < 0.02:
                n_req += 1
                new['tb.dut.ctl.req'] = 1
                req_wait = 7 if n_req == bad_req else R.randint(1, 4)
                if n_req == bad_req:
                    truth['violations'] += 1
                    truth['first_req_ns'] = truth['first_req_ns'] or t_rise
            new['tb.dut.err'] = int(c == c_err)
            if c == c_err:
                truth['err_ns'], truth['fifo_at_err'] = t_rise, [old['tb.dut.fifo.count'], cnt]
        new['tb.dut.perf.cyc_cnt'] = c & 0xFFFF
        new['tb.dut.perf.half_cnt'] = (c // 2) & 0xFFFF
        l = old['tb.dut.perf.lfsr']
        new['tb.dut.perf.lfsr'] = ((l >> 1) | (((l ^ (l >> 2) ^ (l >> 3) ^ (l >> 5)) & 1) << 15)) & 0xFFFF
        for i in range(150):
            if R.random() < 0.001:
                new[f'tb.dut.regs.r{i:03d}'] = R.randrange(1 << 16)
        lines = [val(p, v) for p, v in new.items() if v != cur[p]]
        out.append(f'#{t_rise}')
        out.extend(lines)
        cur = new
        out.append(f'#{t_rise + 5}')
        out.append(val('tb.clk', 0))
        cur['tb.clk'] = 0
    truth['reqs'] = n_req
    with open(path, 'w', encoding='ascii', newline='\n') as f:
        f.write('\n'.join(out) + '\n')
    return truth


# ---------------- the tasks ----------------
APB_SV = ['examples/apb/apb_tb.sv', 'examples/apb/apb.sva']
APB_TRUTH = {'assertion': 'apb_demo_no_wait', 'times_ns': [105, 115], 'wait_cycles': 2, 'rdata': 0xCAFE0001,
             'slverr_ns': 155, 'slverr_addr': 0x40}
TASKS = [
    {'id': 'a1', 'dump': 'apb', 'files': APB_SV,
     'task': 'Check the SystemVerilog assertions of apb.sva (apb_tb.sv declares the package apb_pkg it imports) over apb.vcd, '
             'bound in the scope apb_tb. Which assertion fails, and at which clock-edge times (ns)?',
     'answer': 'assertion=<name> times_ns=<t1>,<t2>,...'},
    {'id': 'a2', 'dump': 'apb',
     'task': 'In apb.vcd (an APB3 bus at apb_tb, clock PCLK): how many clock cycles of wait state are there (PSEL && PENABLE && '
             '!PREADY sampled on the rising edge), what data does the read return (PRDATA when the read completes), and at what '
             'time (ns) does PSLVERR rise, with which PADDR?',
     'answer': 'wait_cycles=<n> rdata=<hex> slverr_ns=<t> slverr_addr=<hex>'},
    {'id': 'b1', 'dump': 'bench',
     'task': 'bench.vcd is a simulation dump. What is the frequency of its clock (MHz), and at what time (ns) is the reset released?',
     'answer': 'mhz=<n> reset_release_ns=<t>'},
    {'id': 'b2', 'dump': 'bench',
     'task': 'bench.vcd: tb.dut has a stream interface s_tvalid / s_tready / s_tdata / s_tlast (AXI-Stream rules, clock tb.clk). '
             'How many complete frames are transferred (handshakes with s_tlast)?',
     'answer': 'frames=<n>'},
    {'id': 'b3', 'dump': 'bench',
     'task': 'bench.vcd: the spec says every request (tb.dut.ctl.req, a one-cycle pulse) is acknowledged (tb.dut.ctl.ack) 1 to 4 '
             'clock cycles (tb.clk) after it. How many requests are there, how many violate the spec, and at what time (ns) does '
             'the first violating request rise?',
     'answer': 'reqs=<n> violations=<n> first_req_ns=<t>'},
    {'id': 'b4', 'dump': 'bench',
     'task': 'bench.vcd: when (ns) does tb.dut.err first go high, and what is the FIFO level tb.dut.fifo.count at that moment?',
     'answer': 'err_ns=<t> fifo_count=<n>'},
    {'id': 'b5', 'dump': 'bench',
     'task': 'bench.vcd: what is the highest value tb.dut.fifo.count reaches, and when (ns) does it first reach it?',
     'answer': 'max=<n> at_ns=<t>'},
    {'id': 'c1', 'dump': 'fsm',
     'task': 'fsm.fst is a Verilator FST dump (clock fsm_tb.clk). The state register of the UART receiver, fsm_tb.u_rx.state, is an '
             'enum. Which states (by name) does it go through, in order, over the whole dump? How many clock cycles does it stay in '
             'its first DATA state, and at what time (ns) does it enter ERROR?',
     'answer': 'states=<NAME,NAME,...> data_cycles=<n> error_ns=<t>'},
]
FSM_TRUTH = {'states': ['IDLE', 'START', 'DATA', 'STOP', 'IDLE', 'START', 'DATA', 'STOP', 'ERROR', 'IDLE'], 'data_cycles': 32, 'error_ns': 905}


def parse_answer(text):
    """The last ANSWER: line -> {key: value text}."""
    lines = [l for l in (text or '').splitlines() if 'ANSWER:' in l]
    if not lines:
        return {}
    body = lines[-1].split('ANSWER:', 1)[1].strip().strip('`*')
    return {k.lower(): v.strip().strip('`*,;') for k, v in re.findall(r'(\w+)\s*=\s*([^\s]+)', body)}


def num(s):
    s = str(s).lower().replace('_', '').replace('ns', '')
    s = re.sub(r"^\d*'h", '0x', s)
    try:
        return int(s, 0) if re.match(r'-?0[xb]', s) else float(s)
    except ValueError:
        return None


def near(got, want, tol=CLOCK_NS):
    g = num(got)
    return g is not None and abs(g - want) <= tol


def check(task, ans, truth):
    """The answer against the truth -> (passed, why)."""
    i, T = task['id'], truth
    try:
        if i == 'a1':
            ts = [num(x) for x in ans.get('times_ns', '').split(',') if x]
            ok = ans.get('assertion') == APB_TRUTH['assertion'] and len(ts) == 2 and all(abs(a - b) <= CLOCK_NS for a, b in zip(sorted(ts), APB_TRUTH['times_ns']))
        elif i == 'a2':
            hx = lambda k: num('0x' + re.sub(r"^(0x|\d*'h)", '', ans.get(k, '').lower()))
            ok = (num(ans.get('wait_cycles')) == APB_TRUTH['wait_cycles'] and hx('rdata') == APB_TRUTH['rdata']
                  and near(ans.get('slverr_ns'), APB_TRUTH['slverr_ns']) and hx('slverr_addr') == APB_TRUTH['slverr_addr'])
        elif i == 'b1':
            ok = num(ans.get('mhz')) == 100 and near(ans.get('reset_release_ns'), T['reset_release_ns'])
        elif i == 'b2':
            ok = num(ans.get('frames')) == T['frames']
        elif i == 'b3':
            ok = num(ans.get('reqs')) == T['reqs'] and num(ans.get('violations')) == T['violations'] and near(ans.get('first_req_ns'), T['first_req_ns'])
        elif i == 'b4':
            ok = near(ans.get('err_ns'), T['err_ns']) and num(ans.get('fifo_count')) in T['fifo_at_err']
        elif i == 'c1':
            st = [x.strip().upper() for x in ans.get('states', '').split(',') if x.strip()]
            ok = (st in (FSM_TRUTH['states'], FSM_TRUTH['states'][1:]) and abs(num(ans.get('data_cycles')) - FSM_TRUTH['data_cycles']) <= 1
                  and near(ans.get('error_ns'), FSM_TRUTH['error_ns']))
        elif i == 'b5':
            ok = num(ans.get('max')) == T['fifo_max'] and near(ans.get('at_ns'), T['fifo_max_ns'])
        else:
            ok = False
    except (TypeError, ValueError, AttributeError):
        ok = False
    return ok


# ---------------- inputs ----------------
def prepare(build):
    """BUILD/mcp_bench/: bench.vcd (made once) and its answers; the APB dump of make example EX=apb -> (dir, truth)."""
    d = os.path.join(build, 'mcp_bench')
    os.makedirs(d, exist_ok=True)
    vcd, tj = os.path.join(d, 'bench.vcd'), os.path.join(d, 'truth.json')
    if not (os.path.isfile(vcd) and os.path.isfile(tj)):
        truth = gen_vcd(vcd)
        with open(tj, 'w') as f:
            json.dump(truth, f, indent=1)
    with open(tj) as f:
        truth = json.load(f)
    ex = {'apb': os.path.join(build, 'examples', 'apb', 'apb.vcd'), 'fsm': os.path.join(build, 'examples', 'fsm', 'fsm.fst')}
    for k, f in ex.items():
        if not os.path.isfile(f):
            sys.exit(f'mcp_bench: no {f}: make example EX={k} BUILD={build} first')
    return d, truth, {'bench': vcd, **ex}


# ---------------- the scripted solutions: the MCP tools without an agent ----------------
def scripted(dumps, truth):
    import wavemcp as W
    calls = []
    def c(tool, **a):
        text, err = W.call(tool, a)
        calls.append((tool, len(text)))
        if err:
            raise RuntimeError(f'{tool}: {text}')
        return json.loads(text)
    apb, bench = dumps['apb'], dumps['bench']
    sols = {}
    r = c('sva_check', dump=apb, files=[os.path.join(ROOT, f) for f in APB_SV], scope='apb_tb')
    f = r['failed'][0]
    sols['a1'] = f"assertion={f['name']} times_ns={','.join(str(x[1]) for x in f['failures'])}"
    w = c('wave_find', dump=apb, expr='PSEL && PENABLE && !PREADY', scope='apb_tb')
    rd = c('wave_find', dump=apb, expr='PSEL && PENABLE && PREADY && !PWRITE', scope='apb_tb')
    v = c('wave_values', dump=apb, signals=['apb_tb.PRDATA'], at=rd['rows'][0][1], side='before', radix='hex')
    e = c('wave_find', dump=apb, signal='apb_tb.PSLVERR', edge='rise')
    a = c('wave_values', dump=apb, signals=['apb_tb.PADDR'], at=e['times'][0], radix='hex')
    sols['a2'] = f"wait_cycles={w['matches']} rdata={v['rows'][0][1]} slverr_ns={e['times'][0]} slverr_addr={a['rows'][0][1]}"
    i = c('wave_info', dump=bench)
    rst = c('wave_find', dump=bench, signal='tb.rst_n', edge='rise')
    sols['b1'] = f"mhz={i['clocks'][0]['mhz']:g} reset_release_ns={rst['times'][0]}"
    fr = c('wave_find', dump=bench, expr='s_tvalid && s_tready && s_tlast', scope='tb.dut', limit=1)
    sols['b2'] = f"frames={fr['matches']}"
    sv = c('sva_check', dump=bench, scope='tb.dut.ctl', source='req_ack: assert property (@(posedge clk) req |-> ##[1:4] ack);')
    nreq = c('wave_stats', dump=bench, signals=['tb.dut.ctl.req'])['signals']['tb.dut.ctl.req']['rises']
    f = sv['failed'][0]
    sols['b3'] = f"reqs={nreq} violations={f['stats']['fail']} first_req_ns={f['failures'][0][3] - CLOCK_NS}"   # req seen at that edge
    er = c('wave_find', dump=bench, signal='tb.dut.err', edge='rise')
    cnt = c('wave_values', dump=bench, signals=['tb.dut.fifo.count'], at=er['times'][0], radix='dec')
    sols['b4'] = f"err_ns={er['times'][0]} fifo_count={cnt['rows'][0][1]}"
    s = c('wave_stats', dump=bench, signals=['tb.dut.fifo.count'], radix='dec')['signals']['tb.dut.fifo.count']
    mx = c('wave_find', dump=bench, signal='tb.dut.fifo.count', value=s['max'], limit=1)
    sols['b5'] = f"max={s['max']} at_ns={mx['rows'][0][0]}"
    ch = c('wave_changes', dump=dumps['fsm'], signals=['fsm_tb.u_rx.state'])['signals']['fsm_tb.u_rx.state']
    seq = [ch['initial']] + [v for _, v in ch['changes']]
    t_data = next(t for t, v in ch['changes'] if v == 'DATA')
    t_next = next(t for t, v in ch['changes'] if t > t_data)
    sols['c1'] = f"states={','.join(seq)} data_cycles={(t_next - t_data) // CLOCK_NS} error_ns={next(t for t, v in ch['changes'] if v == 'ERROR')}"
    rows = []
    for t in TASKS:
        ans = parse_answer('ANSWER: ' + sols[t['id']])
        rows.append((t['id'], check(t, ans, truth), sols[t['id']]))
    return rows, calls


# ---------------- agents ----------------
PROMPT = """You are analysing simulation waveforms. The files are in the current directory: {files}.
The wavelens project at {root} has command-line tools for dumps: python3 {root}/tools/vcd2wavedrom.py --help (a window of a dump as
WaveJSON), {root}/bin/linux-x86_64/sva --help (SystemVerilog assertions evaluated over a dump), python3 {root}/tools/mkconfig.py --help.
{extra}
Task: {task}

Work it out from the dump; do not guess. End your reply with exactly one line:
ANSWER: {answer}"""


def workdir(base, name, task, dumps):
    d = os.path.join(base, 'runs', name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    files = []
    src = dumps[task['dump']]
    os.symlink(src, os.path.join(d, os.path.basename(src)))
    files.append(os.path.basename(src))
    for f in task.get('files', []):
        shutil.copy(os.path.join(ROOT, f), d)
        files.append(os.path.basename(f))
    return d, files


def keep(d, p):
    """The agent's events and stderr next to its files (transcript.jsonl, stderr.txt): what it did, read later."""
    with open(os.path.join(d, 'transcript.jsonl'), 'w') as f:
        f.write(p.stdout)
    with open(os.path.join(d, 'stderr.txt'), 'w') as f:
        f.write(p.stderr)


def run_claude(d, prompt, mcp, model, timeout):
    cfg = os.path.join(d, '.mcp.json')
    with open(cfg, 'w') as f:
        json.dump({'mcpServers': {'wavelens': {'command': sys.executable, 'args': ['-I', SERVER]}} if mcp else {}}, f)
    cmd = ['claude', '-p', prompt, '--output-format', 'stream-json', '--verbose', '--strict-mcp-config', '--mcp-config', cfg,
           '--setting-sources', '', '--no-session-persistence', '--tools', 'Bash,Read,Grep,Glob,Write',
           '--allowedTools', 'Bash Read Grep Glob Write' + (' mcp__wavelens' if mcp else '')]
    if model:
        cmd += ['--model', model]
    t0 = time.time()
    p = subprocess.run(cmd, cwd=d, capture_output=True, text=True, timeout=timeout)
    keep(d, p)
    res, calls, tools = {}, [], []
    for l in p.stdout.splitlines():
        try:
            e = json.loads(l)
        except ValueError:
            continue
        if e.get('type') == 'system' and e.get('subtype') == 'init':
            tools = e.get('tools', [])
        elif e.get('type') == 'assistant':
            calls += [c['name'] for c in e['message'].get('content', []) if c.get('type') == 'tool_use']
        elif e.get('type') == 'result':
            res = e
    u = res.get('usage') or {}
    return {'text': res.get('result', ''), 'secs': round(time.time() - t0, 1), 'turns': res.get('num_turns'),
            'cost_usd': res.get('total_cost_usd'), 'input': u.get('input_tokens', 0), 'cache_write': u.get('cache_creation_input_tokens', 0),
            'cache_read': u.get('cache_read_input_tokens', 0), 'output': u.get('output_tokens', 0), 'calls': calls,
            'mcp_tools': sum(t.startswith('mcp__wavelens') for t in tools), 'rc': p.returncode, 'stderr': p.stderr[-500:]}


def run_codex(d, prompt, mcp, model, timeout):
    cmd = ['codex', 'exec', '--json', '--skip-git-repo-check', '--ephemeral', '-s', 'workspace-write', '-C', d]
    if mcp:
        cmd += ['-c', f'mcp_servers.wavelens.command="{sys.executable}"', '-c', f'mcp_servers.wavelens.args=["-I","{SERVER}"]']
    if model:
        cmd += ['-m', model]
    cmd.append(prompt)
    t0 = time.time()
    p = subprocess.run(cmd, cwd=d, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    keep(d, p)
    text, calls, inp, cached, out, turns = '', [], 0, 0, 0, 0
    for l in p.stdout.splitlines():
        try:
            e = json.loads(l)
        except ValueError:
            continue
        it = e.get('item') or {}
        if e.get('type') == 'item.completed':
            if it.get('type') == 'agent_message':
                text = it.get('text', '')
            elif it.get('type') == 'mcp_tool_call':
                calls.append('mcp:' + it.get('tool', '') + (' (error)' if it.get('error') else ''))
            elif it.get('type') == 'command_execution':
                calls.append('shell')
        elif e.get('type') == 'turn.completed':
            u = e.get('usage') or {}
            inp += u.get('input_tokens', 0); cached += u.get('cached_input_tokens', 0); out += u.get('output_tokens', 0)
            turns += 1
    return {'text': text, 'secs': round(time.time() - t0, 1), 'turns': turns, 'cost_usd': None, 'input': inp - cached,
            'cache_write': 0, 'cache_read': cached, 'output': out, 'calls': calls, 'rc': p.returncode, 'stderr': p.stderr[-500:]}


def total(r):
    """Every token the model read or wrote, the context read again from the cache included."""
    return r['input'] + r['cache_write'] + r['cache_read'] + r['output']


def fresh(r):
    """The tokens that were new: input not read from the cache, cache writes, output (what the price mostly follows;
    a cache read costs about a tenth of an input token)."""
    return r['input'] + r['cache_write'] + r['output']


def schema_size():
    """Characters of the server's tool list (its JSON): the label of a version of the tools in the runs."""
    import wavemcp
    return len(json.dumps(wavemcp.listing(), separators=(',', ':')))


def one(base, dumps, truth, agent, model, mode, task, rep, timeout):
    name = f'{agent}-{mode}-{task["id"]}-{rep}'
    d, files = workdir(base, name, task, dumps)
    extra = {'mcp': 'The wavelens MCP server is attached (tools wave_info, wave_signals, wave_values, wave_changes, wave_sample, '
                    'wave_find, wave_stats, sva_check, wave_page): prefer it.',
             'call': f'The same tools answer from the shell in short JSON: python3 {ROOT}/tools/wavemcp.py --list (the tools: wave_info, '
                     'wave_signals, wave_values, wave_changes, wave_sample, wave_find, wave_stats, sva_check, wave_page; their '
                     f'arguments), python3 {ROOT}/tools/wavemcp.py --call TOOL \'{{"dump": "x.vcd", ...}}\': prefer them.'}.get(mode, '')
    prompt = PROMPT.format(files=', '.join(files), root=ROOT, extra=extra, task=task['task'], answer=task['answer'])
    try:
        r = (run_claude if agent == 'claude' else run_codex)(d, prompt, mode == 'mcp', model, timeout)   # call: the shell only
    except subprocess.TimeoutExpired:
        r = {'text': '', 'secs': timeout, 'turns': None, 'cost_usd': None, 'input': 0, 'cache_write': 0, 'cache_read': 0,
             'output': 0, 'calls': [], 'rc': 'timeout', 'stderr': ''}
    ans = parse_answer(r['text'])
    r.update(agent=agent, model=model or 'default', mode=mode, task=task['id'], rep=rep, answer=ans, schema=schema_size(),
             ok=check(task, ans, truth), tokens=total(r), when=time.strftime('%Y-%m-%d %H:%M'))
    r['text'] = r['text'][-1500:]
    return r


def pct(a, b):
    return f'{100 * (1 - b / a):+.0f}%' if a else '–'


def table(rs, mode):
    """Markdown rows: per task the median of the runs without the tools (cli) and with them (mode), then the sums."""
    import statistics as S
    out = ['| task | all tokens: without → with | saved | new tokens: without → with | saved | correct | calls | seconds |',
           '|---|---:|---:|---:|---:|---|---|---|']
    tot = {(m, f): 0 for m in ('cli', mode) for f in ('all', 'new')}
    for t in TASKS:
        g = {m: [r for r in rs if r['task'] == t['id'] and r['mode'] == m] for m in ('cli', mode)}
        if not g['cli'] or not g[mode]:
            continue
        md = lambda m, f: S.median(f(r) for r in g[m])
        al, nw = {m: md(m, total) for m in g}, {m: md(m, fresh) for m in g}
        for m in g:
            tot[m, 'all'] += al[m]
            tot[m, 'new'] += nw[m]
        ok = ' / '.join(f"{sum(r['ok'] for r in g[m])}/{len(g[m])}" for m in g)
        nc = ' / '.join(f"{md(m, lambda r: len(r['calls'])):g}" for m in g)
        sec = ' / '.join(f"{md(m, lambda r: r['secs']):.0f}" for m in g)
        out.append(f"| {t['id']} | {al['cli']:,.0f} → {al[mode]:,.0f} | {pct(al['cli'], al[mode])} | {nw['cli']:,.0f} → {nw[mode]:,.0f} | "
                   f"{pct(nw['cli'], nw[mode])} | {ok} | {nc} | {sec} |")
    if tot['cli', 'all']:
        out.append(f"| **sum** | **{tot['cli', 'all']:,.0f} → {tot[mode, 'all']:,.0f}** | **{pct(tot['cli', 'all'], tot[mode, 'all'])}** | "
                   f"**{tot['cli', 'new']:,.0f} → {tot[mode, 'new']:,.0f}** | **{pct(tot['cli', 'new'], tot[mode, 'new'])}** | | | |")
    cost = {m: [r['cost_usd'] for r in rs if r['mode'] == m and r.get('cost_usd') is not None] for m in ('cli', mode)}
    if cost['cli'] and cost[mode]:
        out.append(f"\nCost: ${sum(cost['cli']):.2f} for {len(cost['cli'])} runs without, ${sum(cost[mode]):.2f} for {len(cost[mode])} "
                   f"with ({pct(sum(cost['cli']) / len(cost['cli']), sum(cost[mode]) / len(cost[mode]))} per run).")
    return out


def report(rows):
    """Markdown per agent, model and version of the tools (schema size): the runs with the MCP server against the runs
    without it, and the runs of mode "call" (the same tools through wavemcp.py --call in the shell) against them too."""
    out = []
    for key in sorted({(r['agent'], r['model'], r.get('schema', 8354)) for r in rows}):
        rs = [r for r in rows if (r['agent'], r['model'], r.get('schema', 8354)) == key]
        out.append(f'\n### {key[0]} ({key[1]}), tool list {key[2]} characters\n')
        for mode, head in (('mcp', 'With the MCP server'), ('call', 'With the same tools from the shell (`wavemcp.py --call`, no MCP)')):
            if any(r['mode'] == mode for r in rs):
                out += [f'{head}, against the shell and the command-line tools alone:\n'] + table(rs, mode) + ['']
    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build', default=os.environ.get('BUILD') or os.path.join(ROOT, 'out'))
    ap.add_argument('--scripted', action='store_true', help='solve the tasks through the MCP tools by a script (no agent)')
    ap.add_argument('--agent', choices=('claude', 'codex'))
    ap.add_argument('--model')
    ap.add_argument('--modes', default='cli,mcp')
    ap.add_argument('--tasks', help='ids, comma-separated (default: all)')
    ap.add_argument('--reps', type=int, default=1)
    ap.add_argument('--jobs', type=int, default=3)
    ap.add_argument('--timeout', type=int, default=1200)
    ap.add_argument('--report', action='store_true', help='the table of the runs in BUILD/mcp_bench/runs.jsonl')
    a = ap.parse_args()
    base, truth, dumps = prepare(a.build)
    runs = os.path.join(base, 'runs.jsonl')
    if a.scripted:
        rows, calls = scripted(dumps, truth)
        for i, ok, sol in rows:
            print(f"{'ok  ' if ok else 'FAIL'} {i}: {sol}")
        size = {k: os.path.getsize(v) for k, v in dumps.items()}
        print(f'{len(calls)} tool calls, {sum(n for _, n in calls)} characters returned in all; the dumps: '
              + ', '.join(f'{k} {v:,} bytes' for k, v in size.items()))
        return 0 if all(ok for _, ok, _ in rows) else 1
    if a.agent:
        tasks = [t for t in TASKS if not a.tasks or t['id'] in a.tasks.split(',')]
        jobs = [(m, t, r) for r in range(a.reps) for t in tasks for m in a.modes.split(',')]
        with cf.ThreadPoolExecutor(a.jobs) as ex, open(runs, 'a') as log:
            futs = {ex.submit(one, base, dumps, truth, a.agent, a.model, m, t, r, a.timeout): (m, t['id'], r) for m, t, r in jobs}
            for f in cf.as_completed(futs):
                r = f.result()
                log.write(json.dumps(r) + '\n'); log.flush()
                print(f"{r['agent']} {r['mode']:3} {r['task']} #{r['rep']}: {'ok  ' if r['ok'] else 'FAIL'} {r['tokens']:>9,} tokens "
                      f"{len(r['calls']):3} calls {r['secs']:6.0f} s  {r['answer']}", flush=True)
    if a.report or a.agent:
        rows = [json.loads(l) for l in open(runs)] if os.path.isfile(runs) else []
        print(report(rows))
    return 0


if __name__ == '__main__':
    sys.exit(main())
