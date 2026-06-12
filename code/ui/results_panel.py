# ui/results_panel.py
from nicegui import ui
from typing import Optional

ONLINE_COLS = [
    {"name": "provider",    "label": "Provider",    "field": "provider",        "align": "left"},
    {"name": "price",       "label": "Price (₹)",   "field": "price",           "sortable": True},
    {"name": "home",        "label": "Home",        "field": "home_collection"},
    {"name": "walk_in",     "label": "Walk-in",     "field": "walk_in"},
    {"name": "tat",         "label": "TAT (h)",     "field": "tat_hours",       "align": "left"},
    {"name": "rating",      "label": "Rating",      "field": "rating",          "sortable": True},
    {"name": "parameters",  "label": "Parameters",  "field": "parameters",      "align": "left"},
    {"name": "notes",       "label": "Notes",       "field": "notes",           "align": "left"},
]

NEARBY_COLS = [
    {"name": "provider", "label": "Name",      "field": "provider",        "align": "left"},
    {"name": "price",    "label": "Price (₹)", "field": "price",           "sortable": True},
    {"name": "home",     "label": "Home",      "field": "home_collection"},
    {"name": "tat",      "label": "TAT (h)",   "field": "tat_hours"},
    {"name": "rating",   "label": "Rating",    "field": "rating",          "sortable": True},
]


class ResultsPanel:
    def __init__(self):
        with ui.column().classes("w-full h-full gap-0"):

            # Tabs
            with ui.tabs().classes("w-full border-b").style(
                "background: var(--ll-surface); border-color: var(--ll-border); min-height: 44px;"
            ) as self._tabs:
                self._tab_compare  = ui.tab("Compare")
                self._tab_insights = ui.tab("Insights")
                self._tab_replay   = ui.tab("Replay")

            with ui.tab_panels(self._tabs, value=self._tab_compare).classes("w-full flex-1").style(
                "background: var(--ll-surface);"
            ):
                with ui.tab_panel(self._tab_compare).style("padding: 0;"):
                    self._build_compare_tab()

                with ui.tab_panel(self._tab_insights).style("padding: 0;"):
                    with ui.column().classes("w-full p-5"):
                        self._insight_md = ui.markdown(
                            "*Run a search to see insights.*"
                        ).style("font-size: 14px; line-height: 1.7; color: var(--ll-text);")

                with ui.tab_panel(self._tab_replay).style("padding: 0;"):
                    from ui.replay_viewer import ReplayViewer
                    self._replay_viewer = ReplayViewer()

    def _build_compare_tab(self):
        with ui.column().classes("w-full p-5 gap-5"):

            # Recommended card (hidden until distiller returns)
            self._rec_card = ui.card().classes("w-full hidden").style(
                "background: var(--ll-surface-dim); "
                "border: 1px solid var(--ll-accent); "
                "border-radius: 8px; padding: 14px 18px;"
            )
            with self._rec_card:
                with ui.row().classes("items-center gap-2 mb-1"):
                    ui.label("⭐").style("font-size: 14px;")
                    ui.label("RECOMMENDED").style(
                        "font-size: 10px; font-weight: 700; letter-spacing: 0.1em; color: #60a5fa;"
                    )
                self._rec_label = ui.markdown("").style(
                    "font-size: 14px; color: var(--ll-text);"
                )

            _bool_slot = r'''
                <q-td :props="props">
                  <span :style="{color: props.value ? '#16a34a' : '#9ca3af', fontWeight: props.value ? '600' : '400'}">
                    {{ props.value ? '✓' : '—' }}
                  </span>
                </q-td>
            '''
            _price_slot = r'''
                <q-td :props="props">
                  {{ props.value != null ? '₹' + props.value : '—' }}
                </q-td>
            '''

            # Online platforms
            with ui.column().classes("w-full gap-2"):
                ui.label("ONLINE PLATFORMS").style(
                    "font-size: 10px; font-weight: 700; letter-spacing: 0.1em; color: var(--ll-text3);"
                )
                self._online_table = ui.table(
                    columns=ONLINE_COLS, rows=[], row_key="provider"
                ).classes("w-full").style(
                    "border: 1px solid var(--ll-border); border-radius: 8px; overflow: hidden;"
                ).props("dense flat")
                self._online_table.add_slot("body-cell-home",    _bool_slot)
                self._online_table.add_slot("body-cell-walk_in", _bool_slot)
                self._online_table.add_slot("body-cell-price",   _price_slot)

            # Nearby labs
            with ui.column().classes("w-full gap-2"):
                ui.label("NEARBY LABS").style(
                    "font-size: 10px; font-weight: 700; letter-spacing: 0.1em; color: var(--ll-text3);"
                )
                self._nearby_table = ui.table(
                    columns=NEARBY_COLS, rows=[], row_key="provider"
                ).classes("w-full").style(
                    "border: 1px solid var(--ll-border); border-radius: 8px; overflow: hidden;"
                ).props("dense flat")
                self._nearby_table.add_slot("body-cell-home",  _bool_slot)
                self._nearby_table.add_slot("body-cell-price", _price_slot)

    def add_row(self, row: dict) -> None:
        target = self._nearby_table if row.get("type") == "nearby" else self._online_table
        provider = row.get("provider", "")
        for i, existing in enumerate(target.rows):
            if existing.get("provider") == provider:
                target.rows[i] = row   # distiller overwrites placeholder
                target.update()
                return
        target.rows.append(row)
        target.update()

    def set_insights(self, md: str) -> None:
        # LLM often double-escapes newlines in JSON (\\n instead of actual \n);
        # replace literal backslash-n with real newlines so markdown renders correctly.
        self._insight_md.set_content(md.replace('\\n', '\n'))

    def set_recommended(self, provider: str, reason: str) -> None:
        self._rec_label.set_content(f"**{provider}** — {reason}")
        self._rec_card.classes(remove="hidden")

    def set_replay(self, trace) -> None:
        self._replay_viewer.load(trace)

    def clear(self) -> None:
        self._online_table.rows.clear()
        self._online_table.update()
        self._nearby_table.rows.clear()
        self._nearby_table.update()
        self._insight_md.set_content("*Run a search to see insights.*")
        self._rec_card.classes(add="hidden")
