"""LabLens agent runner — coordinates the browser cascade across all sources.

Responsibilities:
  1. Accept goal, locality, options, a RunTrace instance, and a log_push callback.
  2. Build the target URL list from options (online platforms + nearby labs if locality given).
  3. Call BrowserSkill for each source sequentially (not in parallel — rate limit risk).
  4. After each source: append SourceResult + cost_entry to trace, call log_push.
  5. After all sources: call the Distiller LLM, populate trace.dag_plan,
     trace.comparison_rows, trace.insights.
  6. Save replay.json to ./run_artifacts/{run_id}/replay.json.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import time
from typing import Callable, Optional

from llm_client import LLMClient, load_env
from run_trace import RunTrace, SourceResult, TurnRecord
from schemas import NodeSpec

load_env(".env")

# ── Source catalogue ──────────────────────────────────────────────────────────

ONLINE_SOURCES = [
    # layer1: static HTML — trafilatura extracts prices directly from the page
    {"name": "Metropolis", "url": "https://www.metropolisindia.com", "layer_hint": "layer1"},
    # layer2b: JS-rendered — need a11y navigation to reach prices
    {"name": "1mg",        "url": "https://www.1mg.com/labs",         "layer_hint": "layer2b"},
    {"name": "Netmeds",    "url": "https://labs.netmeds.com",         "layer_hint": "layer2b"},
    {"name": "Thyrocare",  "url": "https://www.thyrocare.com",        "layer_hint": "layer2b"},
    {"name": "PharmEasy",  "url": "https://pharmeasy.in/diagnostics", "layer_hint": "layer2b"},
]

NEARBY_SOURCES = [
    {"name": "Google Maps", "url": "https://www.google.com/maps",                       "layer_hint": "layer2b"},
    {"name": "Practo",      "url": "https://www.practo.com/bangalore/diagnostics",      "layer_hint": "layer1"},
    {"name": "JustDial",    "url": "https://www.justdial.com/Bangalore",                "layer_hint": "layer1"},
]

# BrowserOutput.path  →  SourceResult.layer
_PATH_TO_LAYER: dict[str, str] = {
    "extract":       "layer1",
    "deterministic": "layer2a",
    "a11y":          "layer2b",
    "vision":        "layer3",
}

_SKILLS_DIR = pathlib.Path(__file__).parent / "skills"
_DISTILLER_PROMPT = _SKILLS_DIR / "distiller_prompt.md"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _source_goal(source_name: str, goal: str, locality: str, layer_hint: str = "layer1") -> str:
    """Build the per-source goal string for the browser skill.

    For JS-rendered sources (layer_hint="layer2b"), the goal includes interactive
    verbs (navigate, click, select, search) so BrowserSkill._is_useful_extract()
    returns False, forcing escalation past Layer 1 to the a11y driver.

    For static sources (layer_hint="layer1"), the goal is kept verb-free so
    Layer 1 extract succeeds when trafilatura finds useful content.
    """
    loc_part = f" in {locality}" if locality else ""
    if layer_hint == "layer2b":
        city_part = f"Select city '{locality}'" if locality else "Use the default city"
        return (
            f"Navigate {source_name} to find: {goal}{loc_part}. "
            f"{city_part}. Search for the test by name, click through to its detail page. "
            f"Extract: price (INR), home collection availability, turnaround time (hours), "
            f"parameters included (T3/T4/TSH), rating, review count."
        )
    # layer1 — simple goal, no interactive verbs
    return (
        f"Find {goal}{loc_part} on {source_name}. "
        f"Extract: price (INR), home collection availability, turnaround time, "
        f"parameters included (T3/T4/TSH), rating."
    )


def _build_turn_log(actions: list[dict]) -> list[TurnRecord]:
    """Convert BrowserOutput.actions list into TurnRecord objects."""
    records = []
    for step in (actions or []):
        records.append(TurnRecord(
            turn=int(step.get("turn", 0)),
            elements=0,
            thinking="",
            actions=list(step.get("actions") or []),
            outcomes=[str(step.get("outcome", ""))],
            provider="",
            tokens_in=0,
            tokens_out=0,
            latency_ms=0,
        ))
    return records


def _parse_json(text: str) -> dict:
    """Parse JSON from LLM output, stripping markdown fences if present."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.lstrip("`")
        if "\n" in t:
            t = t.split("\n", 1)[1].lstrip()
        if t.endswith("```"):
            t = t[:-3].rstrip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        s, e = t.find("{"), t.rfind("}")
        if s >= 0 and e > s:
            try:
                return json.loads(t[s : e + 1])
            except json.JSONDecodeError:
                pass
    return {}


def _log_actions(actions: list[dict], log_push: Callable) -> None:
    """Log the first few browser actions at turn level."""
    for step in actions[:5]:
        turn_n = step.get("turn", "?")
        for act in (step.get("actions") or []):
            atype = act.get("type", "?")
            mark = act.get("mark")
            val = str(act.get("value", ""))[:40]
            note = act.get("note", "")[:60]
            if atype == "done":
                log_push(f"  Turn {turn_n}: done({act.get('success', '?')}) — {note}")
            elif mark is not None and val:
                log_push(f"  Turn {turn_n}: {atype}([{mark}], {val!r})")
            elif mark is not None:
                log_push(f"  Turn {turn_n}: {atype}([{mark}])")
            else:
                log_push(f"  Turn {turn_n}: {atype}({val!r})")


# ── AgentRunner ───────────────────────────────────────────────────────────────

class AgentRunner:
    def __init__(
        self,
        *,
        log_push: Callable[[str], None],
        on_source_complete: Optional[Callable[[dict], None]] = None,
        options: Optional[dict] = None,
    ):
        self.log_push = log_push
        self.on_source_complete = on_source_complete
        self.options = options or {}
        self._llm = LLMClient.from_env()

    async def run(self, trace: RunTrace, artifacts_root: pathlib.Path) -> None:
        """Run the full cascade for all sources, then call the Distiller."""
        # Ensure the V9 gateway is up so BrowserSkill's a11y/vision layers work.
        self._ensure_gateway()

        goal = trace.goal
        locality = trace.locality

        # Build the sources list based on options
        sources: list[dict] = []
        nearby: list[dict] = []
        if self.options.get("online", True):
            sources = list(ONLINE_SOURCES)
        if self.options.get("nearby", True) and locality:
            nearby = list(NEARBY_SOURCES)
        all_sources = sources + nearby
        nearby_names = {s["name"] for s in nearby}

        self.log_push(f"▶ LabLens run {trace.run_id}")
        self.log_push(f"  Goal: {goal}")
        if locality:
            self.log_push(f"  Locality: {locality}")
        self.log_push(f"  Sources queued: {len(all_sources)}")

        # Import here to avoid circular import at module level (BrowserSkill
        # transitively imports schemas which imports pydantic — fine after env setup).
        from browser.skill import BrowserSkill

        for i, src in enumerate(all_sources):
            src_name: str = src["name"]
            src_url: str = src["url"]
            is_nearby = src_name in nearby_names

            self.log_push(f"▶ Browser: {src_name}")

            # Artifacts directory for this source's screenshots
            safe_name = src_name.replace(" ", "_").lower()
            src_artifacts = artifacts_root / safe_name
            src_artifacts.mkdir(parents=True, exist_ok=True)

            # Polite inter-source delay (rate limit + anti-bot)
            if i > 0:
                await asyncio.sleep(2)

            t0 = time.time()
            try:
                skill = BrowserSkill(
                    artifacts_root=str(src_artifacts),
                    session=trace.run_id,
                    a11y_provider_pin=None,
                )
                layer_hint = src.get("layer_hint", "layer1")
                node = NodeSpec(
                    skill="browser",
                    inputs=[src_url],
                    metadata={
                        "url":  src_url,
                        "goal": _source_goal(src_name, goal, locality, layer_hint),
                    },
                )
                result = await skill.run(node)
            except Exception as exc:
                import httpx as _httpx
                elapsed = time.time() - t0
                self.log_push(f"✗ {src_name} → error: {type(exc).__name__}: {str(exc)[:80]}")
                # If the gateway returned 5xx OR timed out, the cascade attempted the
                # correct layer (Layer 2b driver started, made a /v1/chat call) but the
                # LLM backend failed or stalled. Record layer_hint so attribution is correct.
                if (
                    isinstance(exc, _httpx.HTTPStatusError) and exc.response.status_code >= 500
                ) or isinstance(exc, _httpx.TimeoutException):
                    err_layer = src.get("layer_hint", "layer1")
                else:
                    err_layer = "error"
                trace.sources.append(SourceResult(
                    name=src_name, layer=err_layer, success=False, blocked=False,
                    turn_log=[], extracted={}, tokens_in=0, tokens_out=0,
                    elapsed_s=round(elapsed, 2),
                ))
                trace.cost.append({
                    "source": src_name, "layer": err_layer,
                    "turns": 0, "tok_in": 0, "tok_out": 0,
                    "blocked": False, "elapsed_s": round(elapsed, 2),
                })
                continue

            elapsed = result.elapsed_s or (time.time() - t0)
            out = result.output  # BrowserOutput as dict

            # Determine layer and blocked status.
            # BrowserSkill._pack_error() always sets path="extract", so for failed
            # sources we infer the deepest layer attempted from the error message and
            # the source's layer_hint (which tells us which layers should have been tried).
            blocked = (not result.success) and (result.error_code == "gateway_blocked")
            if blocked:
                layer = "blocked"
            elif result.success:
                raw_path = out.get("path", "extract")
                layer = _PATH_TO_LAYER.get(raw_path, raw_path)
            else:
                err_text = result.error or ""
                # If all layers were exhausted, use the layer_hint to reflect the
                # highest cascade layer that was attempted (even though it failed).
                if "all layers exhausted" in err_text:
                    layer = src.get("layer_hint", "layer1")
                else:
                    raw_path = out.get("path", "extract")
                    layer = _PATH_TO_LAYER.get(raw_path, raw_path)

            turns = int(out.get("turns") or 0)
            actions = list(out.get("actions") or [])
            content = out.get("content") or ""

            # Log outcome
            if blocked:
                self.log_push(f"✗ {src_name} → gateway_blocked")
            elif result.success:
                self.log_push(f"  Layer 1 {'✓' if layer == 'layer1' else '↑ → ' + layer} — {turns} turns")
                _log_actions(actions, self.log_push)
                snippet = content[:120].replace("\n", " ")
                self.log_push(f"✓ {src_name} → {layer} | {turns} turns | {snippet}")
            else:
                self.log_push(f"  Layer: {layer} — failed after {turns} turns")
                self.log_push(f"✗ {src_name} → {layer} failed: {(result.error or '')[:80]}")

            # Build SourceResult
            sr = SourceResult(
                name=src_name,
                layer=layer,
                success=result.success,
                blocked=blocked,
                turn_log=_build_turn_log(actions),
                extracted={"content": content[:8000]} if content else {},
                tokens_in=0,
                tokens_out=0,
                elapsed_s=round(elapsed, 2),
            )
            trace.sources.append(sr)

            # Cost entry
            cost_entry = {
                "source":    src_name,
                "layer":     layer,
                "turns":     turns,
                "tok_in":    0,
                "tok_out":   0,
                "blocked":   blocked,
                "elapsed_s": round(elapsed, 2),
            }
            trace.cost.append(cost_entry)

            # Notify UI: send a placeholder row (Distiller will fill real prices later)
            if self.on_source_complete:
                row: dict = {
                    "provider":        src_name,
                    "type":            "nearby" if is_nearby else "online",
                    "price":           None,
                    "price_note":      "",
                    "home_collection": False,
                    "walk_in":         False,
                    "tat_hours":       None,
                    "rating":          None,
                    "review_count":    None,
                    "parameters":      [],
                    "tsh_type":        "standard",
                    "backend_lab":     "",
                    "notes":           "blocked" if blocked else f"layer: {layer}",
                    "blocked":         blocked,
                }
                self.on_source_complete(row)

        # ── Distiller ─────────────────────────────────────────────────────────
        self.log_push("▶ Distiller: synthesising results")
        distilled = await self._run_distiller(trace)

        trace.dag_plan       = distilled.get("dag_plan", {})
        trace.comparison_rows = distilled.get("comparison_rows", [])
        trace.insights        = distilled.get("insights", "")

        # Push distilled rows to UI (overwrite placeholder rows)
        if self.on_source_complete:
            for row in trace.comparison_rows:
                self.on_source_complete(row)

        rec = distilled.get("recommended", {})
        if rec.get("provider"):
            self.log_push(f"✓ Recommended: {rec['provider']} — {rec.get('reason', '')[:80]}")
        self.log_push("✓ Distiller complete")

        # Save replay
        replay_path = artifacts_root / "replay.json"
        trace.save(str(replay_path))
        self.log_push(f"✓ Saved replay.json → {replay_path}")

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _ensure_gateway() -> None:
        """Ensure llm_gatewayV9 is running on port 8109."""
        from gateway import ensure_gateway
        ensure_gateway()

    async def _run_distiller(self, trace: RunTrace) -> dict:
        """Call the Distiller LLM with all source extracts; return parsed dict."""
        system_prompt = _DISTILLER_PROMPT.read_text(encoding="utf-8")

        raw_sources = [
            {
                "name":      sr.name,
                "layer":     sr.layer,
                "blocked":   sr.blocked,
                "success":   sr.success,
                "extracted": sr.extracted,
            }
            for sr in trace.sources
        ]

        user_content = json.dumps(
            {"goal": trace.goal, "locality": trace.locality, "raw_sources": raw_sources},
            indent=2,
            ensure_ascii=False,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ]

        try:
            result = await self._llm.chat(messages, max_tokens=4096)
            text = result.get("text", "")
            parsed = _parse_json(text)
            if not parsed:
                self.log_push(f"⚠ Distiller returned no valid JSON; raw: {text[:120]}")
                return _fallback_distiller(trace)
            return parsed
        except Exception as exc:
            self.log_push(f"⚠ Distiller error: {type(exc).__name__}: {str(exc)[:100]}")
            return _fallback_distiller(trace)


def _fallback_distiller(trace: RunTrace) -> dict:
    """Generate a minimal valid distiller response when the LLM call fails."""
    source_names = [sr.name for sr in trace.sources]
    nodes = ["Planner"] + [f"Browser:{n}" for n in source_names] + ["Distiller", "Formatter"]
    edges: list[list[str]] = (
        [[f"Planner", f"Browser:{n}"] for n in source_names]
        + [[f"Browser:{n}", "Distiller"] for n in source_names]
        + [["Distiller", "Formatter"]]
    )
    rows = [
        {
            "provider": sr.name, "type": "online",
            "price": None, "price_note": "", "home_collection": False,
            "walk_in": False, "tat_hours": None, "rating": None,
            "review_count": None, "parameters": [], "tsh_type": "standard",
            "backend_lab": "", "notes": "distiller unavailable", "blocked": sr.blocked,
        }
        for sr in trace.sources
    ]
    return {
        "dag_plan":       {"nodes": nodes, "edges": edges},
        "comparison_rows": rows,
        "recommended":    {"provider": "", "reason": "Distiller unavailable — manual review needed."},
        "insights":       "## Distiller unavailable\n\nThe LLM distiller could not be reached. Raw source extracts are available in the Replay tab.",
    }


# ── CLI smoke test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    async def _smoke_test() -> None:
        import sys

        trace = RunTrace(
            goal="Thyroid Profile (T3, T4, TSH) price",
            locality="Koramangala, Bangalore",
        )
        root = pathlib.Path(f"./run_artifacts/{trace.run_id}")
        root.mkdir(parents=True, exist_ok=True)

        def log(line: str) -> None:
            safe = line.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
                sys.stdout.encoding or "utf-8", errors="replace"
            )
            print(safe, flush=True)

        # Limit to Metropolis + 1mg — patch the module-level global directly.
        # When running as __main__, globals() IS the module namespace that run()
        # looks up ONLINE_SOURCES from. DO NOT import agent_runner and patch
        # _ar.ONLINE_SOURCES — that creates a second module object with a separate
        # namespace that run() never reads.
        _smoke_sources = [
            {"name": "Metropolis", "url": "https://www.metropolisindia.com", "layer_hint": "layer1"},
            {"name": "1mg",        "url": "https://www.1mg.com/labs",        "layer_hint": "layer2b"},
        ]
        _orig = globals()["ONLINE_SOURCES"]
        globals()["ONLINE_SOURCES"] = _smoke_sources

        runner = AgentRunner(
            log_push=log,
            options={"online": True, "nearby": False},
        )
        try:
            await runner.run(trace, root)
        finally:
            globals()["ONLINE_SOURCES"] = _orig

        # Verify replay.json
        replay_path = root / "replay.json"
        assert replay_path.exists(), f"replay.json not found at {replay_path}"
        with open(replay_path) as f:
            data = json.load(f)

        source_names = [s["name"] for s in data["sources"]]
        layer_map = {s["name"]: s["layer"] for s in data["sources"]}

        print("\n=== Smoke test result ===")
        print(f"run_id:           {data['run_id']}")
        print(f"sources:          {source_names}")
        print(f"layers:           {layer_map}")
        print(f"comparison_rows:  {len(data['comparison_rows'])}")
        print(f"dag_plan nodes:   {data.get('dag_plan', {}).get('nodes', [])}")
        print(f"insights preview: {data['insights'][:150]}")
        print(f"replay.json:      {replay_path}")

        # Assertions
        assert data["run_id"], "run_id must be non-empty"
        assert "Metropolis" in source_names, "Metropolis must be in sources"
        assert "1mg" in source_names, "1mg must be in sources"
        assert len(data["sources"]) == 2, f"Expected 2 sources, got {len(data['sources'])}"
        assert data.get("dag_plan"), "dag_plan must be populated"
        assert data.get("comparison_rows"), "comparison_rows must be populated"
        # Metropolis: static HTML → must succeed at Layer 1
        assert layer_map.get("Metropolis") == "layer1", (
            f"Expected Metropolis=layer1, got {layer_map.get('Metropolis')}"
        )
        # 1mg: JS-rendered → must attempt at least Layer 2b (cascade escalation shown)
        assert layer_map.get("1mg") in ("layer2b", "layer1"), (
            f"Expected 1mg=layer2b (or layer1 if price found), got {layer_map.get('1mg')}"
        )

        print("\n[OK] All assertions passed — Phase 2 smoke test complete")

    asyncio.run(_smoke_test())
