"""
STEP 2. Physics: how the rocket BEHAVES.

A rocket flying straight up. We move it forward in small steps of DT = 0.1 s.
At every step:

    mass         = dry mass + propellant left
    thrust       = engine thrust while there is propellant, else 0
    air density  = gets thinner with altitude
    q            = 0.5 * air density * v^2           (dynamic pressure)
    drag         = q * Cd * A                         (always against the motion)
    acceleration = (thrust - weight - drag) / mass    (Newton: F = m a)
    v            = v + acceleration * DT
    h            = h + v * DT
"""
import math
from copy import copy
from dataclasses import asdict, dataclass

import pandas as pd

G = 9.81          # gravity, m/s2
DT = 0.1          # time step, s
RHO0 = 1.225      # air density at sea level, kg/m3
H_SCALE = 8500.0  # the air is ~3x thinner every 8500 m, m
MAX_T = 2400.0    # stop the simulation here whatever happens, s


# @dataclass writes __init__ for us:  Config(thrust_n=7_605_000, prop_kg=400_000, ...)
@dataclass
class Config:
    """The numbers the physics needs. Built from the twin graph in twin.py (Step 3)."""
    thrust_n: float    # total thrust, N
    prop_kg: float     # propellant loaded, kg
    burn_kg_s: float   # propellant burned per second, kg/s
    dry_kg: float      # everything that is not propellant, kg
    cd: float          # drag coefficient
    area_m2: float     # frontal area, m2


@dataclass
class Faults:
    """Things that can go wrong with the VEHICLE (the sensor fault lives in mission.py)."""
    thrust: bool = False        # True: the engines give only thrust_level of their thrust
    leak: bool = False          # True: propellant drains leak_rate times as fast
    thrust_level: float = 0.7   # how bad a thrust loss is (0.7 = 70 % thrust left)
    leak_rate: float = 2.0      # how bad a leak is (2.0 = twice as fast)


@dataclass
class State:
    """Where the rocket is right now. State() = on the pad, everything 0."""
    t: float = 0.0        # time since liftoff, s
    h: float = 0.0        # altitude, m
    v: float = 0.0        # velocity, m/s (positive = up)
    a: float = 0.0        # acceleration, m/s2
    prop: float = 0.0     # propellant left, kg
    q: float = 0.0        # dynamic pressure, Pa
    thrust: float = 0.0   # thrust this step, N


def air_density(h: float) -> float:
    """Air density at altitude h (m)."""
    if h < 0:
        h = 0
    return RHO0 * math.exp(-h / H_SCALE)


def step(s: State, cfg: Config, faults: Faults | None = None) -> State:
    """Move the rocket forward by DT seconds. Changes the state s and returns it.
    faults: what is wrong with the rocket (None = nothing)."""
    if faults is None:
        faults = Faults()

    # 1. Engines and propellant
    thrust = cfg.thrust_n
    burn_rate = cfg.burn_kg_s
    if faults.thrust:
        thrust = thrust * faults.thrust_level
    if faults.leak:
        burn_rate = burn_rate * faults.leak_rate

    if s.prop > 0.5:                          # still burning
        s.thrust = thrust
        s.prop = max(0.0, s.prop - burn_rate * DT)
    else:                                     # tanks empty: engines off
        s.thrust = 0.0

    # 2. Forces and motion
    m = cfg.dry_kg + s.prop
    s.q = 0.5 * air_density(s.h) * s.v ** 2
    drag = s.q * cfg.cd * cfg.area_m2
    if s.v < 0:
        drag = -drag
    s.a = (s.thrust - m * G - drag) / m
    s.v = s.v + s.a * DT
    s.h = s.h + s.v * DT
    s.t = s.t + DT

    # 3. The ground stops us
    if s.h < 0:
        s.h = 0.0
        s.v = max(0.0, s.v)
    return s


def flight_over(s: State) -> bool:
    """Back on the ground with empty tanks, or out of time."""
    landed = s.t > 1 and s.h <= 0 and s.prop <= 0.5
    return landed or s.t > MAX_T


def simulate(cfg: Config, faults: Faults | None = None, start: State | None = None) -> pd.DataFrame:
    """Fly a whole flight. One row per step: t, h, v, a, prop, q, thrust.
    `start` lets you continue from a given state (used to re-plan in Step 4)."""
    if start is None:
        s = State(prop=cfg.prop_kg)
    else:
        s = copy(start)                       # a copy: do not change the caller's state
    # Step again and again until the flight is over. Keep every state as one row of a table.
    rows = []
    while True:
        step(s, cfg, faults)
        rows.append(asdict(s))                # the state as a dict: one row of the table
        if flight_over(s):
            break
    return pd.DataFrame(rows)


def events(df: pd.DataFrame) -> dict:
    """Key moments of a flight, found by querying the data:
        apogee  : time of the highest point                       (largest h)
        apogee_h: the highest altitude, m
        max_q   : time of peak dynamic pressure on the way UP     (largest q before apogee)
        meco    : main engine cut-off                             (first row where thrust == 0)
        end     : last time in the table
    """
    # apogee: the row with the largest altitude, and its time
    t_apogee = df.t[df.h.idxmax()]

    # max-Q: the largest dynamic pressure, on the way up only
    ascent = df[df.t <= t_apogee]
    t_max_q = ascent.t[ascent.q.idxmax()]

    # MECO: the first time the engines are off
    engines_off = df.t[df.thrust == 0]
    if len(engines_off) > 0:
        t_meco = engines_off.iloc[0]
    else:
        t_meco = df.t.iloc[-1]               # still burning when the table ends

    return {
        "max_q": float(t_max_q),
        "meco": float(t_meco),
        "apogee": float(t_apogee),
        "apogee_h": float(df.h.max()),
        "end": float(df.t.iloc[-1]),
    }
