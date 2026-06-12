# ui/log_panel.py
from nicegui import ui

_BADGE = {
    "IDLE":     "background:#21262d; color:#8b949e;",
    "RUNNING":  "background:#1d4ed8; color:#ffffff;",
    "COMPLETE": "background:#166534; color:#86efac;",
    "ERROR":    "background:#7f1d1d; color:#fca5a5;",
}


class LogPanel:
    def __init__(self):
        with ui.column().classes("w-full gap-0").style(
            "height: 100%; display: flex; flex-direction: column;"
        ):
            # Header bar — adapts to theme via CSS variables
            with ui.row().classes("w-full items-center gap-2 px-3 py-2 border-b").style(
                "background: var(--ll-surface-dim); border-color: var(--ll-border); flex-shrink: 0;"
            ):
                ui.label("AGENT LOG").style(
                    "font-size: 10px; font-weight: 600; letter-spacing: 0.1em; color: var(--ll-text3);"
                )
                ui.space()
                self._badge = ui.element("span").style(
                    "font-size: 10px; font-weight: 700; padding: 2px 10px; "
                    "border-radius: 9999px; letter-spacing: 0.06em; " + _BADGE["IDLE"]
                )
                with self._badge:
                    self._badge_text = ui.label("IDLE")
                self._tok_lbl = ui.label("0 tok").style(
                    "font-size: 11px; color: var(--ll-text3); min-width: 48px; text-align: right;"
                )

            # Log area — flex:1 fills remaining height; explicit min-height as fallback
            self._log = ui.log(max_lines=500).classes("ll-log-wrap").style(
                "flex: 1; min-height: 300px; width: 100%; "
                "font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace; "
                "font-size: 11.5px; line-height: 1.65; "
                "background: var(--ll-log-bg); color: var(--ll-log-text); "
                "padding: 10px 12px; overflow-y: auto; word-break: break-word;"
            )

        self._total_tokens = 0

    def push(self, line: str) -> None:
        self._log.push(line)

    def set_status(self, status: str) -> None:
        style = (
            "font-size: 10px; font-weight: 700; padding: 2px 10px; "
            "border-radius: 9999px; letter-spacing: 0.06em; "
            + _BADGE.get(status, _BADGE["IDLE"])
        )
        self._badge.style(style)
        self._badge_text.set_text(status)

    def add_tokens(self, n: int) -> None:
        self._total_tokens += n
        t = self._total_tokens
        self._tok_lbl.set_text(f"{t/1000:.1f}k tok" if t >= 1000 else f"{t} tok")

    def clear(self) -> None:
        self._log.clear()
        self._total_tokens = 0
        self.set_status("IDLE")
        self._tok_lbl.set_text("0 tok")
