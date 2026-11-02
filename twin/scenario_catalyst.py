"""UNIT400-TWIN M2 test: run each catalyst profile through the operating sequence
of the basis (basis.json if present, else basis.example.json) and compare.
Usage: python3 scenario_catalyst.py [catalysts.json] [extra_hours]"""
import sys
import unit400_twin as T
import catalyst as C
import basis as Bz

T.NOISE = False
lib = C.load_library(sys.argv[1] if len(sys.argv) > 1 else 'catalysts.json')
extra_h = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0
B = Bz.load()
REF = Bz.reference()


class PI:
    def __init__(s, kc, ti, direct=False):
        s.kc, s.ti, s.op, s.e1, s.d = kc, ti, 0.0, None, direct

    def u(s, pv, sp, dt=1.0):
        e = (pv - sp) if s.d else (sp - pv)
        if s.e1 is not None:
            s.op += s.kc * ((e - s.e1) + dt / s.ti * e)
        s.op = max(0.0, min(100.0, s.op)); s.e1 = e
        return s.op


def run(p):
    m = C.CatalystTwin(p)
    pi = PI(0.5, 120, direct=True)

    def go(minutes, **kw):
        for k, v in kw.items():
            m.set(k, v)
        for _ in range(int(minutes * 60)):
            m.set('04TIC410_OP', pi.u(m.get('04TIC410_PV'), B['tic410_sp']))
            m.step(1.0)
    for mins, kw, _label in B['sequence']:
        go(mins, **kw)
    bed = [m.get('04TI40%d_PV' % i) for i in range(1, 7)]
    res = dict(name=p.name, at400=m.get('04AT400_ATSIM'), bed=bed, hot=max(bed), zone=bed.index(max(bed)) + 1)
    trail = []
    if p.kd_per_h > 0 or p.kd_sinter_per_h > 0:
        for _ in range(int(extra_h)):
            go(60)
            trail.append((m.tos_h, m.get('04CAT400'), m.get('04AT400_ATSIM'), m.hot_spot()))
    return res, trail


print('basis: %s (%s)\n' % (B['name'], B['_file']))
print('%-20s %-11s %7s %7s %5s  %s' % ('profile', 'status', 'AT400%', 'hot C', 'zone', 'bed TI401..406'))
trails = {}
for p in lib.values():
    r, tr = run(p)
    print('%-20s %-11s %7.1f %7.1f %5d  %s' % (r['name'], p.status, r['at400'], r['hot'], r['zone'],
                                               ' '.join('%5.1f' % b for b in r['bed'])))
    if tr:
        trails[p.name] = tr
for n, tr in trails.items():
    print('\n%s - time on stream after steady state' % n)
    print('%6s %8s %7s %7s' % ('TOS h', 'CAT400%', 'AT400%', 'hot C'))
    for tos, cat, at, hot in tr:
        print('%6.1f %8.1f %7.1f %7.1f' % (tos, cat, at, hot))
if REF:
    print('\nreference %s: AT400 %.1f %%, bed %s' % (REF['name'], REF['04AT400_ATSIM'],
          ' '.join('%.1f' % REF['04TI40%d_PV' % i] for i in range(1, 7))))
