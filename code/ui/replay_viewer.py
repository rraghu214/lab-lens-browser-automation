# ui/replay_viewer.py
from nicegui import ui
from run_trace import RunTrace, SourceResult

_STATUS_COLOR = {"success": "green", "blocked": "orange", "failed": "red"}
_STATUS_LABEL = {"success": "✓ success", "blocked": "⊘ blocked", "failed": "failed"}


def _fmt_seconds(s: float) -> str:
    s = int(s)
    if s < 60:
        return f"{s}s"
    m, sec = divmod(s, 60)
    return f"{m}m {sec:02d}s" if sec else f"{m}m"


def _extracted_text(extracted: dict) -> str:
    if not extracted:
        return "(no data retrieved)"
    # unwrap {'content': '...'} to show just the text
    if "content" in extracted and isinstance(extracted["content"], str):
        return extracted["content"][:2000]
    return str(extracted)[:2000]


class ReplayViewer:
    def __init__(self):
        with ui.column().classes("w-full p-4 gap-4"):
            # ── Save / Load controls ──────────────────────────────────────
            with ui.row().classes("gap-2 items-center flex-wrap"):
                self._save_btn = ui.button("Save replay", on_click=self._save).props("outline")
                ui.separator().props("vertical")
                self._path_input = ui.input(
                    placeholder="e.g. run_artifacts/8aa9f3a1/replay.json"
                ).classes("flex-1 text-sm min-w-64").props("outlined dense")
                ui.button("Load replay", on_click=self._load_from_path).props("outline")
                self._upload = ui.upload(
                    label="Upload replay.json",
                    on_upload=self._load_from_upload,
                    max_files=1,
                ).props("accept=.json flat dense").classes("text-xs")

            ui.separator()

            # ── Run metadata (populated by load()) ───────────────────────
            self._meta_container = ui.column().classes("w-full")

            ui.separator()

            # ── DAG ──────────────────────────────────────────────────────
            ui.label("Planner DAG").classes("text-sm font-medium").style("color: var(--ll-text2)")
            self._dag_container = ui.column().classes("w-full").style(
                "min-height: 420px; overflow: auto"
            )

            ui.separator()

            # ── Per-source sections ───────────────────────────────────────
            ui.label("Sources").classes("text-sm font-medium").style("color: var(--ll-text2)")
            self._sources_container = ui.column().classes("w-full gap-2")

            ui.separator()

            # ── Cost ledger ───────────────────────────────────────────────
            ui.label("Cost ledger").classes("text-sm font-medium").style("color: var(--ll-text2)")
            self._cost_container = ui.column().classes("w-full")

        self._trace: RunTrace | None = None

    # ── Public API ────────────────────────────────────────────────────────

    def load(self, trace: RunTrace) -> None:
        self._trace = trace
        self._meta_container.clear()
        self._dag_container.clear()
        self._sources_container.clear()
        self._cost_container.clear()

        with self._meta_container:
            self._render_meta(trace)

        with self._dag_container:
            self._render_dag(trace.dag_plan)

        for source in trace.sources:
            with self._sources_container:
                self._render_source(source)

        with self._cost_container:
            if trace.cost:
                self._render_cost(trace.cost)
            else:
                ui.label("No cost data available").classes("text-xs").style("color: var(--ll-text3)")

    # ── Rendering helpers ─────────────────────────────────────────────────

    def _render_meta(self, trace: RunTrace) -> None:
        with ui.card().classes("w-full p-3").style(
            "background: var(--ll-surface-dim); border: 1px solid var(--ll-border)"
        ):
            with ui.row().classes("items-center gap-3 flex-wrap"):
                ui.badge(f"run {trace.run_id}", color="blue-grey").classes("text-xs font-mono")
                ui.label(trace.goal or "—").classes("font-medium text-sm").style("color: var(--ll-text)")
                if trace.locality:
                    ui.label(f"📍 {trace.locality}").classes("text-xs").style("color: var(--ll-text2)")
                ui.space()
                started = trace.started[:19].replace("T", "  ") if trace.started else "—"
                ui.label(started).classes("text-xs font-mono").style("color: var(--ll-text3)")

    def _render_dag(self, dag: dict) -> None:
        if not dag or not dag.get("edges"):
            ui.label("No DAG plan available").classes("text-xs").style("color: var(--ll-text3)")
            return

        def _nid(name: str) -> str:
            return name.replace(":", "_").replace(" ", "_").replace("-", "_")

        nodes  = dag.get("nodes", [])
        edges  = dag.get("edges", [])
        b_nodes = [n for n in nodes if n.startswith("Browser:")]
        o_nodes = [n for n in nodes if not n.startswith("Browser:")]

        lines = [
            "%%{init: {'theme': 'base', 'flowchart': {"
            "'nodeSpacing': 30, 'rankSpacing': 120, "
            "'htmlLabels': true}}}%%",
            "graph LR",
        ]
        seen: set[str] = set()

        for raw in o_nodes:
            nid = _nid(raw)
            if nid not in seen:
                lines.append(f'  {nid}["{raw}"]')
                seen.add(nid)

        if b_nodes:
            lines.append("  subgraph Sources")
            for raw in b_nodes:
                nid = _nid(raw)
                if nid not in seen:
                    lines.append(f'    {nid}["{raw}"]')
                    seen.add(nid)
            lines.append("  end")

        for edge in edges:
            lines.append(f"  {_nid(edge[0])} --> {_nid(edge[1])}")

        ui.mermaid("\n".join(lines)).classes("w-full")

    def _render_source(self, source: SourceResult) -> None:
        if source.success:
            sk = "success"
        elif source.blocked:
            sk = "blocked"
        else:
            sk = "failed"

        exp = ui.expansion().classes(
            "w-full border rounded"
        ).style("border-color: var(--ll-border)")

        with exp.add_slot("header"):
            with ui.row().classes("items-center gap-2 w-full pr-2"):
                ui.icon("web").classes("text-base").style("color: var(--ll-text3)")
                ui.label(source.name).classes("font-medium text-sm").style("color: var(--ll-text)")
                ui.badge(source.layer, color="blue-grey").props("outline").classes("text-xs")
                ui.space()
                ui.badge(_STATUS_LABEL[sk], color=_STATUS_COLOR[sk]).classes("text-xs")

        with exp:
            if source.layer_path:
                ui.label(f"Path: {source.layer_path}").classes("text-xs px-2 pt-2").style(
                    "color: var(--ll-text3); font-style: italic"
                )
            if source.blocked:
                ui.label("Blocked — gateway precondition fired").classes("text-sm p-2").style("color: #f87171")
            else:
                ui.label("Raw extracted data").classes("text-xs mt-1").style("color: var(--ll-text3)")
                ui.code(_extracted_text(source.extracted)).classes("text-xs w-full")
                ui.label("Screenshots").classes("text-xs mt-3").style("color: var(--ll-text3)")
                self._render_screenshots(source)

    def _render_screenshots(self, source: SourceResult) -> None:
        screenshots = [t for t in source.turn_log if t.marked_path or t.raw_png_path]
        if not screenshots:
            if source.layer == "layer1":
                reason = "Layer 1 — static fetch, no browser interaction"
            elif source.blocked:
                reason = "blocked before any turns ran"
            elif source.turn_log:
                reason = "turns ran but no annotated screenshots saved"
            else:
                reason = "no turns completed (LLM unavailable or rate-limited)"
            ui.label(f"No screenshots — {reason}").classes("text-xs").style("color: var(--ll-text3)")
            return

        with ui.row().classes("gap-2 flex-wrap mt-1"):
            for turn in screenshots:
                _p = (turn.marked_path or turn.raw_png_path or "").replace("\\", "/")
                _idx = _p.find("run_artifacts/")
                url = ("/artifacts/" + _p[_idx + len("run_artifacts/"):]) if _idx >= 0 else "/artifacts/" + _p
                with ui.card().tight().classes("cursor-pointer").on(
                    "click", lambda u=url: self._open_image_dialog(u)
                ):
                    ui.image(url).classes("w-40 h-28 object-cover")
                    ui.label(f"Turn {turn.turn} · {turn.provider}").classes(
                        "text-xs p-1 text-center"
                    ).style("color: var(--ll-text3)")

    def _open_image_dialog(self, url: str) -> None:
        with ui.dialog() as d, ui.card().classes("p-2"):
            ui.image(url).classes("max-w-4xl").style("max-height: 85vh; object-fit: contain")
            ui.button("Close", on_click=d.close).classes("mt-2 self-end")
        d.open()

    def _render_cost(self, cost: list[dict]) -> None:
        total_turns = sum(c.get("turns", 0) for c in cost)
        total_tok   = sum(c.get("tok_in", 0) + c.get("tok_out", 0) for c in cost)
        total_time  = sum(c.get("elapsed_s", 0.0) for c in cost)

        with ui.row().classes("gap-3 mb-4 flex-wrap"):
            for label, val, sub in [
                ("Total turns",  str(total_turns),            None),
                ("Total tokens", f"{total_tok:,}",            None),
                ("Total time",   _fmt_seconds(total_time),    None),
                ("Est. cost",    "$0.00",                     "free tier"),
            ]:
                with ui.card().classes("p-3 flex-1 text-center min-w-28").style(
                    "background: var(--ll-surface-dim); border: 1px solid var(--ll-border)"
                ):
                    ui.label(label).classes("text-xs").style("color: var(--ll-text3)")
                    ui.label(val).classes("text-xl font-medium mt-1").style("color: var(--ll-text)")
                    if sub:
                        ui.label(sub).classes("text-xs").style("color: var(--ll-text3)")

        # format elapsed_s as human-readable in each row copy
        display_rows = [
            {**r, "elapsed_s": _fmt_seconds(r.get("elapsed_s", 0))}
            for r in cost
        ]

        cols = [
            {"name": "source",    "label": "Source",     "field": "source",    "align": "left"},
            {"name": "layer",     "label": "Layer",      "field": "layer",     "align": "left"},
            {"name": "turns",     "label": "Turns",      "field": "turns"},
            {"name": "tok_in",    "label": "Tokens in",  "field": "tok_in"},
            {"name": "tok_out",   "label": "Tokens out", "field": "tok_out"},
            {"name": "elapsed_s", "label": "Time",       "field": "elapsed_s", "align": "right"},
        ]
        ui.table(columns=cols, rows=display_rows, row_key="source").classes("w-full text-sm")

    # ── Save / Load ───────────────────────────────────────────────────────

    def _save(self) -> None:
        if not self._trace:
            ui.notify("No trace to save", type="warning")
            return
        import pathlib
        path = f"./run_artifacts/{self._trace.run_id}/replay.json"
        pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._trace.save(path)
        ui.notify(f"Saved to {path}", type="positive")

    def _load_from_path(self) -> None:
        path = self._path_input.value.strip()
        if not path:
            ui.notify("Enter a path to replay.json", type="warning")
            return
        import pathlib
        p = pathlib.Path(path)
        if not p.exists():
            ui.notify(f"File not found: {path}", type="negative")
            return
        try:
            trace = RunTrace.load(str(p))
            self.load(trace)
            ui.notify(f"Loaded run {trace.run_id}", type="positive")
        except Exception as ex:
            ui.notify(f"Load failed: {ex}", type="negative")

    async def _load_from_upload(self, e) -> None:
        import tempfile, pathlib
        try:
            content = await e.file.read()
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            trace = RunTrace.load(tmp_path)
            pathlib.Path(tmp_path).unlink(missing_ok=True)
            self.load(trace)
            self._upload.reset()
            ui.notify(f"Replay loaded (run {trace.run_id})", type="positive")
        except Exception as ex:
            ui.notify(f"Load failed: {ex}", type="negative")
