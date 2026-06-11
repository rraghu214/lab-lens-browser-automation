from dataclasses import dataclass, field, asdict
from typing import Optional
import json, uuid, datetime


@dataclass
class TurnRecord:
    turn:          int
    elements:      int
    thinking:      str
    actions:       list[dict]
    outcomes:      list[str]
    provider:      str
    tokens_in:     int
    tokens_out:    int
    latency_ms:    int
    raw_png_path:  Optional[str] = None
    marked_path:   Optional[str] = None


@dataclass
class SourceResult:
    name:          str
    layer:         str           # "layer1" | "layer2a" | "layer2b" | "layer3" | "blocked"
    success:       bool
    blocked:       bool
    turn_log:      list[TurnRecord]
    extracted:     dict          # raw extracted data before Distiller
    tokens_in:     int
    tokens_out:    int
    elapsed_s:     float


@dataclass
class RunTrace:
    run_id:          str   = field(default_factory=lambda: uuid.uuid4().hex[:8])
    goal:            str   = ""
    locality:        str   = ""
    started:         str   = field(default_factory=lambda: datetime.datetime.now().isoformat())
    log_lines:       list[str]          = field(default_factory=list)
    sources:         list[SourceResult] = field(default_factory=list)
    cost:            list[dict]         = field(default_factory=list)
    dag_plan:        dict               = field(default_factory=dict)
    comparison_rows: list[dict]         = field(default_factory=list)
    insights:        str                = ""

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load(cls, path: str) -> "RunTrace":
        with open(path) as f:
            data = json.load(f)
        data["sources"] = [
            SourceResult(
                **{**s, "turn_log": [TurnRecord(**t) for t in s["turn_log"]]}
            )
            for s in data["sources"]
        ]
        return cls(**data)
