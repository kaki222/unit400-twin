"""
UNIT400-TWIN milestone M2 - catalyst activity and kinetics parameter interface.

A catalyst is described by a CatalystProfile (JSON-serialisable) and applied to a
running Twin. Nothing in the generated Mimic model is edited: the profile sets the
model's own inputs (T_START, T_IDEAL, HEAT_PER_MOLE, 04CAT400) and, for
'arrhenius' kinetics, swaps the per-zone reaction-speed law on that Twin instance.

Native Mimic law (kinetics='linear'), per bed zone i with temperature T_i:
    f_i = max((T_i - T_START) / (T_IDEAL - T_START), 0)
    rate_i = f_i * CAT[%] * (1000 / feed) / 100 / 6
Arrhenius option (kinetics='arrhenius'), anchored so f = 1 at T_IDEAL:
    f_i = exp(-Ea/R * (1/T_i - 1/T_IDEAL))   for T_i > T_START, else 0
Deactivation (time on stream, only while feed > 5 l/h):
    a(t) = a(t-dt) * exp(-(kd + kd_sinter * [T_max > T_sinter]) * dt_h)
    04CAT400 = activity_pct * a(t)
"""
import json
import math
import types
from dataclasses import dataclass, asdict, field

import unit400_twin as T

R = 8.314e-3  # kJ/mol/K


@dataclass
class CatalystProfile:
    name: str
    activity_pct: float = 100.0      # 04CAT400 at start of run
    t_start: float = 100.0           # no reaction below (C)
    t_ideal: float = 160.0           # full design rate (C)
    heat_per_mole: float = 110.0     # model's dT factor (Mimic HEAT_PER_MOLE)
    kinetics: str = 'linear'         # 'linear' (Mimic native) or 'arrhenius'
    ea_kj_mol: float = 60.0          # used only for 'arrhenius'
    kd_per_h: float = 0.0            # first-order deactivation, time on stream
    t_sinter: float = 999.0          # above this hot-spot T, extra deactivation
    kd_sinter_per_h: float = 0.0
    status: str = 'illustrative'     # 'validated' | 'illustrative' | 'measured'
    note: str = ''

    def check(self):
        assert self.t_ideal > self.t_start, 't_ideal must exceed t_start'
        assert 0 <= self.activity_pct <= 200, 'activity_pct 0-200 %'
        assert self.kinetics in ('linear', 'arrhenius')
        assert self.heat_per_mole > 0 and self.kd_per_h >= 0 and self.kd_sinter_per_h >= 0
        return self


def load_library(path):
    with open(path) as f:
        return {d['name']: CatalystProfile(**d).check() for d in json.load(f)}


def save_library(profiles, path):
    with open(path, 'w') as f:
        json.dump([asdict(p) for p in profiles], f, indent=1)


def _speed_arrhenius(self):
    t_start, t_ideal = self.inputs.get('IN_1', 0.0), self.inputs.get('IN_2', 0.0)
    cat, feed = self.inputs.get('IN_3', 0.0), self.inputs.get('IN_4', 0.0)
    dwell = 1000.0 / feed if feed > 0 else 0.0
    ea = self._cat_ea
    tk_ideal = t_ideal + 273.15
    for i in range(1, 7):
        t = self._read('JACKET_WATERTEMPERATURE/TI40%d/IN' % i)
        f = math.exp(-ea / R * (1.0 / (t + 273.15) - 1.0 / tk_ideal)) if t > t_start else 0.0
        self.outputs['OUT_%d' % i] = f * cat * dwell / 100 / 6
    self.outputs['OUT_7'] = dwell


class CatalystTwin(T.Twin):
    """Twin with a swappable catalyst. Use apply(profile) at any time."""

    def __init__(self, profile=None):
        super().__init__()
        self._speed = self.objects[('REACTION', 'REACTION_SPEED')]
        self._native_speed = self._speed.evaluate
        self.apply(profile or CatalystProfile('mimic_baseline', status='validated'))

    def apply(self, p, reset_activity=True):
        p.check()
        self.cat = p
        self.objects[('REACTION', 'T_START')].field_address = str(p.t_start)
        self.objects[('REACTION', 'T_IDEAL')].field_address = str(p.t_ideal)
        self.objects[('REACTION', 'HEAT_PER_MOLE')].field_address = str(p.heat_per_mole)
        if p.kinetics == 'arrhenius':
            self._speed._cat_ea = p.ea_kj_mol
            self._speed.evaluate = types.MethodType(_speed_arrhenius, self._speed)
        else:
            self._speed.evaluate = self._native_speed
        if reset_activity:
            self.a, self.tos_h = 1.0, 0.0
        self.set('04CAT400', p.activity_pct * self.a)

    def hot_spot(self):
        return max(self.get('04TI40%d_PV' % i) for i in range(1, 7))

    def step(self, dt):
        p = self.cat
        if (p.kd_per_h > 0 or p.kd_sinter_per_h > 0) and self.get('04FIC400_PV') > 5:
            kd = p.kd_per_h + (p.kd_sinter_per_h if self.hot_spot() > p.t_sinter else 0.0)
            self.a *= math.exp(-kd * dt / 3600.0)
            self.tos_h += dt / 3600.0
            self.set('04CAT400', p.activity_pct * self.a)
        super().step(dt)
