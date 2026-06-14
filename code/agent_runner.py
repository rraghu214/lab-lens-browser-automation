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
    # Layer 2b: skip city picker (overlay not in a11y tree), go directly to test search
    {"name": "Metropolis",
     "url": "https://www.metropolisindia.com",
     "layer_hint": "layer2b",
     "wall_clock_s": 180.0,
     "extra_hint": (
         "FOLLOW THESE STEPS IN ORDER — DO NOT DEVIATE: "
         "Step 1 (popup): A popup titled 'Get a call back now!' may appear — "
         "click its 'Close' button to dismiss it. "
         "IMPORTANT: After closing the popup, do NOT click the 'Search City' button or any other link. "
         "The city picker that opens from 'Search City' is invisible to you and will waste all your turns. "
         "Step 2 (search directly): Click the 'Search for Tests, Health Checkups' input field and type 'Thyroid Profile'. "
         "A dropdown will appear with test name suggestions — click 'Thyroid Profile - 1' or 'Thyroid Profile Total' from it. "
         "If no dropdown appears after typing, press key('Enter') to search. "
         "Step 3 (price): On the product page, the price (e.g. ₹600) is visible in the PAGE TEXT. "
         "Read it and call done immediately. Do NOT click Book or Add to Cart."
     )},
    # Layer 2b cascade demo: two-field search bar (city LEFT, test RIGHT)
    {"name": "1mg", "url": "https://www.1mg.com/labs", "layer_hint": "layer2b",
     "wall_clock_s": 420.0,
     "extra_hint": (
         "IMPORTANT — IGNORE THE GENERIC SEARCH INSTRUCTIONS ABOVE AND FOLLOW THESE STEPS INSTEAD: "
         "Step 0 (popup): A popup titled 'How can we help?' may appear on any screen — "
         "dismiss it by clicking the X/close button OR clicking anywhere outside the popup (both work). "
         "Step 1 (city): The search bar has TWO separate fields side by side — "
         "LEFT is 'Search city', RIGHT is 'Search tests or full body checkups'. "
         "If the LEFT field already shows 'Bangalore', skip to Step 2. "
         "Otherwise click the LEFT 'Search city' field — a dropdown shows Delhi, Gurgaon, Pune, Bangalore. "
         "Click 'Bangalore' directly from the list. "
         "If you type 'Bangalore' instead, a sub-dropdown appears — click 'Bangalore' (NOT 'Bangalore Rural'). "
         "Step 2 (test search): Click the RIGHT 'Search tests or full body checkups' field and type 'Thyroid Profile'. "
         "A dropdown appears — click 'Thyroid Profile Total (T3, T4 & TSH)' (the first result). "
         "Do NOT press Enter — always click the dropdown item. "
         "Step 3 (price): You land on the product page at 1mg.com/labs/test/.... "
         "Extract the price shown next to 'Test price:' (e.g. ₹629) and call done immediately. "
         "Do NOT click Book or Add to Cart."
     )},
    # disabled: 4-step pincode flow too fragile
    {"name": "Thyrocare", "url": "https://www.thyrocare.com", "layer_hint": "layer2b",
     "slow_load": True, "disabled": True},
    # disabled: slow_load networkidle + Layer3 fallback = 360s total; Practo covers the price
    {"name": "PharmEasy", "url": "https://pharmeasy.in/diagnostics", "layer_hint": "layer2b",
     "slow_load": True, "wall_clock_s": 120.0, "disabled": True},
    # ACTIVE: Akamai wait fix works; price ₹420 visible in search list → call done immediately
    {"name": "Practo", "url_template": "https://www.practo.com/tests?city={city}",
     "layer_hint": "layer2b", "slow_load": True, "wall_clock_s": 360.0},
]

NEARBY_SOURCES = [
    # custom_goal: let the LLM derive an appropriate Maps search query from the user's goal
    {
        "name": "Google Maps",
        "url":  "https://www.google.com/maps/search/thyroid+profile+lab+near+Koramangala+Bangalore",
        "layer_hint": "layer3",
        "force_path": "vision",
        "vision_provider": "ollama",
        "wall_clock_s": 360.0,
        "custom_goal": (
            "The user wants to find labs offering '{goal}' near {locality}. "
            "The page has ALREADY loaded Google Maps search results for 'thyroid profile lab near Koramangala Bangalore'. "
            "Look at the LEFT PANEL showing the list of labs/diagnostic centres. "
            "DO NOT type anything or click into individual result cards. "
            "From the visible results list on the LEFT, extract for the top 3-5 entries: "
            "lab name, star rating, number of reviews, address, and any visible price or hours. "
            "Call done IMMEDIATELY with all extracted entries."
        ),
    },
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

async def _resolve_pincode(locality: str) -> str | None:
    """Resolve a human-readable locality to a 6-digit Indian postal code via
    Nominatim (OpenStreetMap). Returns None if lookup fails or result is ambiguous."""
    import httpx as _httpx
    try:
        async with _httpx.AsyncClient(timeout=8.0, headers={
            "User-Agent": "LabLens/1.0 (lab-test price intelligence)"
        }) as c:
            r = await c.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": locality, "format": "json", "addressdetails": "1", "limit": "1"},
            )
            data = r.json()
            if data and isinstance(data, list):
                postcode = data[0].get("address", {}).get("postcode", "")
                if postcode and postcode.strip().isdigit() and len(postcode.strip()) == 6:
                    return postcode.strip()
    except Exception:
        pass
    return None


def _source_goal(source_name: str, goal: str, locality: str, layer_hint: str = "layer1",
                 *, extra_hint: str = "") -> str:
    """Build the per-source goal string for the browser skill.

    For JS-rendered sources (layer_hint="layer2b"), the goal includes interactive
    verbs (navigate, click, select, search) so BrowserSkill._is_useful_extract()
    returns False, forcing escalation past Layer 1 to the a11y driver.

    For static sources (layer_hint="layer1"), the goal is kept verb-free so
    Layer 1 extract succeeds when trafilatura finds useful content.
    """
    city = locality.split(",")[-1].strip() if locality else ""
    loc_part = f" in {locality}" if locality else ""
    if layer_hint == "layer2b":
        hint_part = f" {extra_hint}" if extra_hint else ""
        # Strip parenthetical details and "price" keyword for a clean search term
        search_term = goal.split("(")[0].replace("price", "").strip()
        city_line = (
            f"If the selected city or location is not {city!r}, change it to {city!r} first."
            if city else ""
        )
        return (
            f"On {source_name}: {city_line} "
            f"Search for '{search_term}' in the test search box. "
            f"After typing the test name, press Enter to submit. "
            f"If pressing Enter has no effect and a dropdown of test names appears, "
            f"click the most relevant item from that dropdown instead. "
            f"CRITICAL: If the price (e.g. ₹420) is already visible in the search results list "
            f"(the element name itself shows the price), call done IMMEDIATELY with that price — "
            f"do NOT click the result to navigate to a detail page. "
            f"Only click into a result if NO price is visible in the search list. "
            f"Extract: price (INR), home collection (yes/no), TAT hours, test parameters, rating. "
            f"Also note the names and any visible prices of 2-3 other relevant results from the search list. "
            f"STOP HERE — call done as soon as you have the price and test details. "
            f"Do NOT click 'Book Now', 'Add to Cart', or proceed to any checkout or booking form.{hint_part}"
        )
    # layer1 — simple goal, no interactive verbs
    return (
        f"Find {goal}{loc_part} on {source_name}. "
        f"Extract: price (INR), home collection availability, turnaround time, "
        f"test parameters included, rating."
    )


def _build_turn_log(actions: list[dict], artifacts_dir: str | None = None) -> list[TurnRecord]:
    """Convert BrowserOutput.actions list into TurnRecord objects."""
    from pathlib import Path
    records = []
    for step in (actions or []):
        turn_n = int(step.get("turn", 0))
        marked = None
        raw = None
        if artifacts_dir:
            d = Path(artifacts_dir)
            # PNGs are nested: browser_XXXX/{a11y|vision}/turn_XX_raw.png — use rglob
            marked_hits = sorted(d.rglob(f"turn_{turn_n:02d}_marked.png"))
            raw_hits    = sorted(d.rglob(f"turn_{turn_n:02d}_raw.png"))
            def _rel(p: Path) -> str:
                return ("run_artifacts/" + "/".join(p.parts[p.parts.index("run_artifacts") + 1:])
                        if "run_artifacts" in p.parts else str(p).replace("\\", "/"))
            if marked_hits:
                marked = _rel(marked_hits[0])
            if raw_hits:
                raw = _rel(raw_hits[0])
        records.append(TurnRecord(
            turn=turn_n,
            elements=0,
            thinking=step.get("thinking", ""),
            actions=list(step.get("actions") or []),
            outcomes=[str(step.get("outcome", ""))],
            provider=step.get("provider", ""),
            tokens_in=int(step.get("tokens_in", 0)),
            tokens_out=int(step.get("tokens_out", 0)),
            latency_ms=int(step.get("latency_ms", 0)),
            raw_png_path=raw,
            marked_path=marked,
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


async def _run_with_ticker(
    coro,
    src_name: str,
    log_push: Callable[[str], None],
    interval: float = 20.0,
):
    """Await a coroutine while logging elapsed time every `interval` seconds.

    Uses asyncio.wait with a timeout so all log_push() calls remain on the
    NiceGUI client-context task — no create_task()/ensure_future on the logger.
    The skill coroutine runs in a sibling task (it doesn't need NiceGUI context).
    """
    t0 = time.time()
    task = asyncio.ensure_future(coro)
    try:
        while not task.done():
            done, _ = await asyncio.wait({task}, timeout=interval)
            if not done:
                elapsed = time.time() - t0
                log_push(f"  ↻ {src_name}: still running... {elapsed:.0f}s elapsed")
        return task.result()  # re-raises if the skill raised
    except Exception:
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        raise


# ── AgentRunner ───────────────────────────────────────────────────────────────

class AgentRunner:
    def __init__(
        self,
        *,
        log_push: Callable[[str], None],
        on_source_complete: Optional[Callable[[dict], None]] = None,
        on_tokens: Optional[Callable[[int], None]] = None,
        options: Optional[dict] = None,
    ):
        self.log_push = log_push
        self.on_source_complete = on_source_complete
        self.on_tokens = on_tokens
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

        # Resolve locality → pincode once (used by sources that need a postal code)
        resolved_pincode: str | None = None
        if locality:
            resolved_pincode = await _resolve_pincode(locality)

        self.log_push(f"▶ LabLens run {trace.run_id}")
        self.log_push(f"  Goal: {goal}")
        if locality:
            pin_note = f" (pincode: {resolved_pincode})" if resolved_pincode else " (pincode: unresolved)"
            self.log_push(f"  Locality: {locality}{pin_note}")
        self.log_push(f"  Sources queued: {len(all_sources)}")

        # Import here to avoid circular import at module level (BrowserSkill
        # transitively imports schemas which imports pydantic — fine after env setup).
        from browser.skill import BrowserSkill

        for i, src in enumerate(all_sources):
            if src.get("disabled"):
                self.log_push(f"⊘ {src['name']} — disabled (skipped)")
                continue
            src_name: str = src["name"]
            # Resolve url_template (e.g. Practo city param) from locality at runtime
            if "url_template" in src:
                city_slug = (locality or "").split(",")[-1].strip().lower().replace(" ", "")
                src_url = src["url_template"].format(city=city_slug)
            else:
                src_url = src["url"]
            is_nearby = src_name in nearby_names

            # Artifacts directory for this source's screenshots
            safe_name = src_name.replace(" ", "_").lower()
            src_artifacts = artifacts_root / safe_name
            src_artifacts.mkdir(parents=True, exist_ok=True)

            # Polite inter-source delay (rate limit + anti-bot)
            if i > 0:
                await asyncio.sleep(2)

            layer_hint = src.get("layer_hint", "layer1")

            if is_nearby and i == len(sources):
                self.log_push("─" * 38)
                self.log_push("  NEARBY LABS")
                self.log_push("─" * 38)

            self.log_push(f"▶ Browser: {src_name}")
            self.log_push(f"  ↳ {src_url}")
            cap_s = src.get("wall_clock_s", 120.0)
            if src.get("force_path") == "vision":
                self.log_push(
                    f"  Layer 3: vision navigation (ollama/{src.get('vision_provider','ollama')}) | max {src.get('max_steps', 10)} steps | cap {cap_s:.0f}s"
                )
            elif layer_hint == "layer2b":
                self.log_push(
                    f"  Layer 2b: LLM-guided navigation | max {src.get('max_steps', 10)} steps | cap {cap_s:.0f}s"
                )
            else:
                self.log_push(f"  Layer 1: static HTML extract (trafilatura)")

            t0 = time.time()
            try:
                skill = BrowserSkill(
                    artifacts_root=str(src_artifacts),
                    session=trace.run_id,
                    a11y_provider_pin=None,       # gateway failover: cerebras(1.5s) → groq → nvidia → ollama
                    vision_provider_pin=src.get("vision_provider"),
                    max_steps_a11y=src.get("max_steps", 10),
                    wall_clock_s=src.get("wall_clock_s", 120.0),  # real cap enforced in skill
                    slow_load=src.get("slow_load", False),
                )
                # custom_goal (e.g. Google Maps) overrides the generic goal builder
                raw_custom = src.get("custom_goal", "")
                if raw_custom:
                    src_goal = raw_custom.format(goal=goal, locality=locality or "")
                else:
                    # Combine source-level extra_hint with pincode hint if applicable
                    extra = src.get("extra_hint", "")
                    if src.get("needs_pincode") and resolved_pincode:
                        extra += (
                            f" The Bangalore pincode is {resolved_pincode} — "
                            f"when a PIN Code input field appears, type {resolved_pincode} and click the Check/Confirm button."
                        )
                    src_goal = _source_goal(src_name, goal, locality, layer_hint, extra_hint=extra.strip())
                node_meta: dict = {"url": src_url, "goal": src_goal}
                if src.get("force_path"):
                    node_meta["force_path"] = src["force_path"]
                node = NodeSpec(
                    skill="browser",
                    inputs=[src_url],
                    metadata=node_meta,
                )
                if layer_hint == "layer2b":
                    self.log_push(f"  Goal: {src_goal[:90]}...")
                result = await _run_with_ticker(skill.run(node), src_name, self.log_push, interval=20.0)
            except Exception as exc:
                import httpx as _httpx
                elapsed = time.time() - t0
                if isinstance(exc, _httpx.HTTPStatusError):
                    _code = exc.response.status_code
                    _msg = f"gateway HTTP {_code} — LLM providers rate-limited or unavailable"
                elif isinstance(exc, _httpx.TimeoutException):
                    _msg = f"timeout after {elapsed:.0f}s — gateway or site unresponsive"
                elif isinstance(exc, asyncio.CancelledError):
                    _msg = f"cancelled after {elapsed:.0f}s"
                else:
                    _msg = f"{type(exc).__name__}: {str(exc)[:80]}"
                self.log_push(f"✗ {src_name} → {_msg} ({elapsed:.0f}s total)")
                # If the gateway returned 5xx OR timed out, the cascade attempted the
                # correct layer (Layer 2b driver started, made a /v1/chat call) but the
                # LLM backend failed or stalled. Record layer_hint so attribution is correct.
                if (
                    isinstance(exc, _httpx.HTTPStatusError) and exc.response.status_code >= 500
                ) or isinstance(exc, _httpx.TimeoutException):
                    err_layer = src.get("layer_hint", "layer1")
                else:
                    err_layer = "error"
                # Recover partial turn/token data attached by BrowserSkill._drive()
                # when the exception occurred mid-run (e.g. gateway 503 after N turns).
                _partial = getattr(exc, '_partial_steps', [])
                _p_turns   = len(_partial)
                _p_tok_in  = sum(int(getattr(s, 'tokens_in',  0)) for s in _partial)
                _p_tok_out = sum(int(getattr(s, 'tokens_out', 0)) for s in _partial)
                _p_tlog = _build_turn_log([
                    {
                        "turn":       getattr(s, "turn",       0),
                        "thinking":   getattr(s, "thinking",   ""),
                        "actions":    getattr(s, "actions",    []),
                        "outcome":    getattr(s, "outcome",    ""),
                        "provider":   getattr(s, "provider",   ""),
                        "tokens_in":  getattr(s, "tokens_in",  0),
                        "tokens_out": getattr(s, "tokens_out", 0),
                        "latency_ms": getattr(s, "latency_ms", 0),
                    }
                    for s in _partial
                ], artifacts_dir=str(src_artifacts))
                trace.sources.append(SourceResult(
                    name=src_name, layer=err_layer, success=False, blocked=False,
                    turn_log=_p_tlog, extracted={}, tokens_in=_p_tok_in, tokens_out=_p_tok_out,
                    elapsed_s=round(elapsed, 2),
                ))
                trace.cost.append({
                    "source": src_name, "layer": err_layer,
                    "turns": _p_turns, "tok_in": _p_tok_in, "tok_out": _p_tok_out,
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

            turns   = int(out.get("turns")   or 0)
            tok_in  = int(out.get("tok_in")  or 0)
            tok_out = int(out.get("tok_out") or 0)
            actions = list(out.get("actions") or [])
            content = out.get("content") or ""
            if self.on_tokens and (tok_in + tok_out) > 0:
                self.on_tokens(tok_in + tok_out)

            # Log outcome
            layer_path_str = out.get("layer_path", "")
            if blocked:
                self.log_push(f"✗ {src_name} → gateway_blocked")
            elif result.success:
                self.log_push(f"  Layer 1 {'✓' if layer == 'layer1' else '↑ → ' + layer} — {turns} turns")
                if layer_path_str:
                    self.log_push(f"  Path: {layer_path_str}")
                _log_actions(actions, self.log_push)
                snippet = content[:120].replace("\n", " ")
                self.log_push(f"✓ {src_name} → {layer} | {turns} turns | {snippet}")
            else:
                self.log_push(f"  Layer: {layer} — failed after {turns} turns")
                if layer_path_str:
                    self.log_push(f"  Path: {layer_path_str}")
                self.log_push(f"✗ {src_name} → {layer} failed: {(result.error or '')[:80]}")

            # Build SourceResult
            sr = SourceResult(
                name=src_name,
                layer=layer,
                success=result.success,
                blocked=blocked,
                turn_log=_build_turn_log(actions, artifacts_dir=str(src_artifacts)),
                extracted={"content": content[:8000]} if content else {},
                tokens_in=tok_in,
                tokens_out=tok_out,
                elapsed_s=round(elapsed, 2),
                layer_path=layer_path_str,
            )
            trace.sources.append(sr)

            # Cost entry
            cost_entry = {
                "source":    src_name,
                "layer":     layer,
                "turns":     turns,
                "tok_in":    tok_in,
                "tok_out":   tok_out,
                "blocked":   blocked,
                "elapsed_s": round(elapsed, 2),
            }
            if layer_path_str:
                cost_entry["layer_path"] = layer_path_str
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
        # Override type only for known source names — individual nearby labs
        # (e.g. "Orange Health Labs" from Google Maps) keep the distiller's type.
        _online_names = {s["name"] for s in ONLINE_SOURCES}
        if self.on_source_complete:
            for row in trace.comparison_rows:
                row = dict(row)
                if row.get("provider") in _online_names:
                    row["type"] = "online"
                elif row.get("provider") in nearby_names:
                    row["type"] = "nearby"
                # else: trust distiller (e.g. individual labs from Google Maps)
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
            if self.on_tokens:
                self.on_tokens(result.get("tokens_in", 0) + result.get("tokens_out", 0))
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
    _nearby = {s["name"] for s in NEARBY_SOURCES}
    source_names = [sr.name for sr in trace.sources]
    nodes = ["Planner"] + [f"Browser:{n}" for n in source_names] + ["Distiller", "Formatter"]
    edges: list[list[str]] = (
        [[f"Planner", f"Browser:{n}"] for n in source_names]
        + [[f"Browser:{n}", "Distiller"] for n in source_names]
        + [["Distiller", "Formatter"]]
    )
    rows = [
        {
            "provider": sr.name,
            "type": "nearby" if sr.name in _nearby else "online",
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
