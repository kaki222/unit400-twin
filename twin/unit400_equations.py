"""
Unit 400 — MIMIC primitive object implementations.

Hand-written base classes for the 13 MIMIC object types used in
UNIT400HYBRID. These are the "physics" — the equations that govern
each primitive. They are called by the auto-generated model code.
"""
import math
import random


class BaseObject:
    """Common interface for all MIMIC primitives."""
    TYPE = 'BASE'

    def __init__(self, module: str, tag: str, fields: dict, init: dict):
        self.module = module
        self.tag = tag
        self.fields = fields
        self.init = init
        self.inputs = {}
        self.outputs = {}
        self.locals = {}
        self.model = None  # set by Unit400Model during wiring

    def set_input(self, port: str, value):
        self.inputs[port] = value

    def get_output(self, port: str):
        return self.outputs.get(port, 0.0)

    def evaluate(self):
        pass

    def step(self, dt: float):
        pass


class InParamObject(BaseObject):
    """Reads a value from a FIELD_ADDRESS inside the model.

    FIELD_ADDRESS forms:
        MODULE/TAG/PORT      fully-qualified cross-module
        TAG/PORT             same-module reference
        TAG                  same-module, default OUT port
        <numeric>            literal number
        CONST_NAME           user constant
        Anything else        external (leave current value)
    """
    TYPE = 'IN_PARAM'

    def __init__(self, module, tag, fields, init):
        super().__init__(module, tag, fields, init)
        self.field_address = fields.get('FIELD_ADDRESS', '')
        self.outputs['OUT'] = float(init.get('IN', 0.0))

    def evaluate(self):
        addr = self.field_address
        if not addr:
            return

        # Numeric literal
        try:
            self.outputs['OUT'] = float(addr)
            return
        except (ValueError, TypeError):
            pass

        # User constant (bare name)
        if self.model is not None and addr in self.model.constants:
            self.outputs['OUT'] = float(self.model.constants[addr])
            return

        # Path forms
        parts = addr.split('/')
        obj = None
        port = 'OUT'

        if len(parts) == 3:
            module, tag, port = parts
            obj = self.model.objects.get((module, tag)) if self.model else None
        elif len(parts) == 2:
            tag, port = parts
            obj = self.model.objects.get((self.module, tag)) if self.model else None
        elif len(parts) == 1:
            tag = parts[0]
            obj = self.model.objects.get((self.module, tag)) if self.model else None

        if obj is not None:
            self.outputs['OUT'] = obj.get_output(port)
            return
        # Otherwise, keep current value (external / unknown)

class OutParamObject(BaseObject):
    """Writes IN to a FIELD_ADDRESS. Also mirrors the value to
    outputs['IN'] so that other CALCs can VAL("TAG/IN") it."""
    TYPE = 'OUT_PARAM'

    def __init__(self, module, tag, fields, init):
        super().__init__(module, tag, fields, init)
        self.field_address = fields.get('FIELD_ADDRESS', '')
        self.inputs['IN'] = float(init.get('IN', 0.0))
        self.outputs['IN'] = float(init.get('IN', 0.0))

    def evaluate(self):
        self.outputs['IN'] = float(self.inputs.get('IN', 0.0))

class MultObject(BaseObject):
    TYPE = 'MULT'

    def __init__(self, module, tag, fields, init):
        super().__init__(module, tag, fields, init)
        self.num_in = int(fields.get('NUM_IN', 2))
        self.outputs['OUT'] = 0.0

    def _in(self, i):
        # Accept both IN_1 and IN_01 forms
        v = self.inputs.get('IN_%d' % i)
        if v is None:
            v = self.inputs.get('IN_%02d' % i)
        if v is None:
            v = self.inputs.get('IN_1') if i == 1 else 0.0
        return float(v if v is not None else 0.0)

    def evaluate(self):
        result = 1.0
        n = max(self.num_in, len(self.inputs))
        for i in range(1, n + 1):
            result *= self._in(i)
        self.outputs['OUT'] = result


class AddObject(BaseObject):
    TYPE = 'ADD'

    def __init__(self, module, tag, fields, init):
        super().__init__(module, tag, fields, init)
        self.num_in = int(fields.get('NUM_IN', 2))
        self.outputs['OUT'] = 0.0

    def _in(self, i):
        v = self.inputs.get('IN_%d' % i)
        if v is None:
            v = self.inputs.get('IN_%02d' % i)
        return float(v if v is not None else 0.0)

    def evaluate(self):
        result = 0.0
        n = max(self.num_in, len(self.inputs))
        for i in range(1, n + 1):
            result += self._in(i)
        self.outputs['OUT'] = result


class DivObject(BaseObject):
    TYPE = 'DIV'

    def __init__(self, module, tag, fields, init):
        super().__init__(module, tag, fields, init)
        self.outputs['OUT'] = 0.0

    def _in(self, i):
        v = self.inputs.get('IN_%d' % i)
        if v is None:
            v = self.inputs.get('IN_%02d' % i)
        return float(v if v is not None else 0.0)

    def evaluate(self):
        num = self._in(1)
        den = self._in(2)
        self.outputs['OUT'] = num / den if abs(den) > 1e-12 else 0.0


class NotObject(BaseObject):
    TYPE = 'NOT'

    def __init__(self, module, tag, fields, init):
        super().__init__(module, tag, fields, init)
        self.outputs['OUT'] = 0.0

    def evaluate(self):
        v = float(self.inputs.get('IN', 0.0))
        self.outputs['OUT'] = 0.0 if v != 0 else 1.0


class CmpObject(BaseObject):
    TYPE = 'CMP'

    def __init__(self, module, tag, fields, init):
        super().__init__(module, tag, fields, init)
        self.outputs['OUT'] = 0.0

    def evaluate(self):
        a = float(self.inputs.get('IN_1', 0.0))
        b = float(self.inputs.get('IN_2', 0.0))
        self.outputs['OUT'] = 1.0 if a > b else 0.0


class FofObject(BaseObject):
    TYPE = 'FOF'

    def __init__(self, module, tag, fields, init):
        super().__init__(module, tag, fields, init)
        self.gain = float(fields.get('GAIN', 1.0))
        self.tau = float(init.get('FILTER_TIME', 1.0))
        self.y = float(init.get('IN', 0.0))
        self.outputs['OUT'] = self.y

    def step(self, dt):
        x = float(self.inputs.get('IN', 0.0))
        if self.tau > 1e-9:
            self.y += dt * (self.gain * x - self.y) / self.tau
        else:
            self.y = self.gain * x
        self.outputs['OUT'] = self.y


class HXObject(BaseObject):
    """Effectiveness-NTU heat exchanger."""
    TYPE = 'HX'

    def __init__(self, module, tag, fields, init):
        super().__init__(module, tag, fields, init)
        self.area = float(fields.get('SURFACE_AREA', 1.0))
        self.U = float(init.get('HEAT_XFER_COEFFICIENT(U)', 100.0))
        self.fouling = float(init.get('FOULING_FACTOR', 0.0))
        self.cp_shell = float(init.get('SHELL_SIDE_HEAT_CAPACITY(Cm)', 4.18))
        self.cp_tube = float(init.get('TUBE_SIDE_HEAT_CAPACITY(Cp)', 4.18))
        self.rho_shell = float(init.get('SHELL_SIDE_DENSITY', 1000.0))
        self.rho_tube = float(init.get('TUBE_SIDE_DENSITY', 1000.0))
        self.flow_pattern = int(fields.get('FLOW_PATTERN', 0))
        self.tube_volume = float(fields.get('TUBE_VOLUME', 0.0))
        self.shell_volume = float(fields.get('SHELL_VOLUME', 0.0))

        self.tube_out_temp = float(init.get('TUBE_IN_TEMP', 20.0))
        self.shell_out_temp = float(init.get('SHELL_IN_TEMP', 20.0))

        self.outputs['TUBE_OUT_TEMP'] = self.tube_out_temp
        self.outputs['SHELL_OUT_TEMP'] = self.shell_out_temp
        self.outputs['TUBE_OUT_FLOW'] = float(init.get('TUBE_IN_FLOW', 0.0))
        self.outputs['SHELL_OUT_FLOW'] = float(init.get('SHELL_IN_FLOW', 0.0))

    def step(self, dt):
        md_shell = float(self.inputs.get('SHELL_IN_FLOW', 0.0))
        T_shell_in = float(self.inputs.get('SHELL_IN_TEMP', 20.0))
        md_tube = float(self.inputs.get('TUBE_IN_FLOW', 0.0))
        T_tube_in = float(self.inputs.get('TUBE_IN_TEMP', 20.0))

        C_shell = md_shell * self.cp_shell if md_shell > 0 else 0.0
        C_tube = md_tube * self.cp_tube if md_tube > 0 else 0.0
        Cmin = min(C_shell, C_tube) if (C_shell > 0 and C_tube > 0) else 0.0
        Cmax = max(C_shell, C_tube) if (C_shell > 0 and C_tube > 0) else 0.0

        UA = self.U * self.area * (1.0 - self.fouling)

        if Cmin > 1e-9 and UA > 0:
            NTU = UA / Cmin
            Cr = Cmin / Cmax if Cmax > 1e-9 else 0.0
            if self.flow_pattern == 0:
                if abs(1.0 - Cr) < 1e-6:
                    eps = NTU / (1.0 + NTU)
                else:
                    eps = (1.0 - math.exp(-NTU * (1.0 - Cr))) / \
                          (1.0 - Cr * math.exp(-NTU * (1.0 - Cr)))
            else:
                eps = (1.0 - math.exp(-NTU * (1.0 + Cr))) / (1.0 + Cr)
            Q = eps * Cmin * (T_tube_in - T_shell_in)
        else:
            Q = 0.0

        self.tube_out_temp = T_tube_in - Q / C_tube if C_tube > 1e-9 else T_tube_in
        self.shell_out_temp = T_shell_in + Q / C_shell if C_shell > 1e-9 else T_shell_in

        self.outputs['TUBE_OUT_TEMP'] = self.tube_out_temp
        self.outputs['SHELL_OUT_TEMP'] = self.shell_out_temp
        self.outputs['TUBE_OUT_FLOW'] = md_tube
        self.outputs['SHELL_OUT_FLOW'] = md_shell


class AnalogValveObject(BaseObject):
    TYPE = 'ANALOGVALVE'

    def __init__(self, module, tag, fields, init):
        super().__init__(module, tag, fields, init)
        self.start_position = float(fields.get('STARTPOSITION', 0.0))
        self.deadband = float(fields.get('DEADBAND', 0.0))
        self.open_close_time = float(fields.get('OPEN_CLOSE_TIME', 5.0))
        self.position = self.start_position
        self.outputs['OUT'] = self.position

    def step(self, dt):
        target = float(self.inputs.get('IN', self.position))
        if abs(target - self.position) < self.deadband:
            return
        rate = 100.0 / self.open_close_time if self.open_close_time > 0 else 100.0
        delta = target - self.position
        max_step = rate * dt
        if abs(delta) <= max_step:
            self.position = target
        else:
            self.position += max_step * (1 if delta > 0 else -1)
        self.outputs['OUT'] = self.position


class RngObject(BaseObject):
    TYPE = 'RNG'

    def __init__(self, module, tag, fields, init):
        super().__init__(module, tag, fields, init)
        self.eff_lo = float(fields.get('EFF_RANGE_EUL', 0.0))
        self.eff_hi = float(fields.get('EFF_RANGE_EUH', 100.0))
        self.ran_lo = float(fields.get('RAN_RANGE_EUL', 0.0))
        self.ran_hi = float(fields.get('RAN_RANGE_EUH', 0.5))
        self.hi_cutoff = float(fields.get('HIGH_CUTOFF', self.eff_hi))
        self.lo_cutoff = float(fields.get('LOW_CUTOFF', self.eff_lo))
        self.outputs['OUT'] = self.eff_lo

    def evaluate(self):
        span = self.eff_hi - self.eff_lo
        lo = self.eff_lo + self.ran_lo * span
        hi = self.eff_lo + self.ran_hi * span
        v = random.uniform(lo, hi)
        if v > self.hi_cutoff:
            v = self.hi_cutoff
        if v < self.lo_cutoff:
            v = self.lo_cutoff
        self.outputs['OUT'] = v


class CalcObject(BaseObject):
    TYPE = 'CALC'

    def __init__(self, module, tag, fields, init):
        super().__init__(module, tag, fields, init)
        self.expression = fields.get('EXPRESSION', '')
        self.num_in = int(fields.get('NUM_IN', 0))
        self.num_out = int(fields.get('NUM_OUT', 0))
        self.L = {}

    def _read(self, path):
        return self.model.read(path) if self.model else 0.0

    def _const(self, name):
        return self.model.constants.get(name, 0.0) if self.model else 0.0

    def evaluate(self):
        pass  # overridden by generated subclass
