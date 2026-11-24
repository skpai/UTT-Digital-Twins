"""
STEP 4. Fly the REAL rocket and watch it through its sensors.

"Reality" here is the same physics, but with faults the twin is NOT told about. Reality can also
differ a little from the design: the engines give a hidden thrust_factor (e.g. 0.4 % more than
rated) and the sensors are noisy. So even a healthy flight never matches the plan exactly.

The twin only sees reality through its sensors:
    IMU (navigation)   altitude, velocity, acceleration
    altimeter          altitude            (it can FREEZE)
    tank telemetry     propellant left

Before launch the twin computes the PLAN (the expected flight). During the flight it compares:
    sensor alarm  : altimeter and IMU disagree by more than 5 %   -> a SENSOR is broken
    vehicle alarm : IMU altitude and plan differ by more than 5 %  -> the ROCKET has a problem
                    (checked on the way up only: near landing the planned altitude goes to 0,
                    and any tiny difference would look huge)

When the vehicle alarm fires, the twin guesses which fault it is (diagnose) and predicts where
the rocket will now end up (re-plan).
"""
import math
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from physics import Faults, State, events, flight_over, simulate, step

# What the mission log says when a fault starts. The {} is filled with how bad it is.
FAULT_TEXT = {
    "thrust": ("Anomaly: thrust loss", "Engines drop to {:.0%} thrust."),
    "leak": ("Anomaly: propellant leak", "Propellant drains {:.1f}x as fast."),
    "freeze": ("Anomaly: altimeter", "The altimeter stops updating."),
}
# How bad a fault is when you do not say: 70 % thrust left, propellant drains 2x as fast
DEFAULT_SEVERITY = {"thrust": 0.7, "leak": 2.0, "freeze": None}

# Sensor noise when reality is noisy: (relative, minimum)
# e.g. altitude: 0.2 % of the reading, but at least 0.5 m
NOISE = {
    "h": (0.002, 0.5),        # altitude, m
    "v": (0.002, 0.5),        # velocity, m/s
    "a": (0.005, 0.05),       # acceleration, m/s2
    "fuel": (0.002, 50.0),    # propellant, kg
}


def km(m: float) -> str:
    """A distance for humans: "12.3 km", or "850 m"."""
    if abs(m) >= 1000:
        return f"{m / 1000:.1f} km"
    return f"{m:.0f} m"


# =============================================================================
# The three rules of the twin
# =============================================================================
def sensor_alarm(altimeter_h: float, imu_h: float) -> bool:
    """True when the two altitude sensors disagree by more than 5 % (ignore the first 50 m)."""
    if imu_h <= 50:                       # on the pad: too close to 0 to compare
        return False
    difference = abs(altimeter_h - imu_h) / imu_h
    return difference > 0.05


def vehicle_alarm(imu_h: float, planned_h: float) -> bool:
    """True when the rocket is more than 5 % away from the planned altitude (only above 1 km).
    planned_h may be NaN (the real flight lasts longer than the plan): then no alarm."""
    if math.isnan(planned_h):             # no plan for this moment
        return False
    if planned_h <= 1000:                 # too low to compare
        return False
    difference = abs(imu_h - planned_h) / planned_h
    return difference > 0.05


def diagnose(a: float, fuel_kg: float, plan_a: float, plan_fuel_kg: float) -> str:
    """Which fault? Use telemetry only: "leak", "thrust" or "unknown".
    Compare what the sensors say now (a, fuel_kg) with the plan at the same time."""
    # The fingerprints:
    #   A leak: propellant drops much faster than planned (the rocket even gets lighter).
    #   A thrust loss: propellant follows the plan, but acceleration is well below it.
    if fuel_kg < 0.9 * plan_fuel_kg:              # 10 % less propellant than planned
        return "leak"
    if a < plan_a - 0.1 * abs(plan_a):            # 10 % less acceleration than planned
        return "thrust"
    return "unknown"


# =============================================================================
# Reality: how the real rocket differs from its design (hidden from the twin)
# =============================================================================
@dataclass
class Reality:
    thrust_factor: float = 1.0    # the engines really give rated thrust x this (1.004 = +0.4 %)
    noise: bool = False           # True: the sensors add random noise
    seed: int | None = None       # seed of the random numbers: the same seed = the same flight

    @classmethod   # call it on the class:  reality = Reality.random(seed=1)
    def random(cls, seed=None, spread=0.005, noise=True) -> "Reality":
        """A plausible real rocket: thrust about +-0.5 % off rated (never more than +-2 %)."""
        rng = np.random.default_rng(seed)
        factor = rng.normal(1.0, spread)             # a random number around 1.0
        factor = float(np.clip(factor, 0.98, 1.02))  # keep it between 0.98 and 1.02
        return Reality(thrust_factor=factor, noise=noise, seed=seed)


def read(value: float, kind: str, reality: Reality, rng) -> float:
    """What a sensor reports: the true value, plus random noise if reality is noisy."""
    if not reality.noise:
        return value
    relative, minimum = NOISE[kind]
    size = max(relative * abs(value), minimum)
    return value + rng.normal(0.0, size)             # a random error of about that size


# =============================================================================
# One flight
# =============================================================================
@dataclass
class Flight:
    """Everything that happened during one flight."""
    df: pd.DataFrame                  # one row per step: the truth, what the twin saw, the plan
    plan: pd.DataFrame                # the flight the twin expected, computed before launch
    log: list = field(default_factory=list)      # the mission log: a list of dicts
    alarms: dict = field(default_factory=dict)   # "sensor" / "vehicle" / "ml" -> time it fired
    diagnosis: str | None = None                 # "thrust", "leak" or "unknown"
    replanned_apogee: float | None = None        # the new predicted highest point, m
    reality: Reality = field(default_factory=Reality)
    ml_threshold: float | None = None            # used by the reference answer (anomaly.check_flight)

    def note(self, t, title, text, tone="info"):
        """Add one line to the mission log. tone: "info", "danger" or "success"."""
        self.log.append({"t": round(t, 1), "title": title, "text": text, "tone": tone})

    @property   # use it like a value, without (): flight.apogee
    def apogee(self) -> float:
        return float(self.df.h.max())

    @property
    def planned_apogee(self) -> float:
        return float(self.plan.h.max())


# Used when the real flight lasts longer than the plan: nothing to compare with
NO_PLAN = {"t": math.nan, "h": math.nan, "v": math.nan, "a": math.nan, "prop": math.nan}


def fly(twin, faults_at=None, reality=None, t_max=None) -> Flight:
    """Fly the real rocket.

    faults_at : {"thrust": 40} = a thrust loss at T+40 s.
                {"thrust": (40, 0.8)} also says how bad (80 % thrust left; for "leak": 2.5 = 2.5x).
                Kinds: "thrust", "leak", "freeze" (the altimeter freezes).
    reality   : how the real rocket differs from its design (default: a perfect copy).
    t_max     : stop the flight early at this time (makes datasets faster).
    """
    if reality is None:
        reality = Reality()
    rng = np.random.default_rng(reality.seed)        # random numbers for the sensor noise
    waiting = waiting_faults(faults_at)              # faults that have not started yet

    # --- Before launch: what the twin believes, and the plan it computes from it
    cfg = twin.config()
    plan = simulate(cfg)
    plan_rows = plan.to_dict("records")              # the plan as a list of dicts, one per step
    t_planned_apogee = events(plan)["apogee"]

    # --- The real rocket: the same design, but the engines are a little off
    real_cfg = replace(cfg, thrust_n=cfg.thrust_n * reality.thrust_factor)  # a copy, other thrust
    real = State(prop=cfg.prop_kg)                   # on the pad, tanks full
    faults = Faults()                                # nothing wrong yet
    altimeter_h = 0.0
    frozen_h = None                                  # the altimeter value, once it has frozen

    flight = Flight(df=pd.DataFrame(), plan=plan, reality=reality)
    flight.note(0, "Liftoff", f"{twin.name} clears the tower at {twin.site_name}. "
                              f"Planned apogee {km(flight.planned_apogee)}.")
    rows = []
    i = 0                                            # step number, to find the plan row
    while not flight_over(real):
        if t_max is not None and real.t >= t_max:
            break

        # 1. Faults happen in REALITY. The twin is not told.
        for kind in list(waiting):                   # list(...): we delete from it in the loop
            t_start, severity = waiting[kind]
            if real.t < t_start:
                continue                             # not yet
            del waiting[kind]                        # it starts now, only once
            if kind == "thrust":
                faults.thrust = True
                faults.thrust_level = severity
            if kind == "leak":
                faults.leak = True
                faults.leak_rate = severity
            if kind == "freeze":
                frozen_h = altimeter_h               # the altimeter keeps showing this value
            title, text = FAULT_TEXT[kind]
            flight.note(real.t, title, text.format(severity), tone="danger")

        # 2. Reality moves on by one step.
        step(real, real_cfg, faults)

        # 3. The sensors read reality.
        imu_h = read(real.h, "h", reality, rng)
        imu_v = read(real.v, "v", reality, rng)
        imu_a = read(real.a, "a", reality, rng)
        if real.prop > 0:
            tank_kg = max(0.0, read(real.prop, "fuel", reality, rng))
        else:
            tank_kg = 0.0
        if frozen_h is None:
            altimeter_h = read(real.h, "h", reality, rng)
        else:
            altimeter_h = frozen_h

        # 4. The twin compares what it SEES with what it EXPECTS.
        if i < len(plan_rows):
            expected = plan_rows[i]
        else:
            expected = NO_PLAN                       # the real flight lasts longer than the plan
        on_the_way_up = expected["t"] <= t_planned_apogee

        # 4a. Do the two altitude sensors agree?
        if "sensor" not in flight.alarms and sensor_alarm(altimeter_h, imu_h):
            flight.alarms["sensor"] = real.t
            flight.note(real.t, "Cross-check failed",
                        f"Altimeter reads {km(altimeter_h)}, IMU reads {km(imu_h)}. Altimeter flagged.",
                        "danger")

        # 4b. Is the rocket where the plan says? If not: what is wrong, and where will it go?
        if "vehicle" not in flight.alarms and on_the_way_up and vehicle_alarm(imu_h, expected["h"]):
            flight.alarms["vehicle"] = real.t
            flight.note(real.t, "Deviation from plan",
                        f"Altitude {km(imu_h)} vs {km(expected['h'])} planned. Vehicle off nominal.",
                        "danger")
            flight.diagnosis = diagnose(imu_a, tank_kg, expected["a"], expected["prop"])
            replan(flight, cfg, real)

        # 5. Write down this step: the truth, what the twin SAW, and what it EXPECTED.
        rows.append({
            "t": round(real.t, 1),
            # the truth (the twin never sees these)
            "h": real.h, "v": real.v, "a": real.a, "q": real.q,
            "fuel_t": real.prop / 1000, "thrust_kn": real.thrust / 1000,
            # what the twin saw (sensors)
            "altimeter": altimeter_h, "imu_h": imu_h, "imu_v": imu_v, "imu_a": imu_a,
            "tank_t": tank_kg / 1000,
            # what the twin expected (plan)
            "plan_h": expected["h"], "plan_v": expected["v"], "plan_a": expected["a"],
            "plan_fuel_t": expected["prop"] / 1000,
        })
        i = i + 1

    # --- After the flight
    flight.df = pd.DataFrame(rows)
    if t_max is None:                                # a full flight: add the key moments
        add_events_to_log(flight)
    flight.log.sort(key=lambda e: e["t"])            # the log in time order
    return flight


def waiting_faults(faults_at) -> dict:
    """Write every fault the same way, with its severity:
    {"thrust": 40, "leak": (60, 2.5)}  ->  {"thrust": (40, 0.7), "leak": (60, 2.5)}"""
    waiting = {}
    if faults_at is None:
        return waiting
    for kind, when in faults_at.items():
        if isinstance(when, tuple):                  # (time, severity)
            t_start, severity = when
        else:                                        # just a time
            t_start, severity = when, None
        if severity is None:
            severity = DEFAULT_SEVERITY[kind]
        waiting[kind] = (t_start, severity)
    return waiting


def replan(flight: Flight, cfg, real: State):
    """After a diagnosis: run the twin forward from where the rocket is now, with the fault,
    to predict where it will end up."""
    if flight.diagnosis == "unknown":
        flight.note(real.t, "Diagnosis: unknown", "The twin cannot tell what is wrong.", "danger")
        return
    # The twin assumes the textbook severity (70 % thrust, 2x leak): it cannot know more.
    if flight.diagnosis == "thrust":
        fault = Faults(thrust=True)
    else:
        fault = Faults(leak=True)
    ahead = simulate(cfg, fault, start=real)
    flight.replanned_apogee = max(real.h, float(ahead.h.max()))
    flight.note(real.t, f"Diagnosis: {flight.diagnosis}",
                f"New predicted apogee {km(flight.replanned_apogee)} "
                f"(planned {km(flight.planned_apogee)}).", "danger")


def add_events_to_log(flight: Flight):
    """Add Max-Q, MECO, apogee and splashdown of the real flight to the mission log."""
    df = flight.df
    ev = events(df.rename(columns={"thrust_kn": "thrust"}))

    max_q = df.iloc[(df.t - ev["max_q"]).abs().idxmin()]    # the row closest to that time
    meco = df.iloc[(df.t - ev["meco"]).abs().idxmin()]

    flight.note(ev["max_q"], "Max-Q", f"Peak aerodynamic pressure, {max_q.q / 1000:.1f} kPa.")
    flight.note(ev["meco"], "MECO", f"Main engine cut-off at {km(meco.h)}, {meco.v:.0f} m/s.")
    flight.note(ev["apogee"], "Apogee", f"Highest point: {km(ev['apogee_h'])}.")
    flight.note(ev["end"], "Splashdown", f"Flight over at T+{ev['end']:.0f} s.", "success")
