# Build a rocket digital twin

You will build a **digital twin** of a rocket: a virtual copy that knows what the rocket is made of,
predicts how it should fly, watches the real flight through sensors, and tells you when something
goes wrong and what. Then you use your twin as a **simulator**: generate flights, catch failures
your own way, and write what you learn back into the twin (see `CHALLENGE.md`).

```
twins.yaml ──► TwinGraph ──► RocketTwin.config() ──► physics.simulate() ──► plan
 (Step 1)       (Step 1)        (Step 3)               (Step 2)              │
                                                                             ▼
          real rocket + faults ──► sensors ──► compare with plan ──► alarms, diagnosis
                                               (Step 4, given)                │
                                                                             ▼
                                        many flights → your data, your alert, your app
                                                      (the open challenge)
```

Read along in `docs/`: `student_guide.pdf` explains every step (the ideas, the given code, and a
*Your turn* box for each gap) and `workshop_slides.pdf` is the deck shown in the room.
`rocket_twin.ipynb` runs **your** code mission by mission: tables, a drawing of your graph, your
poll, the simulator, and the solutions once they unlock.

## Setup (10 min)

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python check.py                   # Steps 2 and 4 PASS (given code), the others not yet
```
With [uv](https://docs.astral.sh/uv/) instead: `uv venv`, `uv pip install -r requirements.txt`, then
`uv run --no-project --python .venv python check.py`.

Steps 1 and 3 have gaps marked `TODO(...)` in the code, and Step 1 starts with writing
`twins.yaml`. Fill them in, then run `python check.py` (or `python check.py 1` for one step).
A step is done when it says **PASS**.

| File | What it is | Steps |
|---|---|---|
| `twins.yaml` | The data: every part of the rocket and how the parts are linked | 1 |
| `twin.py` | The twin graph and the rocket twin | 1, 3 |
| `physics.py` | How a rocket flies | 2 |
| `mission.py` | The real flight, sensors, alarms, diagnosis (given: the simulator) | 4 |
| `CHALLENGE.md` | The open challenge: data, your own alert, your own app | after 4 |

---

## Step 1: the twin graph (45 min) · `twins.yaml`, `twin.py`

Open `twins.yaml`. It holds a **spec sheet** (a description of the rocket, in comments) and one
entry: the rocket itself. Each entry is one **real** thing: the rocket, a stage, each of the 9
engines, each tank and sensor. `props` are design values, `state` changes during operations, and
`links` are **relations**: `stage-1 HAS_ENGINE eng-1`.

`RELATIONS` at the top of `twin.py` is the **ontology**: which relations exist and which types they
connect. It only knows `HAS_STAGE` so far. `TwinGraph.validate()` checks every link against it, so
that a bad file is refused when it is loaded.

**Do:**
- Write every twin of the spec sheet into `twins.yaml`, with its `props`, `state` and `links`.
- `TODO(1a)` add a rule to `RELATIONS` for every relation you use.
- `TODO(1b)` `validate()`: check every link against `RELATIONS` and return a list of problems
  (unknown relation, wrong type of twin, missing target, wrong type of target).
- `TODO(1c)` `out()` follows a relation forwards, `TODO(1d)` `inc()` follows it backwards.

Run `python check.py 1` often: it tells you what is missing, wrong or misspelled.

**Try:**
```python
from twin import TwinGraph
g = TwinGraph.load()
g.out(g.get("stage-1"), "HAS_ENGINE")     # the 9 engines
g.inc(g.get("stage-1"), "MONITORS")       # the sensors watching stage 1
```
Break `twins.yaml` on purpose (link `stage-1` to `HAS_ENGINE: [tank-lox]`) and load it again.

> **Why a graph?** The twin code never says "9 engines". It asks the graph. Add a 10th engine
> in the YAML and everything follows.

## Step 2: the physics (given) · `physics.py`

The physics is **given, complete**. You do not edit it: it is a function you call. The rocket
flies straight up. Every 0.1 s:

| | |
|---|---|
| mass | `m = dry + propellant` |
| air density | `rho = 1.225 * exp(-h / 8500)` |
| dynamic pressure | `q = 0.5 * rho * v²` |
| drag | `drag = q * Cd * A`, against the motion |
| Newton | `a = (thrust - m*g - drag) / m` |
| Euler step | `v += a*dt`, `h += v*dt` |

`simulate()` returns a DataFrame, one row per step, and `events()` finds Max-Q, MECO (engine
cut-off) and apogee **by querying** it. Read both functions.

**Try:**
```python
import math
from physics import Config, simulate, events
cfg = Config(thrust_n=7_605_000, prop_kg=400_000, burn_kg_s=400_000 / 150,
             dry_kg=28_200, cd=0.3, area_m2=math.pi * 1.85 ** 2)   # Step 3 builds this from the graph
df = simulate(cfg)
df.plot(x="t", y="h")
events(df)
```
*Question:* why does `q` peak at about T+46 s while the rocket is still speeding up?

## Step 3: from graph to numbers, and the go / no-go poll (25 min) · `twin.py`

`RocketTwin` finds its parts by following relations. Now turn them into numbers.

**Do:** `TODO(3a)` `config()`: add up thrust over the engines (a failed engine gives nothing),
propellant over the tanks, dry mass over the stages and the payload. Work in SI units: **kN × 1000 = N**.

**Do:** `TODO(3b)` the poll must read the twins: every engine nominal, every sensor nominal, and
thrust-to-weight > 1.2 (below 1 the rocket cannot even leave the pad).

**Try:** set `eng-3` to `failed` in `twins.yaml`. The thrust drops, the planned apogee drops,
and the poll says NO GO. You changed **data**, not code.

## Step 4: the twin as a simulator (given) · `mission.py`

`mission.py` is **given, complete**. Read the docstring at the top and then `fly()`. "Reality" runs
the same physics, but with faults the twin is **not told about**, a small hidden thrust delta and
noisy sensors. The twin only sees the sensors, and compares them with its plan.

| Fault | What really happens | What a naive check sees |
|---|---|---|
| `freeze` | the altimeter stops updating | altimeter ≠ IMU |
| `thrust` | engines at 70 % (or the level you give) | every sensor agrees: they all see a rocket flying badly |
| `leak` | propellant drains twice as fast (or the rate you give) | every sensor agrees too |

The twin has two simple **rules**, already written: `sensor_alarm` (altimeter and IMU differ by more
than 5 %) and `vehicle_alarm` (the rocket is more than 5 % off the plan). Then `diagnose` names the
fault and `fly()` **re-plans**: it predicts the new apogee from now on. These rules are the
**baseline**: in the challenge, you try to beat them.

```python
from twin import RocketTwin
from mission import fly, Reality
twin = RocketTwin.from_file()
f = fly(twin, {"thrust": 40}, Reality.random(seed=1))    # thrust loss at T+40, imperfect reality
for e in f.log: print(e)
f.df.head()
```

What a flight gives you:

| | |
|---|---|
| `f.df` | one row per 0.1 s (columns below) |
| `f.alarms` | `{"sensor": t, "vehicle": t}`: when each rule fired |
| `f.diagnosis`, `f.replanned_apogee` | what the twin thinks went wrong, and where the rocket will end up |
| `f.log` | the mission log, a list of dicts |

| Columns of `f.df` | |
|---|---|
| what the twin **sees** (use these) | `altimeter`, `imu_h`, `imu_v`, `imu_a`, `tank_t` |
| what the twin **expects** (use these) | `plan_h`, `plan_v`, `plan_a`, `plan_fuel_t` |
| the hidden **truth** (do NOT use) | `h`, `v`, `a`, `q`, `fuel_t`, `thrust_kn`, and `f.reality` |

Faults: `{"thrust": 40}`, `{"leak": 60}`, `{"freeze": 60}`, or with a severity
`{"thrust": (40, 0.8)}`. What-ifs: edit the graph first
(`graph.get("eng-3").state["status"] = "failed"`, then `RocketTwin(graph)`), and fly again.

## Next: the open challenge

Open `CHALLENGE.md`. From here on, **you decide how**: generate the data, build your own alert,
write the results back into the twin, and show it on one screen.

## Stuck? The solutions open during the day

At the end of each mission the instructor writes a password on the board. From then on:

```bash
python unlock.py              # what can be opened, and from what time
python unlock.py 1a           # show the solution of TODO(1a)
python unlock.py 1 --apply    # put every Step 1 solution into the code
python unlock.py twins.yaml --apply   # the full twins.yaml (yours is kept as twins.yaml.mine)
python unlock.py app.py       # a reference file, saved to revealed/app.py
```

In `rocket_twin.ipynb` the same works as `unlock("1a")` or `unlock("1", apply=True)`.

## What to remember

1. A digital twin = **structure** (graph) + **model** (physics) + **state** + **live data** + **comparison**.
2. Structure lives in **data**, not in code: change the YAML and the twin follows.
3. Compare reality with the **plan**, not only sensor with sensor: many faults fool every sensor at once.
4. A twin **predicts**: from the current state it can tell you where you will end up.
5. A twin is also a **simulator**: it gives every reading an expected value, and it can generate
   as many labelled flights as you need to learn from.
