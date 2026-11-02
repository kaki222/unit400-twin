"""
Unit 400 digital twin - corrected runtime on top of the generated model.

unit400_model.py (generated) is used unchanged. This module fixes the
runtime semantics so the model is driven ONLY by the real plant inputs
(the values the C300 sends to Mimic) and calculates everything else:

  * unwired object inputs take their Mimic initial values (constants
    such as /3600, x0.01, 600 l, 30 % ... were previously 0)
  * OUT_PARAMs write to their FIELD_ADDRESS (internal HX inputs and
    the UNIT400HYBRID/... tags), as Mimic does
  * IN_PARAMs re-read UNIT400HYBRID/... tags every pass
  * ANALOGVALVE uses SETPOINT / VALVE_POSITION (fraction 0-1, full
    stroke OPEN_CLOSE_TIME s)
  * RNG adds noise to its input (seeded; can be switched off)
  * HX is dynamic (tube and shell hold-up from TUBE/SHELL_VOLUME), so
    a stagnant bed heats from the jacket as on the plant

Units assumed: HX flows l/s, volumes m3, density kg/m3, Cp kJ/kg.K,
U W/m2.K.  HOLDUP_SCALE multiplies the hold-up heat capacity.
"""
import math
import random

import unit400_model as gen
from unit400_equations import (
    InParamObject, OutParamObject, AnalogValveObject, RngObject, HXObject,
    FofObject,
)

HOLDUP_SCALE = 1.0
UA_SCALE = {}          # per HX tag, e.g. {'R-400': 0.2}; key = tag prefix
# Calibrated against private plant runs: the model's own constants (HEAT_PER_MOLE as
# exported) with 04CAT400 = 100 reproduced a real reaction run within ~8 C rms on the bed.
HEAT_PER_MOLE = None   # None = use the exported model value (110)
CAT_DEFAULT = 100.0
SHELL_FLOW_SCALE = {'E-410_AIRFIN': 1000.0}   # air side flow is m3/s in Mimic, not l/s
NOISE = True
_rng = random.Random(400)

PLANT_INPUTS = [
    '04FIC400_PV', '04FIC401_PV', '04FIC402_OP', '04FI413_PV', '04FIC410_PV',
    '04FIC411_PV', '04FIC421_OP', '04PIC420_OP', '04TIC410_OP', '04LIC410_PV',
    '04LI410_RST', '04XZV401_PV', '04E410', '04CAT400',
]


# ---------------- object patches ----------------
def _inparam_eval(self):
    addr = self.field_address
    if addr.startswith('UNIT400HYBRID/'):
        if addr in self.model.external:
            self.outputs['OUT'] = float(self.model.external[addr])
        return
    return _orig_inparam_eval(self)


def _outparam_eval(self):
    v = float(self.inputs.get('IN', 0.0))
    self.outputs['IN'] = v
    addr = self.field_address
    if not addr:
        return
    if addr.startswith('UNIT400HYBRID/'):
        self.model.external[addr] = v
        return
    parts = addr.split('/')
    if len(parts) == 2:
        tgt = self.model.objects.get((self.module, parts[0]))
        if tgt is not None:
            tgt.set_input(parts[1], v)


def _valve_init(self, module, tag, fields, init):
    _orig_valve_init(self, module, tag, fields, init)
    self.position = float(fields.get('STARTPOSITION', 0.0)) / 100.0
    self.outputs['VALVE_POSITION'] = self.position


def _valve_step(self, dt):
    sp = max(0.0, min(1.0, float(self.inputs.get('SETPOINT', 0.0))))
    rate = 1.0 / self.open_close_time if self.open_close_time > 0 else 1e9
    d = sp - self.position
    self.position = sp if abs(d) <= rate * dt else self.position + math.copysign(rate * dt, d)
    self.outputs['VALVE_POSITION'] = self.position
    self.outputs['OUT'] = self.position


def _rng_eval(self):
    x = float(self.inputs.get('IN', 0.0))
    if NOISE:
        x = x * (1.0 + _rng.uniform(self.ran_lo, self.ran_hi) / 100.0)
    self.outputs['OUT'] = max(self.lo_cutoff, min(self.hi_cutoff, x))


def _hx_init(self, module, tag, fields, init):
    _orig_hx_init(self, module, tag, fields, init)
    self.Tt = float(init.get('TUBE_IN_TEMP', 20.0))
    self.Ts = float(init.get('SHELL_IN_TEMP', 20.0))
    self.Tt = self.Ts = 20.0                      # cold, plant-like start
    self.outputs['TUBE_OUT_TEMP'] = self.Tt
    self.outputs['SHELL_OUT_TEMP'] = self.Ts


def _hx_step(self, dt):
    Ft = max(0.0, float(self.inputs.get('TUBE_IN_FLOW', 0.0)))     # l/s
    Fs = max(0.0, float(self.inputs.get('SHELL_IN_FLOW', 0.0))) * SHELL_FLOW_SCALE.get(self.tag, 1.0)
    Tti = float(self.inputs.get('TUBE_IN_TEMP', self.Tt))
    Tsi = float(self.inputs.get('SHELL_IN_TEMP', self.Ts))
    Ct = Ft * self.rho_tube / 1000.0 * self.cp_tube                # kW/K
    Cs = Fs * self.rho_shell / 1000.0 * self.cp_shell
    Mt = max(1e-6, self.tube_volume * self.rho_tube * self.cp_tube * HOLDUP_SCALE)   # kJ/K
    Ms = max(1e-6, self.shell_volume * self.rho_shell * self.cp_shell * HOLDUP_SCALE)
    UA = self.U * self.area * (1.0 - self.fouling) / 1000.0        # kW/K
    for k, v in UA_SCALE.items():
        if self.tag.startswith(k):
            UA *= v
    n = max(1, int(math.ceil(dt / 0.05)))                          # stable sub-steps
    h = dt / n
    for _ in range(n):
        q = UA * (self.Ts - self.Tt)
        self.Tt += h * (Ct * (Tti - self.Tt) + q) / Mt
        self.Ts += h * (Cs * (Tsi - self.Ts) - q) / Ms
    self.outputs['TUBE_OUT_TEMP'] = self.Tt
    self.outputs['SHELL_OUT_TEMP'] = self.Ts
    self.outputs['TUBE_OUT_FLOW'] = Ft
    self.outputs['SHELL_OUT_FLOW'] = Fs / SHELL_FLOW_SCALE.get(self.tag, 1.0)


def _fof_step(self, dt):
    x = float(self.inputs.get('IN', 0.0))
    if self.tau > 1e-9:
        self.y += min(1.0, dt / self.tau) * (self.gain * x - self.y)
    else:
        self.y = self.gain * x
    self.outputs['OUT'] = self.y


_orig_inparam_eval = InParamObject.evaluate
_orig_valve_init = AnalogValveObject.__init__
_orig_hx_init = HXObject.__init__
InParamObject.evaluate = _inparam_eval
OutParamObject.evaluate = _outparam_eval
AnalogValveObject.__init__ = _valve_init
AnalogValveObject.step = _valve_step
RngObject.evaluate = _rng_eval
HXObject.__init__ = _hx_init
HXObject.step = _hx_step
FofObject.step = _fof_step


# ---------------- model ----------------
class Twin(gen.Unit400Model):
    def __init__(self):
        super().__init__()
        wired = {(id(d), p) for _, _, d, p, _, _ in self._wires}
        for obj in self.objects.values():
            if obj.TYPE in ('IN_PARAM', 'OUT_PARAM', 'ANALOGVALVE', 'FOF', 'RNG'):
                continue
            for k, v in obj.init.items():
                if (id(obj), k) not in wired:
                    try:
                        obj.inputs[k] = float(v)
                    except (TypeError, ValueError):
                        pass
        for t in PLANT_INPUTS:
            self.set_external('UNIT400HYBRID/' + t, 0.0)
        self.set('04CAT400', CAT_DEFAULT)
        if HEAT_PER_MOLE is not None:
            self.objects[('REACTION', 'HEAT_PER_MOLE')].field_address = str(HEAT_PER_MOLE)
        self.t = 0.0

    def set(self, tag, value):
        self.set_external('UNIT400HYBRID/' + tag, value)

    def get(self, tag):
        return self.external.get('UNIT400HYBRID/' + tag, float('nan'))

    def step(self, dt):
        super().step(dt)
        self.t += dt

    def run(self, seconds, dt=1.0, log_every=None, log=None, cols=None):
        for _ in range(int(round(seconds / dt))):
            self.step(dt)
            if log is not None and log_every and int(round(self.t)) % log_every == 0:
                log.append(self.row(cols))

    def row(self, cols):
        r = {'t_min': round(self.t / 60.0, 2)}
        for c in cols:
            r[c] = self.get(c)
        return r


# Air-fin flow cannot exceed the jacket flow it is part of; the generated
# calc can see them one step apart and then returns a negative V-410
# temperature. Clamp (Mimic evaluates both in the same scan).
_orig_tic410 = gen.Calc_JACKET_WATERTEMPERATURE_TIC410.evaluate


def _tic410_eval(self):
    j = self.inputs.get('IN_3', 0.0)
    if self.inputs.get('IN_1', 0.0) > j:
        self.inputs['IN_1'] = j
    _orig_tic410(self)


gen.Calc_JACKET_WATERTEMPERATURE_TIC410.evaluate = _tic410_eval
