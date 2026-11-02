#!/usr/bin/env python3
"""Unit 400 console - Station-style web console driven by the Unit 400 digital twin.

Runs next to the twin (../twin, needs your generated unit400_model.py). Python 3 stdlib only.
    python3 u400_console.py [port]          (default 8400)
Browse to http://<host>:8400

Layers
  Mimic model   unit400_twin.Twin       chemistry: temperatures, analysers, H2/N2 flows
  Plant         Plant hydraulics below   real water flows, levels, pumps (as on the plant)
  C300          Loop / Pump classes      PID loops (MAN/AUTO/CAS), devices, interlocks
"""
import json
import math
import os
import pickle
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'twin'))
import unit400_twin as T  # noqa: E402

T.NOISE = False
LAYOUT_FILE = os.path.join(HERE, 'u400_layout.json')
SNAP_DIR = os.path.join(HERE, 'snapshots')

# ------------------------------------------------------------------ tag dictionary
DESC = {
    '04FIC400': 'Unit feed flow (octanal) – real water flow on plant',
    '04FIC401': 'Heat supply to E-401 feed preheater',
    '04TIC401': 'Feed temperature after E-401 (= 04TI407), cascades to 04FIC401',
    '04FIC402': 'Hydrogen supply to R-400 (simulated flow, real valve)',
    '04FIC410': 'V-410 drain to water effluent (slave of 04LIC410)',
    '04FIC411': 'Jacket circulation flow from V-410 (P-410 discharge, 04FCV411)',
    '04TIC411': 'Jacket inlet temperature – drives 3-way 04TCV411 (heat supply)',
    '04TIC410': 'V-410 return temperature – E-410 air-fin split 04TCV410',
    '04LIC410': 'V-410 jacket-water level, cascades to 04FIC410',
    '04LIC420': 'V-420 product drum level',
    '04FIC420': 'Run-down flow from V-420 via P-420 to filters F420A/B',
    '04PIC420': 'V-420 pressure, 04PCV420 (simulated)',
    '04FIC421': 'Nitrogen stripping flow to V-420 (simulated flow, real valve)',
    '04TI400': 'Feed after E-400 feed/effluent exchanger',
    '04TI407': 'Feed into top of R-400 (E-401 outlet)',
    '04TI401': 'R-400 bed temperature 1 (top)',
    '04TI402': 'R-400 bed temperature 2',
    '04TI403': 'R-400 bed temperature 3',
    '04TI404': 'R-400 bed temperature 4',
    '04TI405': 'R-400 bed temperature 5',
    '04TI406': 'R-400 bed temperature 6 (bottom)',
    '04TI408': 'Jacket water out of R-400 (top)',
    '04TI412': 'V-410 inlet mix temperature',
    '04TI420': 'Product after E-420 cooler',
    '04FI413': 'Heat-supply water into jacket through 04TCV411',
    '04AT400': 'Unreacted feed in product, %',
    '04AT420': 'Hydrogen in product, %',
    '04LI400': 'V-400 dump vessel level',
    '04FIQ420': 'Run-down totaliser, l',
    '04PT423': 'Filter outlet pressure',
    '04PT424': 'Filter inlet pressure',
    '04dP420': 'Filter differential pressure',
    '01PI121': 'Service air header pressure, barg',
    '01PI122': 'Instrument air header pressure, barg',
    '05PIC511': 'Unit 400 feed header pressure (from Unit 500)',
    'P-410': 'Jacket water pump (trips on no flow – open 04FCV411 first)',
    'P-420': 'Run-down pump (trips on no flow – open 04FCV420 first)',
    '04CAT400': 'Catalyst activity (instructor), %',
}


# ------------------------------------------------------------------ C300 layer
class Loop:
    """PID block, velocity form. action 'rev': PV above SP -> OP down."""

    def __init__(self, tag, eu, lo, hi, kc, ti, action='rev', sp=0.0, mode='MAN', ophi=100.0, oplo=0.0,
                 master=None, slave=None):
        self.tag, self.eu, self.lo, self.hi = tag, eu, lo, hi
        self.kc, self.ti, self.action = kc, ti, action
        self.sp, self.pv, self.op, self.mode = sp, 0.0, 0.0, mode
        self.ophi, self.oplo = ophi, oplo
        self.master, self.slave = master, slave
        self.e1 = None
        self.bad = False
        self.si = False          # safety interlock active

    def update(self, dt):
        if self.si:
            self.op, self.e1 = 0.0, None
            return
        if self.mode == 'MAN' or self.bad:
            self.e1 = None
            return
        span = max(1e-9, self.hi - self.lo)
        e = (self.sp - self.pv) / span * 100.0
        if self.action == 'dir':
            e = -e
        if self.e1 is not None:
            self.op += self.kc * ((e - self.e1) + dt / self.ti * e)
        self.op = max(self.oplo, min(self.ophi, self.op))
        self.e1 = e

    def to_dict(self):
        return dict(kind='loop', tag=self.tag, eu=self.eu, lo=self.lo, hi=self.hi, sp=self.sp, pv=self.pv,
                    op=self.op, mode=self.mode, ophi=self.ophi, bad=self.bad, si=self.si, kc=self.kc, ti=self.ti,
                    master=self.master, slave=self.slave, desc=DESC.get(self.tag, ''))


class Pump:
    def __init__(self, tag, delay=5.0):
        self.tag, self.cmd, self.running, self.tripped = tag, 'STOPPED', False, False
        self.delay, self.noflow_t = delay, 0.0

    def to_dict(self):
        return dict(kind='pump', tag=self.tag, cmd=self.cmd, running=self.running, tripped=self.tripped,
                    desc=DESC.get(self.tag, ''))


class Plant:
    """Twin + plant hydraulics + C300 controls, stepped at 1 s simulated time."""

    def __init__(self):
        self.lock = threading.RLock()
        self.speed, self.paused = 1.0, False
        self.events = []
        self.new_model()
        L = Loop
        self.loops = {
            '04FIC400': L('04FIC400', 'l/h', 0, 1500, 0.1, 10, sp=1000),
            '04TIC401': L('04TIC401', 'degC', 0, 250, 1.0, 120, sp=75, slave='04FIC401'),
            '04FIC401': L('04FIC401', 'l/h', 0, 2000, 0.1, 10, master='04TIC401'),
            '04FIC402': L('04FIC402', 'Nm3/h', 0, 1200, 0.2, 15, sp=0, mode='AUTO'),
            '04FIC411': L('04FIC411', 'l/h', 0, 3000, 0.1, 10, sp=2000),
            '04TIC411': L('04TIC411', 'degC', 0, 250, 2.0, 60, sp=110, ophi=20.0),
            '04TIC410': L('04TIC410', 'degC', 0, 250, 0.3, 20, action='dir', sp=110, mode='AUTO'),
            '04LIC410': L('04LIC410', '%', 0, 100, 1.0, 600, action='dir', sp=60, mode='AUTO', slave='04FIC410'),
            '04FIC410': L('04FIC410', 'l/h', 0, 3000, 0.1, 10, mode='CAS', master='04LIC410'),
            '04FIC420': L('04FIC420', 'l/h', 0, 5000, 0.1, 10, sp=1000),
            '04PIC420': L('04PIC420', 'barg', 0, 60, 1.0, 30, action='dir', sp=20, mode='AUTO'),
            '04FIC421': L('04FIC421', 'Nm3/h', 0, 1000, 0.2, 15, sp=245),
        }
        self.pumps = {'P-410': Pump('P-410'), 'P-420': Pump('P-420')}
        self.lvl410, self.lvl420, self.fiq420 = 55.0, 70.0, 0.0
        self.air = 6.0
        self.hist, self.hist_t = {}, []
        self.fl, self.f413 = {}, 0.0

    def new_model(self):
        self.m = T.Twin()
        self.m.set('04E410', 1)
        self.m.set('04LIC410_PV', 55)

    def log(self, text, kind='event'):
        self.events.append(dict(t=round(self.m.t), kind=kind, text=text))
        self.events = self.events[-200:]

    # ---------------------------------------------------------------- one second
    def step(self):
        dt = 1.0
        lp, m = self.loops, self.m
        p410, p420 = self.pumps['P-410'], self.pumps['P-420']

        # cascade: master OP -> slave SP
        for s in lp.values():
            if s.master and s.mode == 'CAS':
                ms = lp[s.master]
                s.sp = s.lo + ms.op / 100.0 * (s.hi - s.lo)
            if s.slave and lp[s.slave].mode != 'CAS':
                s.op = (lp[s.slave].sp - lp[s.slave].lo) / (lp[s.slave].hi - lp[s.slave].lo) * 100.0  # track

        # --- plant hydraulics (real flows on the plant) ---
        def lag(k, target, tau=3.0):          # valve stroke / line dynamics
            f = self.fl.get(k, 0.0)
            f += (target - f) * min(1.0, dt / tau)
            self.fl[k] = f
            return f
        f400 = lag('400', lp['04FIC400'].op * 74.0)
        f401 = lag('401', lp['04FIC401'].op * 112.0)
        tcv411 = lp['04TIC411'].op
        t411 = lp['04FIC411'].op * 140.0 if p410.running else 0.0
        if p410.running and tcv411 > 90:            # 3-way valve closes the pump path
            t411 *= max(0.0, (100 - tcv411) / 10.0)
        f411 = lag('411', t411)
        f413 = lag('413', tcv411 * 130.0)
        f410 = lag('410', lp['04FIC410'].op * 143.0)
        f420 = lag('420', lp['04FIC420'].op * 126.0 if p420.running else 0.0)

        # pumps: flow-switch trip after delay (deadhead)
        for p, flow in ((p410, f411), (p420, f420)):
            if p.cmd == 'RUNNING' and not p.tripped:
                p.running = True
                p.noflow_t = p.noflow_t + dt if flow < 50 else 0.0
                if p.noflow_t >= p.delay:
                    p.running, p.tripped = False, True
                    self.log(f'{p.tag} TRIPPED – no flow (flow switch, deadhead)', 'alarm')
            elif p.cmd == 'STOPPED':
                p.running, p.noflow_t = False, 0.0
        if not p410.running:
            f411 = self.fl['411'] = 0.0
        if not p420.running:
            f420 = self.fl['420'] = 0.0
        self.f413 = f413

        # levels
        self.lvl410 += (f413 - f410) / 3600.0 / 600.0 * 100.0 * dt
        self.lvl410 = max(0.0, min(100.0, self.lvl410))
        self.lvl420 += (f400 - f420) / 3600.0 / 4700.0 * 100.0 * dt
        self.lvl420 = max(0.0, min(100.0, self.lvl420))
        self.fiq420 += f420 / 3600.0 * dt
        if p410.running and self.lvl410 < 5:
            p410.running, p410.tripped = False, True
            self.log('P-410 TRIPPED – V-410 low level (loss of suction)', 'alarm')

        # feed interlock on V-420 high level
        si = self.lvl420 >= 95.0
        if si and not lp['04FIC400'].si:
            self.log('04FIC400 SI – V-420 high level 95 %, feed stopped', 'alarm')
        lp['04FIC400'].si = si

        # --- to the Mimic model ---
        m.set('04FIC400_PV', f400)
        m.set('04FIC401_PV', f401)
        m.set('04FI413_PV', f413)
        m.set('04FIC411_PV', f411)
        m.set('04FIC410_PV', f410)
        m.set('04LIC410_PV', self.lvl410)
        m.set('04FIC402_OP', lp['04FIC402'].op)
        m.set('04FIC421_OP', lp['04FIC421'].op)
        m.set('04PIC420_OP', lp['04PIC420'].op)
        m.set('04TIC410_OP', lp['04TIC410'].op)
        m.step(dt)

        # --- PVs back to the C300 ---
        pv = {'04FIC400': f400, '04FIC401': f401, '04FIC411': f411, '04FIC410': f410, '04FIC420': f420,
              '04TIC401': m.get('04TI407_PV'), '04TIC411': m.get('04TIC411_PV'), '04TIC410': m.get('04TIC410_PV'),
              '04LIC410': self.lvl410, '04FIC402': m.get('04FIC402_PV'), '04PIC420': m.get('04PIC420_PV'),
              '04FIC421': m.get('04FIC421_PV')}
        for k, v in pv.items():
            lp[k].pv = v
        n2 = lp['04FIC421']
        was = n2.bad
        n2.bad = (not math.isfinite(n2.pv)) or n2.pv > n2.hi * 1.0
        if n2.bad and not was:
            self.log('04FIC421 PV NaN/BAD – model N2 flow above C300 range (model MAX_FLOW_N2 10000)', 'alarm')
        for l in lp.values():
            l.update(dt)

        # history every 5 s
        if int(m.t) % 5 == 0:
            vals = self.values()
            self.hist_t.append(round(m.t / 60.0, 2))
            for k, v in vals.items():
                if isinstance(v, (int, float)):
                    self.hist.setdefault(k, []).append(round(v, 2))
            if len(self.hist_t) > 2880:
                self.hist_t = self.hist_t[-2880:]
                for k in self.hist:
                    self.hist[k] = self.hist[k][-2880:]

    # ---------------------------------------------------------------- views
    def values(self):
        m, lp = self.m, self.loops
        g = m.get
        v = {k: l.pv for k, l in lp.items()}
        v.update({
            '04TI400': g('04TI400_PV'), '04TI407': g('04TI407_PV'),
            '04TI401': g('04TI401_PV'), '04TI402': g('04TI402_PV'), '04TI403': g('04TI403_PV'),
            '04TI404': g('04TI404_PV'), '04TI405': g('04TI405_PV'), '04TI406': g('04TI406_PV'),
            '04TI408': g('04TI410_PV'), '04TI412': g('04TIC410_PV'), '04TI420': 20.7,
            '04FI413': self.f413, '04AT400': g('04AT400_ATSIM'), '04AT420': g('04AT420_ATSIM'),
            '04LIC420': self.lvl420, '04LI400': 0.0, '04FIQ420': self.fiq420,
            '04PT424': 0.8 if self.pumps['P-420'].running else 0.0,
            '04PT423': 0.78 if self.pumps['P-420'].running else 0.0,
            '04dP420': 0.02 if self.pumps['P-420'].running else 0.0,
            '01PI121': self.air, '01PI122': self.air,
            '05PIC511': 2.5 if lp['04FIC400'].op > 0 else 0.2,
            '04STOICH': g('04AT400_STOICH'),
        })
        for k, x in list(v.items()):
            if isinstance(x, float) and not math.isfinite(x):
                v[k] = None
        return v

    def alarms(self):
        v, a = self.values(), []
        def chk(c, t):
            if c:
                a.append(t)
        chk((v['04AT400'] or 0) > 5 and self.loops['04FIC400'].pv > 5, '04AT400 PVHIGH – unreacted feed')
        chk((v['04AT420'] or 0) > 5, '04AT420 PVHIGH – H2 in product')
        chk(v['04LIC420'] >= 90, '04LIC420 PVHIGH – V-420 level')
        chk(v['04LIC410'] <= 15, '04LIC410 PVLOW – V-410 level')
        chk(max(v[f'04TI40{i}'] or 0 for i in range(1, 7)) > 200, 'R-400 bed temperature above 200 °C')
        chk(self.loops['04FIC421'].bad, '04FIC421 BAD PV')
        for p in self.pumps.values():
            chk(p.tripped, f'{p.tag} tripped – set STOPPED to reset')
        chk(self.loops['04FIC400'].si, '04FIC400 SI – feed interlock')
        return a

    def state(self):
        with self.lock:
            return dict(t=self.m.t, speed=self.speed, paused=self.paused, values=self.values(),
                        loops={k: l.to_dict() for k, l in self.loops.items()},
                        pumps={k: p.to_dict() for k, p in self.pumps.items()},
                        alarms=self.alarms(), events=self.events[-30:],
                        cat=self.m.get('04CAT400'), desc=DESC)

    # ---------------------------------------------------------------- commands
    def command(self, c):
        with self.lock:
            kind = c.get('cmd')
            if kind == 'loop':
                l = self.loops[c['tag']]
                if 'mode' in c:
                    md = c['mode']
                    if md == 'CAS' and not l.master:
                        return 'no master'
                    l.mode = md
                    self.log(f"{l.tag} mode → {md}")
                if 'sp' in c and l.mode != 'CAS':
                    l.sp = float(c['sp'])
                    self.log(f"{l.tag} SP → {l.sp:g}")
                if 'op' in c:
                    if l.mode != 'MAN':
                        return 'OP only in MAN'
                    l.op = max(0.0, min(100.0, float(c['op'])))
                    self.log(f"{l.tag} OP → {l.op:g} %")
                if 'ophi' in c:
                    l.ophi = float(c['ophi'])
                    self.log(f"{l.tag} OP high limit → {l.ophi:g} %")
                if 'kc' in c:
                    l.kc = float(c['kc'])
                if 'ti' in c:
                    l.ti = float(c['ti'])
            elif kind == 'pump':
                p = self.pumps[c['tag']]
                p.cmd = c['state']
                if p.cmd == 'STOPPED':
                    p.tripped = False
                p.noflow_t = 0.0
                self.log(f"{p.tag} → {p.cmd}")
            elif kind == 'speed':
                self.speed = float(c['value'])
            elif kind == 'pause':
                self.paused = bool(c['value'])
            elif kind == 'restart_run':
                t = self.m.t
                self.new_model()
                self.m.t = t
                self.log('Restart Run – model reset to ambient (levels and controls kept)')
            elif kind == 'cat':
                self.m.set('04CAT400', float(c['value']))
                self.log(f"04CAT400 → {float(c['value']):g} %")
            elif kind == 'air':
                self.air = float(c['value'])
            elif kind == 'save':
                os.makedirs(SNAP_DIR, exist_ok=True)
                name = ''.join(ch for ch in c.get('name', 'snap') if ch.isalnum() or ch in '-_') or 'snap'
                with open(os.path.join(SNAP_DIR, name + '.pkl'), 'wb') as f:
                    pickle.dump(self.snapshot_obj(), f)
                self.log(f'Snapshot saved: {name}')
            elif kind == 'load':
                name = ''.join(ch for ch in c.get('name', '') if ch.isalnum() or ch in '-_')
                with open(os.path.join(SNAP_DIR, name + '.pkl'), 'rb') as f:
                    self.restore(pickle.load(f))
                self.log(f'Snapshot loaded: {name}')
            return 'ok'

    def snapshot_obj(self):
        return dict(fl=self.fl, m=self.m, loops=self.loops, pumps=self.pumps, lvl410=self.lvl410, lvl420=self.lvl420,
                    fiq420=self.fiq420, air=self.air)

    def restore(self, s):
        self.m, self.loops, self.pumps = s['m'], s['loops'], s['pumps']
        self.lvl410, self.lvl420, self.fiq420, self.air = s['lvl410'], s['lvl420'], s['fiq420'], s['air']
        self.fl = s.get('fl', {})

    def runner(self):
        while True:
            t0 = time.time()
            if not self.paused:
                n = max(1, int(round(self.speed)))
                with self.lock:
                    for _ in range(n):
                        self.step()
            time.sleep(max(0.0, 1.0 - (time.time() - t0)) if self.speed >= 1 else 1.0 / max(self.speed, 0.1))


PLANT = Plant()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype='application/json'):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            with open(os.path.join(HERE, 'u400_console.html'), 'rb') as f:
                return self.send(200, f.read(), 'text/html; charset=utf-8')
        if self.path == '/api/state':
            return self.send(200, json.dumps(PLANT.state()))
        if self.path.startswith('/api/hist'):
            with PLANT.lock:
                return self.send(200, json.dumps(dict(t=PLANT.hist_t, v=PLANT.hist)))
        if self.path == '/api/layout':
            f = LAYOUT_FILE if os.path.exists(LAYOUT_FILE) else os.path.join(HERE, 'u400_layout_default.json')
            with open(f, 'rb') as fh:
                return self.send(200, fh.read())
        if self.path == '/api/snapshots':
            os.makedirs(SNAP_DIR, exist_ok=True)
            return self.send(200, json.dumps(sorted(x[:-4] for x in os.listdir(SNAP_DIR) if x.endswith('.pkl'))))
        self.send(404, '{}')

    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(n) or b'{}')
        if self.path == '/api/cmd':
            try:
                return self.send(200, json.dumps(dict(result=PLANT.command(body))))
            except Exception as ex:   # noqa: BLE001
                return self.send(400, json.dumps(dict(result=str(ex))))
        if self.path == '/api/layout':
            if body.get('reset'):
                if os.path.exists(LAYOUT_FILE):
                    os.remove(LAYOUT_FILE)
            else:
                with open(LAYOUT_FILE, 'w') as f:
                    json.dump(body, f, indent=1)
            return self.send(200, '{"result":"ok"}')
        self.send(404, '{}')


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8400
    threading.Thread(target=PLANT.runner, daemon=True).start()
    print(f'Unit 400 console on http://0.0.0.0:{port}  (Ctrl+C to stop)')
    ThreadingHTTPServer(('0.0.0.0', port), H).serve_forever()
