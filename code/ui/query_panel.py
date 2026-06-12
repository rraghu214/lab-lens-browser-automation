# ui/query_panel.py
import asyncio
from nicegui import ui
from typing import Callable, Optional


class QueryPanel:
    def __init__(self):
        self._on_run_cb: Optional[Callable] = None
        self._recent: list[str] = []

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

            # ── Run button ────────────────────────────────────────────────
            with ui.column().classes("w-full px-4 pb-4 pt-1"):
                ui.button(
                    "Run Search", on_click=self._handle_run
                ).props("unelevated no-caps").classes("w-full").style(
                    "background: var(--ll-accent) !important; "
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

    def on_run(self, cb: Callable) -> None:
        self._on_run_cb = cb

    async def _handle_run(self) -> None:
        """Async handler — NiceGUI will await it in the event loop, making
        asyncio.create_task() safe to call from here."""
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
        self._add_recent(goal)
        if self._on_run_cb:
            result = self._on_run_cb(goal, locality, opts)
            # MUST await the coroutine directly — asyncio.create_task() loses
            # NiceGUI's client context, so push() / update() wouldn't reach the browser.
            if asyncio.iscoroutine(result):
                await result

    def _add_recent(self, query: str) -> None:
        if query in self._recent:
            self._recent.remove(query)
        self._recent.insert(0, query)
        self._recent = self._recent[:5]
        self._recent_container.clear()
        with self._recent_container:
            for q in self._recent:
                ui.button(
                    q[:36] + ("…" if len(q) > 36 else ""),
                    on_click=lambda _, qq=q: self._query.set_value(qq)
                ).props("flat dense no-caps align=left").classes("w-full text-left").style(
                    "font-size: 12px; color: var(--ll-text2); "
                    "background: var(--ll-tag-bg); "
                    "border: 1px solid var(--ll-border); "
                    "border-radius: 4px; padding: 5px 8px; margin-bottom: 2px; "
                    "text-overflow: ellipsis; overflow: hidden;"
                )
