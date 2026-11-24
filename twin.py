"""
STEP 1. The twin graph: what the rocket IS.
        Every real part of the rocket (each engine, each tank, ...) is one Twin.
        The parts are linked to each other ("stage-1 HAS_ENGINE eng-1").
        All of it is read from the file twins.yaml.

STEP 3. The rocket twin: walk through the graph, add up the numbers the physics needs
        (thrust, mass, ...), and run the go / no-go poll before launch.
"""
import copy
import math
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from physics import G, Config

# The folder this file is in, so twins.yaml is found wherever you run the code from.
HERE = Path(__file__).parent


# =============================================================================
# The ontology: the RULES of the graph.
# Which relations exist, and which type of twin they go FROM and TO.
# Example: "HAS_STAGE" may only go from a Rocket to a Stage.
# =============================================================================
# TODO(1a): add the other six relations. For each one, decide which type of twin it goes
#   FROM and which type it goes TO (read the spec sheet in twins.yaml):
#
#     HAS_ENGINE      HAS_TANK      MONITORS
#     CONTROLLED_BY   CARRIES       LAUNCHED_FROM
#
#   Write each one like the example:   "RELATION_NAME": ("FromType", "ToType"),
RELATIONS = {"HAS_STAGE": ("Rocket", "Stage")}


# =============================================================================
# One twin = one real thing: THIS engine, THIS tank, THIS sensor.
# =============================================================================
@dataclass   # @dataclass writes __init__ for us: Twin(id="eng-1", type="Engine", name="Merlin-1")
class Twin:
    id: str        # unique key, used by links, e.g. "eng-1"
    type: str      # what kind of thing it is, e.g. "Engine"
    name: str      # a readable name, e.g. "Merlin-1"

    # field(default_factory=dict) means: "an empty dict {} if not given".
    props: dict = field(default_factory=dict)   # design values that never change: {"thrust_kn": 845}
    state: dict = field(default_factory=dict)   # values that change: {"status": "nominal"}
    links: dict = field(default_factory=dict)   # relation -> list of twin ids: {"HAS_TANK": ["tank-lox"]}

    def __repr__(self):
        # what print(twin) shows, e.g. <Engine Merlin-1>
        return f"<{self.type} {self.name}>"


# =============================================================================
# The twin graph: all the twins of one rocket, and the links between them.
# =============================================================================
class TwinGraph:

    def __init__(self, twins: list[Twin]):
        # Keep the twins in a dictionary, so we can find one by its id:  self.twins["eng-1"]
        self.twins = {}
        for t in twins:
            self.twins[t.id] = t

    @classmethod   # call it on the class itself:  graph = TwinGraph.load()
    def load(cls, path=HERE / "twins.yaml") -> "TwinGraph":
        """Read twins.yaml, make one Twin per entry, and refuse the file if it breaks the rules."""
        # 1. Read the YAML file into plain Python: a dict with a list of dicts inside.
        text = Path(path).read_text(encoding="utf-8")
        raw = yaml.safe_load(text)

        # 2. Turn every entry into a Twin. Missing fields get a default value.
        twins = []
        for entry in raw["twins"]:
            twin = Twin(
                id=entry["id"],
                type=entry["type"],
                name=entry.get("name", entry["id"]),   # no name in the file: use the id
                props=entry.get("props") or {},        # "or {}": an empty dict if missing
                state=entry.get("state") or {},
                links=entry.get("links") or {},
            )
            twins.append(twin)

        # 3. Build the graph and check it against RELATIONS.
        graph = TwinGraph(twins)
        problems = graph.validate()
        if problems:
            message = "twins.yaml is not valid:"
            for p in problems:
                message += "\n  - " + p
            raise ValueError(message)
        return graph

    def validate(self) -> list[str]:
        """Check every link against RELATIONS. Returns a list of problems (an empty list = all good)."""
        # TODO(1b): check every link of every twin against the rules in RELATIONS.
        #
        #   Loop over every twin t (self.twins.values()), then over every relation it has
        #   (t.links.items() gives pairs: relation name, list of target ids).
        #   For each one, add a message (a string) to a list called problems when:
        #     1. the relation is not in RELATIONS                     -> "eng-1: unknown relation FOO"
        #        (then skip to the next relation: there is no rule to check it against)
        #     2. t has the wrong type for this relation               -> "tank-lox: a Tank cannot have HAS_ENGINE"
        #        RELATIONS["HAS_ENGINE"] is ("Stage", "Engine"): from_type, to_type
        #     3. a target id does not exist in self.twins             -> "stage-1 -HAS_ENGINE-> eng-10: no twin with id 'eng-10'"
        #     4. a target exists but has the wrong type               -> "stage-1 -HAS_ENGINE-> tank-lox: target must be a Engine"
        #   Return the list. An empty list means the file follows all the rules.
        #   Make the messages clear: load() shows them to whoever wrote the YAML.
        return []      # accepts everything, until you write it

    def get(self, id: str) -> Twin:
        """The twin with this id:  graph.get("eng-1")"""
        return self.twins[id]

    def of_type(self, type: str) -> list[Twin]:
        """All twins of one type:  graph.of_type("Engine") -> the 9 engines"""
        result = []
        for t in self.twins.values():
            if t.type == type:
                result.append(t)
        return result

    def out(self, twin: Twin, relation: str) -> list[Twin]:
        """Follow a relation FORWARDS: graph.out(stage1, "HAS_ENGINE") -> the engines of stage 1."""
        # TODO(1c): twin.links.get(relation, []) gives a list of ids. Return the Twin objects.
        raise NotImplementedError('TODO(1c)')

    def inc(self, twin: Twin, relation: str) -> list[Twin]:
        """Follow a relation BACKWARDS: graph.inc(stage1, "MONITORS") -> the sensors watching stage 1."""
        # TODO(1d): return every twin t that has twin.id in t.links.get(relation, []).
        raise NotImplementedError('TODO(1d)')

    def copy(self) -> "TwinGraph":
        """A full copy. Change the copy (a what-if) without touching the original."""
        return copy.deepcopy(self)

    def to_dot(self) -> str:
        """The graph as Graphviz text, for an app:  st.graphviz_chart(graph.to_dot())
        Boxes are coloured by status: green nominal, orange degraded, red failed."""
        colour = {"nominal": "#c8f7c5", "degraded": "#ffe0a3", "failed": "#ffb3b3"}
        lines = ["digraph twins {",
                 'rankdir=LR; node [shape=box, style="rounded,filled", fontsize=10];']
        for t in self.twins.values():                # one box per twin
            fill = colour.get(t.state.get("status"), "#e8eef7")
            lines.append(f'"{t.id}" [label="{t.name}\\n({t.type})", fillcolor="{fill}"];')
        for t in self.twins.values():                # one arrow per link
            for rel, targets in t.links.items():
                for dst in targets:
                    lines.append(f'"{t.id}" -> "{dst}" [label="{rel}", fontsize=8];')
        lines.append("}")
        return "\n".join(lines)


# =============================================================================
# Small helpers for the rocket twin
# =============================================================================

# How much of its thrust an engine gives, depending on its status
ENGINE_FACTOR = {"nominal": 1.0, "degraded": 0.7, "failed": 0.0}


def status(twin: Twin) -> str:
    """The status of a twin. If the YAML does not say, we assume "nominal"."""
    return twin.state.get("status", "nominal")


def first_or_none(items: list):
    """The first item of a list, or None if the list is empty."""
    if len(items) > 0:
        return items[0]
    return None


# =============================================================================
# The rocket twin: ONE rocket, built by following the links of the graph.
# It never hard-codes "9 engines": it asks the graph.
# =============================================================================
class RocketTwin:

    def __init__(self, graph: TwinGraph):
        self.graph = graph

        # The rocket itself (there is exactly one Rocket in the file)
        self.rocket = graph.of_type("Rocket")[0]
        self.name = self.rocket.name

        # Its stages, in order: stage 1 first
        stages = graph.out(self.rocket, "HAS_STAGE")
        self.stages = sorted(stages, key=lambda s: s.props["stage_number"])
        self.stage1 = self.stages[0]

        # What stage 1 is made of, and who watches it
        self.engines = graph.out(self.stage1, "HAS_ENGINE")
        self.tanks = graph.out(self.stage1, "HAS_TANK")
        self.sensors = graph.inc(self.stage1, "MONITORS")    # backwards: sensors point to the stage

        # At most one of each. None if the YAML has none.
        self.computer = first_or_none(graph.out(self.rocket, "CONTROLLED_BY"))
        self.payload = first_or_none(graph.out(self.rocket, "CARRIES"))
        self.site = first_or_none(graph.out(self.rocket, "LAUNCHED_FROM"))
        if self.site:
            self.site_name = self.site.name
        else:
            self.site_name = "the pad"

    @classmethod   # a shortcut:  twin = RocketTwin.from_file()
    def from_file(cls, path=HERE / "twins.yaml") -> "RocketTwin":
        graph = TwinGraph.load(path)
        return RocketTwin(graph)

    def config(self) -> Config:
        """Walk the graph and add things up for the physics (all values in SI units: N, kg, m)."""
        # TODO(3a): build and return a Config:
        #   thrust_n  = sum over engines of thrust_kn * 1000 * ENGINE_FACTOR[engine status]
        #   prop_kg   = sum over tanks of level_kg
        #   burn_kg_s = prop_kg / burn_time_s of stage 1
        #   dry_kg    = dry_mass_kg of every stage + mass_kg of the payload (if any)
        #   cd        = drag_coefficient of the rocket
        #   area_m2   = pi * (diameter_m / 2) ** 2
        raise NotImplementedError('TODO(3a)')

    def go_no_go(self) -> list[dict]:
        """The pre-launch poll. Every check reads the twins. Launch only if all are ok.
        Returns a list of checks like {"check": "Engines", "ok": True, "detail": "9 engines nominal"}."""
        cfg = self.config()

        # Two checks are given as examples
        if self.computer:
            fc = status(self.computer)
        else:
            fc = "missing"
        checks = [
            {"check": "Propellant", "ok": cfg.prop_kg > 0, "detail": f"{cfg.prop_kg / 1000:.0f} t loaded"},
            {"check": "Flight computer", "ok": fc == "nominal", "detail": f"status: {fc}"},
        ]
        # TODO(3b): append three more checks in the same format:
        #   "Engines"       ok if stage 1 has engines and all are "nominal"  (detail: names of bad ones)
        #   "Sensors"       ok if every sensor monitoring stage 1 is "nominal"
        #   "Thrust/weight" ok if thrust / (total mass * G) > 1.2, else it never leaves the pad
        pass
        return checks

    def ready(self) -> bool:
        """True when every check of the poll is ok: GO for launch."""
        for c in self.go_no_go():
            if not c["ok"]:
                return False
        return True
