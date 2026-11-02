# UNIT400-TWIN

A Python digital twin of a jacketed fixed-bed hydrogenation reactor (R-400, "Unit 400") of the kind used on pilot/training plants, with a browser operator console and notebooks for catalyst screening.

It re-implements, in plain Python, the object semantics of a MiMiC-style process model (heat exchangers, valves, calculation blocks, parameters, wiring), so a model exported from such a database can be run, inspected and extended without the vendor runtime.

**Not included:** the plant model itself (`unit400_model.py`) and any plant data. You generate the model from your own export (see below). Scenario settings come from `twin/basis.json` (yours, kept private) or the generic `twin/basis.example.json`.

## Layout
| path | what |
|---|---|
| `twin/unit400_equations.py` | object library: HX (dynamic hold-up), valves, PID, calc, in/out parameters, … |
| `twin/unit400_mimic_expr.py` | translator for the model's calculation-block expression language |
| `twin/generate_model.py` | builds `unit400_model.py` from five extracted JSON files |
| `twin/unit400_twin.py` | runtime corrections + `Twin` class (`set`, `get`, `step`) |
| `twin/catalyst.py`, `catalysts.json` | **M2** catalyst profiles: activity, light-off, linear/Arrhenius kinetics, deactivation |
| `twin/screening.py`, `scenario_screening.py` | **M3** OK / LOW / HOT maps vs jacket temperature, feed, catalyst; time on spec |
| `twin/scenario_catalyst.py` | M2 test run |
| `twin/basis.py`, `basis.example.json` | operating basis (sequence, flows, ratios) |
| `console/` | Station-style web console (Python stdlib server, port 8400): controllers, pumps, interlocks, trends, snapshots, editable layout |
| `notebooks/` | **M1/M2** replay and catalyst comparison; **M3** screening maps |

## Generate the model
Put your extracted files in `data/extracted/` (`unit400_objects.json`, `unit400_registry.json`, `unit400_wiring.json`, `unit400_init.json`, `unit400_constants.json`; structure as read by `generate_model.py`), then:
```
cd twin && python3 generate_model.py ../data/extracted
```

## Run
```
cd twin && python3 scenario_catalyst.py catalysts.json 4        # M2
cd twin && python3 scenario_screening.py quick                   # M3, ~10 min
cd console && python3 u400_console.py 8400                       # console
pip install jupyterlab matplotlib && jupyter lab notebooks/      # notebooks
```

## How the reaction is modelled
Per bed zone: rate ∝ catalyst activity × dwell time (1000 / feed) × f(T), with f = (T − T_START)/(T_IDEAL − T_START) (native, linear) or an Arrhenius law anchored at T_IDEAL. Heat of reaction raises the zone temperature, so the bed either sustains the reaction or loses it (positive feedback). Screening limits (5 % unreacted, 200 °C hot spot) are assumptions, not plant trip settings. Illustrative catalyst profiles are hypothetical.

## Validation
With the author's private plant data, the twin reproduced a real reaction run within about 8 °C rms on the six bed temperatures. Results with `basis.example.json` are generic.

## Licence
MIT — see `LICENSE`. MiMiC is a trademark of its owner; this project is independent and not affiliated with or endorsed by any vendor or plant operator.
