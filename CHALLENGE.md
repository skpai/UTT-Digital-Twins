# Open challenge: catch the failure

Your twin is built: it knows the rocket (Step 1), turns it into numbers (Step 3), and with
`mission.fly()` it is a **simulator** (Step 4). Now use it.

> **The question:** can your twin learn what a normal flight looks like, and catch a failure
> **earlier** than the 5 % rules?

From here on there is no TODO and no `check.py`. **You choose the method and the tools**: a
notebook or scripts, pandas only or scikit-learn, Streamlit or matplotlib. Anything goes, as long
as you can explain it.

---

## The minimum (all four are needed for the demo)

1. **Data.** At least **100 simulated flights**, healthy and faulty. Give each flight its own
   `Reality.random(seed)`, keep the label (which fault, at what time) next to the data, and save
   it to a file.
2. **Your own alert.** A rule, a statistic or a model: your choice. Report three numbers:
   - the false-alarm rate on healthy flights,
   - the miss rate for each fault type,
   - the detection delay (seconds after the fault), next to the delay of the 5 % rules
     (`flight.alarms`).
3. **Data back into the twin.** Record each flight and each alert in the twin graph, for example
   as new twins (`Flight`, `Alert`) linked to the rocket (`Rocket FLEW Flight`,
   `Flight RAISED Alert`), or in the `state` of existing twins. `graph.validate()` must still
   pass. Then answer with a query: *"which flights raised an alert?"*
4. **One screen** that shows a faulty flight: plan against what the sensors saw, and the moment
   your alert fires. A plot in a notebook or an app, as you like.

**Checkpoints** (your Capcom shows the instructor):
- **16:55**: your dataset exists. How many rows, which columns, which labels?
- **17:20**: your alert fires on a thrust loss at T+40.

**Demo (3 minutes per team):** your three numbers, your screen, your twin query, and one thing
that surprised you.

---

## Your toolkit

```python
from mission import fly, Reality
from twin import RocketTwin, TwinGraph, Twin, RELATIONS

twin = RocketTwin.from_file()
f = fly(twin, {"thrust": 40}, Reality.random(seed=1))
```

| `fly(twin, faults_at, reality, t_max)` | |
|---|---|
| `faults_at` | `None` (healthy), `{"thrust": 40}`, `{"leak": 60}`, `{"freeze": 60}`, or with a severity `{"thrust": (40, 0.8)}`, `{"leak": (60, 2.5)}` |
| `reality` | `Reality.random(seed)`: a hidden thrust delta and sensor noise, different for every seed |
| `t_max` | stop the flight early, e.g. `t_max=200` (much faster) |

| What you get back | |
|---|---|
| `f.df` | one row per 0.1 s |
| `f.alarms` | `{"sensor": t, "vehicle": t}`: when the 5 % rules fired (your baseline) |
| `f.diagnosis` | `"thrust"`, `"leak"` or `"unknown"` |
| `f.log` | the mission log |

| Columns of `f.df` | |
|---|---|
| what the twin **sees**: use these | `altimeter`, `imu_h`, `imu_v`, `imu_a`, `tank_t` |
| what the twin **expects**: use these | `plan_h`, `plan_v`, `plan_a`, `plan_fuel_t` |
| the hidden **truth**: do NOT use | `h`, `v`, `a`, `q`, `fuel_t`, `thrust_kn`, `f.reality` |

A real control room never sees the truth, so neither may your alert. You may use it to *check*
your results, never as input.

**A start for the data:**
```python
import pandas as pd

tables = []
for seed in range(3):
    f = fly(twin, {"thrust": 40}, Reality.random(seed), t_max=200)
    df = f.df[f.df.t % 1 == 0].copy()      # one row per second is enough
    df["run_id"] = seed
    df["fault"] = "thrust"
    df["t_fault"] = 40
    tables.append(df)
data = pd.concat(tables)
print(data.shape)
```

**A new twin**, if you go that way: `Twin(id, type, name, props={...}, state={...}, links={...})`.
Put it in `graph.twins`, link to it from another twin's `links`, add the relation to `RELATIONS`,
then check `graph.validate()` (an empty list means all good).

---

## If you do not know where to start

Ideas, not instructions. Pick what you like.

- **Residuals.** "What I see minus what I expect": `(imu_h - plan_h) / plan_h`. Plot it for a
  healthy flight and for a faulty one. Also look at how fast it changes over a few seconds.
- **Learn "normal" from healthy flights only.** Then anything far from normal is suspicious.
- **Split by flight, not by row.** Keep whole flights out for testing. Why does that matter?
- **Choose the threshold** from healthy flights you did not train on, for the false-alarm rate
  you accept (1 %? 5 %?).
- **Be patient for a few seconds.** Alert only when it stays above the threshold k seconds in a
  row, so one noisy reading does not raise an alert.
- **Name the fault.** Can you tell `thrust`, `leak` and `freeze` apart? Better than `diagnose()`?
- **Stress it.** Small faults (`{"thrust": (40, 0.95)}`), late faults, noisier sensors
  (`mission.NOISE["h"] = (0.02, 5.0)`). Which alert breaks first, yours or the 5 % rule?
- **Use the twin for what-ifs.** Fly with a failed engine or a heavy payload: is that a
  "failure" for your alert, or a new normal?

**Traps we have seen:** using the truth columns; splitting by row; reporting results on the
flights you tuned on; making the app look nice before the first dataset exists.
