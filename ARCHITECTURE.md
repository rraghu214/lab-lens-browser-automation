# LabLens — Architecture

## Why a browser agent

Lab-test prices in India are **city-specific, JS-rendered, and hidden behind interaction flows** — city pickers, pincode inputs, search dropdowns, and login walls. A static HTTP fetch retrieves the server-rendered shell (navigation bar, marketing copy) but never the price, because the price is injected by JavaScript after the user selects their city or enters a pincode. A web-search snippet captures a cached or paraphrased price from months ago, not today's live rate. The only reliable path is a real browser that can *see* the page state, *decide* what to click, and *read* the result — exactly what the four-layer cascade provides.

---

## Browser cascade

The cascade escalates through four layers, stopping as soon as a layer succeeds:

```
URL + Goal
   │
   ├─ Layer 1 ──── httpx + trafilatura (no browser)
   │               Cost: $0 · Speed: ~0.5–1 s
   │               Works: static HTML (Metropolis homepage, JustDial)
   │               Fails: JS-rendered content, city-gated prices
   │
   ├─ Layer 2a ─── Playwright + CSS selectors (no LLM)
   │               Cost: $0 · Speed: ~4 s
   │               Works: sites with stable, known CSS classes
   │               Fails: selector timeout
   │
   ├─ Layer 2b ─── Playwright + a11y tree + text LLM
   │               Cost: text tokens · Speed: 5–60 s
   │               Works: dynamic pages, dropdowns, city pickers (1mg, Thyrocare, PharmEasy)
   │               Fails: Cloudflare / canvas-only page with no ARIA labels
   │
   └─ Layer 3 ──── Playwright + set-of-marks screenshot + vision LLM
                   Cost: image tokens (~4–8× text) · Speed: ~30 s/turn
                   Works: anything visible on screen
                   Used: Thyrocare (Cloudflare challenge page)
```

### Expected layer per source

| Source | Expected layer | Reason |
|--------|----------------|--------|
| Metropolis | Layer 1 | Server-rendered HTML; trafilatura extracts full text in <1 s |
| JustDial | Layer 1 | Older site; mostly static HTML |
| 1mg | Layer 2b | JS-rendered; city defaults to Delhi; price requires city selection + search |
| Netmeds | Layer 2b | JS-rendered; location popup gates content |
| PharmEasy | Layer 2b | Pincode-gated dynamic pricing |
| Thyrocare | Layer 2b → Layer 3 | A11y works for search; Cloudflare fires on product pages → vision escalation |
| Google Maps | Layer 2b | JS-heavy; search navigable but price data not in a11y tree |
| Practo | Layer 1 → Layer 2b | Layer 1 returns empty; JS listing requires a11y navigation |

---

## What was not modified

| File | Rule |
|------|------|
| `flow.py` | Core DAG orchestrator — **not touched**. All new behaviour plugs in via the skill catalogue. |
| `browser/skill.py` | Four-layer cascade implementation — **not touched** |
| `browser/driver.py` | A11y driver + set-of-marks driver — **not touched** |
| `browser/dom.py` | Element enumeration JS — **not touched** |
| `browser/highlight.py` | Screenshot annotation with Pillow — **not touched** |
| `browser/client.py` | Browser HTTP client — **not touched** |

---

## What is new

| File | Purpose |
|------|---------|
| `agent_config.yaml` | Browser skill and `lab_distiller` node registered in the skill catalogue |
| `skills/distiller_prompt.md` | Lab-domain normalisation rules: price extraction, `tsh_type` (standard vs. ultrasensitive), backend-lab overlap detection, hidden-fee flagging, review-theme extraction |
| `run_trace.py` | `RunTrace` dataclass — serialisation hub for the entire run; `save()` / `load()` for `replay.json` |
| `mini_gateway.py` | FastAPI proxy on port 8109 wrapping `LLMClient`; replaces the missing `llm_gatewayV9` in this environment; started as a daemon thread by `agent_runner._ensure_gateway()` |
| `agent_runner.py` | Orchestration layer: builds source list, runs cascade per source, calls Distiller, saves `replay.json`; exposes `log_push` callback for real-time UI updates |
| `main.py` | NiceGUI app entry point; three-panel layout; static file mount for screenshots (`/artifacts → ./run_artifacts`) |
| `ui/log_panel.py` | Live agent log with colour-coded prefix convention (▶ cyan, ✓ green, ✗ red, ⚠ yellow) |
| `ui/query_panel.py` | Left panel: query input, locality, options, recent queries |
| `ui/results_panel.py` | Right panel: Compare tab (online + nearby tables, recommended card) + Insights tab (markdown) |
| `ui/replay_viewer.py` | Replay tab: Mermaid DAG, per-source screenshot thumbnails, cost ledger; supports load from path or file upload |

---

## Provider chain

```
Text  : Gemini → Groq → Cerebras → NVIDIA → OpenRouter → GitHub → Ollama (local)
Vision: Gemini → GitHub (gpt-4.1-mini) → Ollama (if vision-capable model loaded)

Minimum viable: GEMINI_API_KEY alone covers both text and vision (free tier)
Best throughput: Cerebras (~3 s/call when available) or Groq
Reliable fallback: Ollama local (gemma4:e4b, 32–67 s/call, unlimited)
```

Rate-limit handling:
- HTTP 429 → 5 s sleep before fallback to next provider
- 2 s inter-turn sleep to keep free-tier RPM within limits
- 20 s heartbeat ticker in the log panel during long provider waits

---

## Key design decisions

**`await` not `create_task` in NiceGUI click handlers.**  
`asyncio.create_task()` spawns a sibling task that has lost NiceGUI's WebSocket client context. Any `log_panel.push()` call from that task is silently dropped. The agent coroutine must be `await`-ed directly inside the click handler to preserve context.

**Upsert-by-provider in the results table.**  
A placeholder row appears immediately when a source starts (so the table fills progressively). When the distiller result arrives, `add_row()` overwrites the placeholder in-place rather than appending a duplicate.

**Mermaid node-ID sanitisation.**  
`Browser:1mg` contains a colon — Mermaid parses it as a node label separator. Node IDs are sanitised (`:`/spaces → `_`) while display labels preserve the original name: `Browser_1mg["Browser: 1mg"]`.

---

## Known limitations

| Limitation | Mitigation |
|-----------|-----------|
| Google Maps blocks headless browsers | `gateway_blocked` is a valid output — demo shows the fallback path to Practo/JustDial |
| Thyrocare Cloudflare on product pages | Layer 3 vision escalation; or navigate via the Jaanch package URL directly |
| Netmeds requires login for location | Pincode entered manually; without login, home-collection prices are unavailable |
| LLM provider rate limits (free tier) | 7-provider fallback chain; Ollama local as unlimited backstop |
| `wall_clock_s` does not hard-cap elapsed | Sources can exceed the wall-clock budget; `asyncio.wait_for()` hard timeout is a future improvement |
| Prices are point-in-time | Refresh the run for updated rates; no caching layer |
