# ui/query_panel.py
import asyncio
import json
import pathlib
from datetime import datetime
from nicegui import ui
from typing import Callable, Optional


def _load_recent_runs(limit: int = 5) -> list[dict]:
    """Scan ./run_artifacts/*/replay.json sorted by mtime (newest first)."""
    runs: list[dict] = []
    artifacts_dir = pathlib.Path("./run_artifacts")
    if not artifacts_dir.exists():
        return runs
    for p in sorted(
        artifacts_dir.glob("*/replay.json"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )[:limit]:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            runs.append({
                "run_id":   data.get("run_id", p.parent.name),
                "goal":     data.get("goal", ""),
                "locality": data.get("locality", ""),
                "started":  data.get("started", ""),
            })
        except Exception:
            pass
    return runs


def _fmt_started(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%b %d  %H:%M")
    except Exception:
        return iso[:16] if iso else "—"


class QueryPanel:
    def __init__(self):
        self._on_run_cb: Optional[Callable] = None
        self._on_stop_cb: Optional[Callable] = None
        self._on_load_replay_cb: Optional[Callable] = None

        with ui.column().classes("w-full h-full overflow-y-auto gap-0"):

            # ── Inputs ────────────────────────────────────────────────────
            with ui.column().classes("w-full p-4 gap-4"):

                with ui.column().classes("w-full gap-1"):
                    ui.label("TEST / PANEL").style(
                        "font-size: 10px; font-weight: 600; letter-spacing: 0.1em; "
                        "color: var(--ll-text3);"
                    )
                    self._query = ui.textarea(
                        placeholder="e.g. Thyroid Profile (T3, T4, TSH)"
                    ).classes("w-full").props("rows=3 outlined dense")

                with ui.column().classes("w-full gap-1"):
                    ui.label("LOCALITY / CITY").style(
                        "font-size: 10px; font-weight: 600; letter-spacing: 0.1em; "
                        "color: var(--ll-text3);"
                    )
                    self._locality = ui.input(
                        placeholder="e.g. Koramangala, Bangalore"
                    ).classes("w-full").props("outlined dense")

            # ── Divider ───────────────────────────────────────────────────
            ui.separator()

            # ── Options ───────────────────────────────────────────────────
            with ui.column().classes("w-full px-4 py-3 gap-2"):
                ui.label("OPTIONS").style(
                    "font-size: 10px; font-weight: 600; letter-spacing: 0.1em; "
                    "color: var(--ll-text3); margin-bottom: 2px;"
                )
                self._opt_online  = ui.checkbox("Online platforms",     value=True )
                self._opt_nearby  = ui.checkbox("Nearby labs",          value=True )
                self._opt_reviews = ui.checkbox("Include reviews",      value=True )
                self._opt_home    = ui.checkbox("Home collection only", value=False)

            # ── Run / Stop buttons ────────────────────────────────────────
            with ui.column().classes("w-full px-4 pb-4 pt-1 gap-2"):
                self._run_btn = ui.button(
                    "Run Search", on_click=self._handle_run
                ).props("unelevated no-caps").classes("w-full").style(
                    "background: var(--ll-accent) !important; "
                    "color: #ffffff !important; "
                    "font-size: 13px !important; font-weight: 700 !important; "
                    "padding: 10px 0 !important; border-radius: 6px !important; "
                    "letter-spacing: 0.03em !important;"
                )
                self._stop_btn = ui.button(
                    "⬛ Stop Run", on_click=self._handle_stop
                ).props("unelevated no-caps").classes("w-full hidden").style(
                    "background: #dc2626 !important; "
                    "color: #ffffff !important; "
                    "font-size: 13px !important; font-weight: 700 !important; "
                    "padding: 10px 0 !important; border-radius: 6px !important; "
                    "letter-spacing: 0.03em !important;"
                )

            # ── Divider ───────────────────────────────────────────────────
            ui.separator()

            # ── Recent ────────────────────────────────────────────────────
            with ui.column().classes("w-full px-4 py-3 gap-2 flex-1"):
                ui.label("RECENT").style(
                    "font-size: 10px; font-weight: 600; letter-spacing: 0.1em; "
                    "color: var(--ll-text3);"
                )
                self._recent_container = ui.column().classes("w-full gap-1")
                self._refresh_recent()

    # ── Public API ────────────────────────────────────────────────────────

    def on_run(self, cb: Callable) -> None:
        self._on_run_cb = cb

    def on_stop(self, cb: Callable) -> None:
        self._on_stop_cb = cb

    def set_running(self, running: bool) -> None:
        if running:
            self._run_btn.classes(add="hidden")
            self._stop_btn.classes(remove="hidden")
        else:
            self._run_btn.classes(remove="hidden")
            self._stop_btn.classes(add="hidden")

    def on_load_replay(self, cb: Callable) -> None:
        """Register a callback invoked with run_id when a recent run is clicked."""
        self._on_load_replay_cb = cb

    def refresh_recent(self) -> None:
        """Re-scan disk and redraw the recent list. Call after a new run completes."""
        self._refresh_recent()

    # ── Internals ────────────────────────────────────────────────────────

    async def _handle_stop(self) -> None:
        if self._on_stop_cb:
            result = self._on_stop_cb()
            if asyncio.iscoroutine(result):
                await result

    async def _handle_run(self) -> None:
        goal     = self._query.value.strip()
        locality = self._locality.value.strip()
        if not goal:
            ui.notify("Please enter a test name", type="warning", position="top-right")
            return
        opts = {
            "online":    self._opt_online.value,
            "nearby":    self._opt_nearby.value,
            "reviews":   self._opt_reviews.value,
            "home_only": self._opt_home.value,
        }
        if self._on_run_cb:
            result = self._on_run_cb(goal, locality, opts)
            if asyncio.iscoroutine(result):
                await result

    def _refresh_recent(self) -> None:
        runs = _load_recent_runs()
        self._recent_container.clear()
        with self._recent_container:
            if not runs:
                ui.label("No recent runs").classes("text-xs").style("color: var(--ll-text3);")
                return
            for run in runs:
                self._render_recent_item(run)

    def _render_recent_item(self, run: dict) -> None:
        goal_text  = run["goal"] or "—"
        goal_short = goal_text[:34] + ("…" if len(goal_text) > 34 else "")
        loc        = run["locality"] or "—"
        date_str   = _fmt_started(run["started"])

        with ui.card().classes("w-full cursor-pointer").style(
            "background: var(--ll-tag-bg); border: 1px solid var(--ll-border); "
            "border-radius: 4px; padding: 6px 8px; margin-bottom: 2px;"
        ).on("click", self._make_load_handler(run)):
            ui.label(goal_short).classes("text-xs font-medium").style(
                "color: var(--ll-text); line-height: 1.4;"
            )
            ui.label(f"{loc} · {date_str}").classes("text-xs").style(
                "color: var(--ll-text3); line-height: 1.4;"
            )

    def _make_load_handler(self, run: dict):
        """Returns an async click handler bound to this specific run dict."""
        async def _handler():
            # Fill form fields so user can see what this run was for
            self._query.set_value(run["goal"])
            self._locality.set_value(run["locality"])
            if self._on_load_replay_cb:
                result = self._on_load_replay_cb(run["run_id"])
                if asyncio.iscoroutine(result):
                    await result
        return _handler
