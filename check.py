"""
Self-check. Run it after each step:

    python check.py        all steps
    python check.py 2      only step 2

Steps 1 and 3 are yours. Steps 2 and 4 check the given code (physics, simulator): they pass at once.

Each step prints PASS, TODO (a gap is not filled in yet), FAIL (with what is wrong) or ERROR.
"""
import math
import sys
import traceback

from mission import Reality, diagnose, fly, sensor_alarm, vehicle_alarm
from physics import G, Config, State, events, simulate, step
from twin import RocketTwin, Twin, TwinGraph


def twin_with(change=None) -> RocketTwin:
    """A fresh rocket twin from twins.yaml. change(graph) can edit the graph first (a what-if)."""
    graph = TwinGraph.load()
    if change:
        change(graph)
    return RocketTwin(graph)


def failed(id):
    """A what-if: the twin with this id has status "failed"."""
    def change(graph):
        graph.get(id).state["status"] = "failed"
    return change


def step1():
    # 1. The YAML loads and follows the rules
    try:
        g = TwinGraph.load()
    except ValueError as e:                  # validate() found problems: show them
        raise AssertionError(str(e))

    # 2. Everything on the spec sheet is there, with the right values
    def count(type):
        return len(g.of_type(type))
    for type, n in [("Rocket", 1), ("Stage", 2), ("Engine", 9), ("Tank", 2), ("Sensor", 2),
                    ("FlightComputer", 1), ("Payload", 1), ("LaunchSite", 1)]:
        assert count(type) == n, f"twins.yaml: expected {n} twin(s) of type {type}, found {count(type)}"
    for id in ["rocket", "stage-1", "stage-2", "tank-lox", "tank-rp1", "imu", "altimeter", "fc", "payload", "pad"]:
        assert id in g.twins, f"twins.yaml: no twin with id '{id}' (use the ids of the spec sheet)"
    thrust_kn = sum([e.props.get("thrust_kn", 0) for e in g.of_type("Engine")])
    assert thrust_kn == 9 * 845, f"twins.yaml: total engine thrust is {thrust_kn} kN, expected 9 x 845 kN"
    level_kg = sum([t.state.get("level_kg", 0) for t in g.of_type("Tank")])
    assert level_kg == 400_000, f"twins.yaml: the tanks hold {level_kg} kg, expected 400000 kg (is level_kg in state?)"
    for id, key, value in [("stage-1", "dry_mass_kg", 22200), ("stage-1", "burn_time_s", 150),
                           ("stage-2", "dry_mass_kg", 4000), ("payload", "mass_kg", 2000)]:
        assert g.get(id).props.get(key) == value, f"twins.yaml: {id} props {key} should be {value}"
    for t in g.of_type("Engine") + g.of_type("Sensor") + [g.get("fc")]:
        assert t.state.get("status") == "nominal", f"twins.yaml: {t.id} needs state status: nominal"

    # 3. validate() catches every kind of broken link (small test graphs, made here)
    def problems(*twins):
        return TwinGraph(list(twins)).validate()
    rocket_ok = Twin("r", "Rocket", "R", links={"HAS_STAGE": ["s"]})
    stage = Twin("s", "Stage", "S")
    assert problems(rocket_ok, stage) == [], "validate(): a correct graph should give [] (no problems)"
    assert len(problems(Twin("r", "Rocket", "R", links={"FLIES_TO": ["s"]}), stage)) >= 1, \
        "validate(): an unknown relation (FLIES_TO) is not reported"
    assert len(problems(Twin("x", "Stage", "X", links={"HAS_STAGE": ["s"]}), stage)) >= 1, \
        "validate(): a Stage with HAS_STAGE is not reported (only a Rocket can have it)"
    assert len(problems(Twin("r", "Rocket", "R", links={"HAS_STAGE": ["ghost"]}), stage)) >= 1, \
        "validate(): a link to an id that does not exist is not reported"
    assert len(problems(Twin("r", "Rocket", "R", links={"HAS_STAGE": ["e"]}), Twin("e", "Engine", "E"))) >= 1, \
        "validate(): HAS_STAGE pointing to an Engine is not reported (the target must be a Stage)"
    assert all(isinstance(p, str) for p in problems(Twin("r", "Rocket", "R", links={"HAS_STAGE": ["ghost"]}))), \
        "validate(): return a list of strings (messages)"
    assert g.validate() == [], f"validate(): your twins.yaml has problems: {g.validate()}"

    # 4. out() and inc() follow the links
    rocket = g.get("rocket")
    stage1 = g.get("stage-1")
    stages = [s.id for s in g.out(rocket, "HAS_STAGE")]
    assert stages == ["stage-1", "stage-2"], "out(rocket, HAS_STAGE) is wrong"
    assert len(g.out(stage1, "HAS_ENGINE")) == 9, "stage 1 should have 9 engines"
    assert g.out(g.get("eng-1"), "HAS_ENGINE") == [], "an engine has no engines: expected []"
    sensors = {s.id for s in g.inc(stage1, "MONITORS")}
    assert sensors == {"imu", "altimeter"}, "inc(stage1, MONITORS) is wrong"
    assert g.inc(rocket, "HAS_STAGE") == [], "nothing points to the rocket with HAS_STAGE"


def step2():
    # One step of a small test rocket, compared with a hand calculation
    cfg = Config(thrust_n=20_000, prop_kg=1000, burn_kg_s=10, dry_kg=500, cd=0.3, area_m2=1.0)
    s = step(State(prop=1000), cfg)
    a = (20_000 - 1499 * G) / 1499
    assert math.isclose(s.a, a, rel_tol=1e-6), f"first step: a = {s.a:.4f}, expected {a:.4f}"
    assert math.isclose(s.v, a * 0.1, rel_tol=1e-6), "v is wrong"
    assert math.isclose(s.h, a * 0.01, rel_tol=1e-6), "h is wrong"
    assert math.isclose(s.t, 0.1), "t should advance by DT"

    # Drag must always be against the motion
    s = step(State(h=1000, v=300, prop=0), cfg)
    assert s.q > 0 and s.a < -G, "with v > 0, drag must slow the rocket down (a < -g)"
    s = step(State(h=1000, v=-300, prop=0), cfg)
    assert s.a > -G, "falling (v < 0), drag must push UP (a > -g)"

    # The default rocket, typed in by hand so this step does not need Step 3
    aether = Config(thrust_n=7_605_000, prop_kg=400_000, burn_kg_s=400_000 / 150, dry_kg=28_200,
                    cd=0.3, area_m2=math.pi * 1.85 ** 2)
    ev = events(simulate(aether))
    assert abs(ev["apogee_h"] - 2_240_730) / 2_240_730 < 0.01, \
        f"apogee {ev['apogee_h'] / 1000:.0f} km, expected ~2241 km"
    assert 0 < ev["max_q"] < ev["meco"] < ev["apogee"] < ev["end"], f"events in the wrong order: {ev}"
    assert abs(ev["meco"] - 150) < 1, f"MECO at {ev['meco']:.1f} s, expected ~150 s (the burn time)"


def step3():
    cfg = twin_with().config()
    assert math.isclose(cfg.thrust_n, 9 * 845_000), f"thrust {cfg.thrust_n} N, expected 9 x 845 kN in NEWTONS"
    assert cfg.prop_kg == 400_000, f"propellant {cfg.prop_kg} kg, expected 400000 (two tanks)"
    assert cfg.dry_kg == 28_200, f"dry mass {cfg.dry_kg} kg, expected 22200 + 4000 + 2000 payload"
    assert math.isclose(cfg.burn_kg_s, 400_000 / 150), "burn rate = propellant / burn time"
    assert math.isclose(cfg.area_m2, math.pi * 1.85 ** 2), "area = pi * (d/2)^2"

    eight_engines = twin_with(failed("eng-3")).config().thrust_n
    assert math.isclose(eight_engines, 8 * 845_000), "a failed engine gives no thrust"

    assert twin_with().ready(), "the nominal rocket should be GO"
    assert not twin_with(failed("fc")).ready(), "failed flight computer not detected"
    assert not twin_with(failed("eng-3")).ready(), "failed engine not detected"
    assert not twin_with(failed("altimeter")).ready(), "failed sensor not detected"

    def heavy_payload(graph):
        graph.get("payload").props["mass_kg"] = 600_000
    assert not twin_with(heavy_payload).ready(), \
        "a 600 t payload is too heavy to lift off: should be NO GO (thrust/weight)"


def step4():
    # The rules on their own
    assert sensor_alarm(1000, 5000) and not sensor_alarm(5000, 5100), "sensor_alarm: 5 % rule"
    assert not sensor_alarm(0, 40), "sensor_alarm: ignore the first 50 m"
    assert vehicle_alarm(9000, 10_000) and not vehicle_alarm(9600, 10_000), "vehicle_alarm: 5 % rule"
    assert not vehicle_alarm(500, 900), "vehicle_alarm: only above 1 km"
    assert not vehicle_alarm(5000, math.nan), "vehicle_alarm: no plan (NaN) means no alarm"
    assert diagnose(a=20, fuel_kg=300_000, plan_a=20, plan_fuel_kg=300_000) == "unknown", \
        "nothing wrong -> unknown"

    # Whole flights
    twin = twin_with()
    assert not fly(twin).alarms, "a nominal flight should raise no alarm"
    f = fly(twin, {"freeze": 60})
    assert "sensor" in f.alarms and "vehicle" not in f.alarms, \
        "frozen altimeter: expected a SENSOR alarm only (the rocket itself is fine)"
    for fault in ["thrust", "leak"]:
        f = fly(twin, {fault: 40})
        assert "vehicle" in f.alarms, f"{fault} at T+40 s: no vehicle alarm"
        assert f.diagnosis == fault, f"{fault} at T+40 s diagnosed as '{f.diagnosis}'"
        assert abs(f.replanned_apogee - f.apogee) / f.apogee < 0.03, "re-planned apogee is off"

    # An imperfect reality (hidden thrust delta + sensor noise) must not fool the alarms
    for seed in range(10):
        f = fly(twin, reality=Reality.random(seed))
        assert not f.alarms, f"healthy flight with Reality.random({seed}) raised {f.alarms}"
    f = fly(twin, {"thrust": 40}, Reality.random(0))
    assert f.diagnosis == "thrust", "thrust loss with a noisy reality: not diagnosed as thrust"


STEPS = {1: ("Twin graph", step1), 2: ("Physics (given)", step2), 3: ("Config + go/no-go", step3),
         4: ("Simulator (given)", step4)}

if __name__ == "__main__":
    only = None
    if len(sys.argv) > 1:
        only = int(sys.argv[1])

    for n, (name, check) in STEPS.items():
        if only is not None and n != only:
            continue
        try:
            check()
            print(f"Step {n}  {name:<28} PASS")
        except NotImplementedError as e:
            print(f"Step {n}  {name:<28} TODO  ({e})")
        except AssertionError as e:
            print(f"Step {n}  {name:<28} FAIL  -> {e}")
        except ValueError as e:
            if "twins.yaml" not in str(e):
                raise
            print(f"Step {n}  {name:<28} WAIT  (finish Step 1 first: twins.yaml is not valid yet)")
        except Exception:
            print(f"Step {n}  {name:<28} ERROR")
            traceback.print_exc(limit=-2)

    if only is None:
        print(f"Then    {'Open challenge':<28} no check: see CHALLENGE.md")
