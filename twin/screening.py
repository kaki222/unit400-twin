"""
UNIT400-TWIN milestone M3 - catalyst screening scenarios.

Maps, for any catalyst profile (M2), where the reactor gives on-spec product,
where conversion is lost and where the hot spot runs away, as a function of the
operator's levers: jacket inlet temperature (04TIC411 SP, AUTO) and feed rate.
Also measures how long a deactivating catalyst stays on spec.

Operating basis = basis.json (your plant, private) or basis.example.json:
jacket circulation, feed preheat 04FIC401, H2 kept in ratio to feed,
04TIC410 AUTO (V-410 return).

Criteria (edit SPEC_AT400 / HOT_LIMIT to suit):
  OK   unreacted feed 04AT400 <= SPEC_AT400 and peak hot spot <= HOT_LIMIT
  LOW  conversion lost  (04AT400 > SPEC_AT400), hot spot within limit
  HOT  peak hot spot > HOT_LIMIT at any time in the run (runaway risk)
"""
import copy
import unit400_twin as T
import catalyst as C
import basis as Bz

T.NOISE = False
SPEC_AT400 = 5.0      # % unreacted feed
HOT_LIMIT = 200.0     # C, screening limit for the bed hot spot (assumption, not a plant trip)
BASIS = Bz.load()
HEAT_PER_PCT = BASIS['heat_supply_lph_per_op_pct']   # 04TCV411 OP % -> 04FI413 l/h
H2_PER_FEED = BASIS['h2_nm3h_per_feed_lph']          # Nm3/h per l/h feed
H2_PER_OP = BASIS['h2_nm3h_per_op_pct']              # 04FIC402 Nm3/h per OP %
PREHEAT = BASIS['preheat_lph']
JACKET = BASIS['jacket_circulation_lph']
FEED = BASIS['feed_lph']


class PI:
    def __init__(s, kc, ti, sp, direct=False):
        s.kc, s.ti, s.sp, s.op, s.e1, s.d = kc, ti, sp, 0.0, None, direct

    def u(s, pv, dt=1.0):
        e = (pv - s.sp) if s.d else (s.sp - pv)
        if s.e1 is not None:
            s.op += s.kc * ((e - s.e1) + dt / s.ti * e)
        s.op = max(0.0, min(100.0, s.op)); s.e1 = e
        return s.op


class Plant:
    """Twin + the two loops in AUTO (04TIC411 jacket inlet, 04TIC410 V-410 return)."""

    def __init__(self, jacket_sp):
        self.m = C.CatalystTwin()
        self.tic411 = PI(1.0, 60.0, jacket_sp)
        self.tic410 = PI(0.5, 120.0, BASIS['tic410_sp'], direct=True)
        for k, v in {'04FIC411_PV': JACKET, '04LIC410_PV': 55, '04E410': 1}.items():
            self.m.set(k, v)

    def run(self, minutes, dt=1.0, watch=None):
        m = self.m
        for _ in range(int(minutes * 60 / dt)):
            m.set('04FI413_PV', self.tic411.u(m.get('04TIC411_PV'), dt) * HEAT_PER_PCT)
            m.set('04TIC410_OP', self.tic410.u(m.get('04TIC410_PV'), dt))
            m.step(dt)
            if watch is not None:
                watch(m)


_hot_cache = {}


def heated(jacket_sp, heat_min=25):
    """Bed heated to jacket SP with no feed - shared start point (cached)."""
    if jacket_sp not in _hot_cache:
        p = Plant(jacket_sp); p.run(heat_min)
        _hot_cache[jacket_sp] = p
    return copy.deepcopy(_hot_cache[jacket_sp])


def classify(at400, peak):
    if peak > HOT_LIMIT:
        return 'HOT'
    return 'OK' if at400 <= SPEC_AT400 else 'LOW'


def screen_point(profile, jacket_sp, feed=None, minutes=40):
    feed = feed or FEED
    p = heated(jacket_sp)
    m = p.m
    m.apply(profile)
    m.set('04FIC401_PV', PREHEAT)
    m.set('04FIC400_PV', feed)
    m.set('04FIC402_OP', feed * H2_PER_FEED / H2_PER_OP)
    peak = [0.0]

    def w(mm):
        h = mm.hot_spot()
        if h > peak[0]:
            peak[0] = h
    p.run(minutes, watch=w)
    bed = [m.get('04TI40%d_PV' % i) for i in range(1, 7)]
    at = m.get('04AT400_ATSIM')
    return dict(profile=profile.name, jacket_sp=jacket_sp, feed=feed, activity=profile.activity_pct,
                at400=round(at, 1), hot=round(max(bed), 1), zone=bed.index(max(bed)) + 1,
                peak=round(peak[0], 1), result=classify(at, peak[0]))


def time_on_spec(profile, jacket_sp, feed=None, hours=6.0, dt=2.0):
    """Hours a deactivating catalyst keeps 04AT400 <= SPEC_AT400 (None = never on spec)."""
    feed = feed or FEED
    p = heated(jacket_sp)
    m = p.m
    m.apply(profile)
    m.set('04FIC401_PV', PREHEAT); m.set('04FIC400_PV', feed); m.set('04FIC402_OP', feed * H2_PER_FEED / H2_PER_OP)
    p.run(40)                                  # reach steady state (counts as time on stream)
    if m.get('04AT400_ATSIM') > SPEC_AT400:
        return None, []
    trail = []
    t_lost = None
    for _ in range(int(hours * 6)):            # 10-min blocks
        p.run(10, dt=dt)
        trail.append((round(m.tos_h, 2), round(m.get('04CAT400'), 1), round(m.get('04AT400_ATSIM'), 1),
                      round(m.hot_spot(), 1)))
        if t_lost is None and m.get('04AT400_ATSIM') > SPEC_AT400:
            t_lost = m.tos_h
            break
    return t_lost, trail
