"""Operating basis for scenarios: loads basis.json if present (your plant's own
settings, kept private), otherwise basis.example.json (generic values)."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name=None):
    for f in ([name] if name else ['basis.json', 'basis.example.json']):
        p = f if os.path.isabs(f) else os.path.join(HERE, f)
        if os.path.exists(p):
            with open(p) as fh:
                b = json.load(fh)
            b['_file'] = os.path.basename(p)
            return b
    raise FileNotFoundError('no basis.json or basis.example.json')


def reference(name='reference.json'):
    """Optional measured steady state to compare against (private, not shipped)."""
    p = os.path.join(HERE, name)
    if os.path.exists(p):
        with open(p) as fh:
            return json.load(fh)
    return None
