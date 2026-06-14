# main.py
import asyncio
import pathlib
from nicegui import ui, app

from ui.query_panel   import QueryPanel
from ui.log_panel     import LogPanel
from ui.results_panel import ResultsPanel
from ui.replay_viewer import ReplayViewer

app.add_static_files("/artifacts", "./run_artifacts")

_THEME_CSS = """
<style>
/* ── CSS variables — light (default, no class needed) ─────────────────── */
:root {
  --ll-bg:          #f6f8fa;
  --ll-surface:     #ffffff;
  --ll-surface-dim: #f0f3f5;
  --ll-border:      #d0d7de;
  --ll-text:        #1f2328;
  --ll-text2:       #57606a;
  --ll-text3:       #6e7781;
  --ll-input-bg:    #ffffff;
  --ll-accent:      #0969da;
  --ll-tag-bg:      rgba(0,0,0,0.04);
  --ll-log-bg:      #f6f8fa;
  --ll-log-text:    #374151;
}
/* ── CSS variables — dark (opt-in via body.ll-dark) ───────────────────── */
body.ll-dark {
  --ll-bg:          #0d1117;
  --ll-surface:     #0d1117;
  --ll-surface-dim: #010409;
  --ll-border:      #21262d;
  --ll-text:        #e2e8f0;
  --ll-text2:       #8b949e;
  --ll-text3:       #484f58;
  --ll-input-bg:    #161b22;
  --ll-accent:      #1f6feb;
  --ll-tag-bg:      rgba(255,255,255,0.04);
  --ll-log-bg:      #0a0e14;
  --ll-log-text:    #9ca3af;
}
/* ── Global Quasar overrides ───────────────────────────────────────────── */
body, .q-page, .nicegui-content { background: var(--ll-bg) !important; }
/* Input field colours */
.q-field__native, .q-field__input, .q-field__native textarea {
  color: var(--ll-text) !important;
  caret-color: var(--ll-accent) !important;
}
.q-field__native::placeholder, .q-field__input::placeholder { color: var(--ll-text3) !important; }
.q-field--outlined .q-field__control { border-color: var(--ll-border) !important; background: var(--ll-input-bg) !important; }
.q-field--outlined:hover .q-field__control { border-color: var(--ll-accent) !important; }
.q-field--focused .q-field__control { border-color: var(--ll-accent) !important; box-shadow: 0 0 0 3px rgba(31,111,235,0.12) !important; }
.q-field__label { color: var(--ll-text3) !important; }
/* Checkbox */
.q-checkbox__label { color: var(--ll-text) !important; font-size: 13px !important; }
.q-checkbox__bg { border-color: var(--ll-text3) !important; }
.q-checkbox__inner--truthy .q-checkbox__bg,
.q-checkbox__inner--indet .q-checkbox__bg  { background: var(--ll-accent) !important; border-color: var(--ll-accent) !important; }
/* Table */
.q-table { background: transparent !important; }
.q-table__container { background: transparent !important; }
.q-table th { color: var(--ll-text3) !important; border-color: var(--ll-border) !important; font-size: 11px !important; letter-spacing: 0.06em !important; text-transform: uppercase !important; font-weight: 600 !important; }
.q-table td { color: var(--ll-text) !important; border-color: var(--ll-border) !important; font-size: 13px !important; }
.q-table tbody tr:hover td { background: rgba(31,111,235,0.06) !important; }
/* Tabs */
.q-tab { color: var(--ll-text2) !important; font-size: 13px !important; font-weight: 500 !important; }
.q-tab--active { color: var(--ll-text) !important; font-weight: 600 !important; }
.q-tab__indicator { background: var(--ll-accent) !important; }
.q-tab-panels, .q-panel { background: transparent !important; }
/* Misc */
.q-separator { background: var(--ll-border) !important; opacity: 1 !important; }
.q-markdown p, .q-markdown li { color: var(--ll-text) !important; line-height: 1.7 !important; }
.q-markdown h2, .q-markdown h3 { color: var(--ll-text) !important; }
/* Log panel — follows the theme via CSS variables */
.nicegui-log, .ll-log-wrap { background: var(--ll-log-bg) !important; }
.nicegui-log, .nicegui-log * { color: var(--ll-log-text) !important; font-size: 11.5px !important; line-height: 1.65 !important; }
/* Resize handles between panels */
.ll-resize-h {
  width: 4px;
  background: var(--ll-border);
  cursor: col-resize;
  flex-shrink: 0;
  transition: background 0.15s;
  z-index: 10;
  position: relative;
}
.ll-resize-h:hover, .ll-resize-h.ll-dragging { background: var(--ll-accent); }
</style>
<script>
// :root defaults to light mode, so nothing to do for most users.
// Only add ll-dark if the user previously opted into dark mode.
(function(){
  if (localStorage.getItem('ll-theme') === 'dark') {
    document.addEventListener('DOMContentLoaded', function(){
      document.body.classList.add('ll-dark');
    });
  }
})();

// ── Panel resize handles ──────────────────────────────────────────────────
(function(){
  var drag = null, startX = 0, startW = 0, leftEl = null;
  document.addEventListener('mousedown', function(e){
    var h = e.target.closest('.ll-resize-h');
    if (!h) return;
    drag = h;
    startX = e.clientX;
    leftEl = h.previousElementSibling;
    startW = leftEl ? leftEl.getBoundingClientRect().width : 0;
    h.classList.add('ll-dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
  });
  document.addEventListener('mousemove', function(e){
    if (!drag || !leftEl) return;
    var w = Math.max(120, startW + (e.clientX - startX));
    leftEl.style.width = w + 'px';
    leftEl.style.minWidth = w + 'px';
    leftEl.style.flex = 'none';
  });
  document.addEventListener('mouseup', function(){
    if (!drag) return;
    drag.classList.remove('ll-dragging');
    drag = null; leftEl = null;
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  });
})();
</script>
"""

@ui.page("/")
async def index():
    dark = ui.dark_mode()
    dark.disable()          # light mode is the default
    ui.add_head_html(_THEME_CSS)

    # ── Track theme state (light = True by default) ─────────────────────
    is_light = [True]

    async def toggle_theme():
        is_light[0] = not is_light[0]
        if is_light[0]:     # just switched → light
            dark.disable()
            await ui.run_javascript(
                "document.body.classList.remove('ll-dark'); localStorage.removeItem('ll-theme');"
            )
            theme_btn.props("icon=dark_mode")
            theme_btn.tooltip("Switch to dark mode")
        else:               # just switched → dark
            dark.enable()
            await ui.run_javascript(
                "document.body.classList.add('ll-dark'); localStorage.setItem('ll-theme','dark');"
            )
            theme_btn.props("icon=light_mode")
            theme_btn.tooltip("Switch to light mode")

    # ── Header ──────────────────────────────────────────────────────────
    with ui.row().classes("w-full items-center gap-3 px-5 py-3 border-b").style(
        "background: var(--ll-surface-dim); border-color: var(--ll-border); flex-shrink: 0;"
    ):
        ui.label("🔬").style("font-size: 20px; line-height: 1;")
        with ui.column().classes("gap-0"):
            ui.label("LabLens").style(
                "font-size: 16px; font-weight: 700; color: #58a6ff; "
                "line-height: 1.2; letter-spacing: -0.02em;"
            )
            ui.label("Lab test price intelligence").style(
                "font-size: 11px; color: var(--ll-text3);"
            )
        ui.space()
        theme_btn = ui.button(on_click=toggle_theme).props(
            "flat round dense icon=dark_mode"   # moon = currently light, click for dark
        ).style("color: var(--ll-text3);").tooltip("Switch to dark mode")
        ui.link("GitHub ↗", "https://github.com/rraghu214/lablens").style(
            "font-size: 12px; color: var(--ll-text3); text-decoration: none;"
        )

    # ── Three-panel layout ───────────────────────────────────────────────
    # align-items: stretch makes every child column fill the row height.
    # Each column needs height: 100% so flex children inside can fill it.
    with ui.row().classes("w-full gap-0").style(
        "height: calc(100vh - 52px); overflow: hidden; align-items: stretch;"
    ):
        with ui.column().classes("overflow-y-auto").style(
            "width: 260px; min-width: 120px; height: 100%; "
            "background: var(--ll-surface);"
        ):
            query_panel = QueryPanel()

        ui.element("div").classes("ll-resize-h")

        with ui.column().classes("").style(
            "width: 320px; min-width: 120px; height: 100%; overflow: hidden; "
            "background: var(--ll-log-bg);"
        ):
            log_panel = LogPanel()

        ui.element("div").classes("ll-resize-h")

        with ui.column().classes("flex-1 overflow-y-auto").style(
            "height: 100%; min-width: 200px; background: var(--ll-surface);"
        ):
            results_panel = ResultsPanel()

    # Wire: run search
    query_panel.on_run(
        lambda goal, locality, opts: run_agent(goal, locality, opts, log_panel, results_panel, query_panel)
    )
    # Wire: stop running search
    query_panel.on_stop(lambda: stop_agent())
    # Wire: load a previous run from the Recent list
    query_panel.on_load_replay(
        lambda run_id: load_replay_from_disk(run_id, log_panel, results_panel)
    )


_current_run_task: "asyncio.Task | None" = None


def stop_agent() -> None:
    global _current_run_task
    if _current_run_task and not _current_run_task.done():
        _current_run_task.cancel()


async def run_agent(goal, locality, opts, log_panel, results_panel, query_panel):
    import asyncio
    global _current_run_task
    from agent_runner import AgentRunner
    from run_trace import RunTrace
    import pathlib

    log_panel.clear()
    results_panel.clear()
    log_panel.set_status("RUNNING")
    query_panel.set_running(True)
    ui.notify(f"Search started: {goal[:60]}", type="info", position="top-right", timeout=2000)

    trace = RunTrace(goal=goal, locality=locality)
    artifacts_root = pathlib.Path(f"./run_artifacts/{trace.run_id}")
    artifacts_root.mkdir(parents=True, exist_ok=True)

    def _log(line: str) -> None:
        log_panel.push(line)
        trace.log_lines.append(line)

    try:
        runner = AgentRunner(
            log_push=_log,
            on_source_complete=results_panel.add_row,
            on_tokens=log_panel.add_tokens,
            options=opts,
        )
        _current_run_task = asyncio.ensure_future(runner.run(trace, artifacts_root))
        await _current_run_task
        results_panel.set_insights(trace.insights)
        results_panel.set_replay(trace)
        log_panel.set_status("COMPLETE")
        ui.notify("Search complete", type="positive", position="top-right", timeout=3000)
        query_panel.refresh_recent()
    except asyncio.CancelledError:
        log_panel.push("⬛ Run cancelled by user")
        log_panel.set_status("STOPPED")
        ui.notify("Run stopped", type="warning", position="top-right", timeout=2000)
    except Exception as exc:
        log_panel.push(f"✗ Fatal: {type(exc).__name__}: {str(exc)[:120]}")
        log_panel.set_status("ERROR")
        ui.notify(f"Error: {str(exc)[:80]}", type="negative", position="top-right")
    finally:
        _current_run_task = None
        query_panel.set_running(False)


async def load_replay_from_disk(run_id: str, log_panel, results_panel) -> None:
    from run_trace import RunTrace
    import pathlib

    path = pathlib.Path(f"./run_artifacts/{run_id}/replay.json")
    if not path.exists():
        ui.notify(f"Replay not found for run {run_id}", type="negative")
        return
    try:
        trace = RunTrace.load(str(path))
        log_panel.clear()
        if trace.log_lines:
            for line in trace.log_lines:
                log_panel.push(line)
        else:
            # Legacy runs without saved log_lines — synthesise a short summary
            log_panel.push(f"▶ Loaded run {run_id}")
            log_panel.push(f"  Goal: {trace.goal}")
            if trace.locality:
                log_panel.push(f"  Locality: {trace.locality}")
            log_panel.push(f"  Sources: {len(trace.sources)}")
        log_panel.set_status("COMPLETE")
        results_panel.clear()
        for row in (trace.comparison_rows or []):
            results_panel.add_row(row)
        results_panel.set_insights(trace.insights or "")
        results_panel.set_replay(trace)
        results_panel.switch_to_compare()
        ui.notify(f"Loaded run {run_id[:8]}", type="positive", position="top-right", timeout=2000)
    except Exception as exc:
        ui.notify(f"Load failed: {exc}", type="negative")


try:
    ui.run(title="LabLens", port=8080, reload=False)
except KeyboardInterrupt:
    pass
