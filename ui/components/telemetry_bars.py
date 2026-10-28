"""KPI stat cards, persistent execution summary panel, and simulation control bar."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from ui.components.theme import (
    COLOR_AVAILABLE,
    COLOR_AVAILABLE_BG,
    COLOR_BG_CARD,
    COLOR_BG_PRIMARY,
    COLOR_BORDER,
    COLOR_INFO,
    COLOR_INFO_BG,
    COLOR_LOG_BG,
    COLOR_OCCUPIED,
    COLOR_OCCUPIED_BG,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_WAITING,
    COLOR_WAITING_BG,
    font_family,
)


class StatCard(tk.Frame):
    """Card widget displaying a KPI metric (title, value, and subtitle).

    In OS terms, these cards display the state of shared counters,
    such as admission counts, current occupancy, and terminal outcomes.
    """

    def __init__(
        self,
        parent: tk.Widget,
        title: str,
        initial_value: str = "0",
        subtitle: str = "",
        value_color: str = COLOR_TEXT_PRIMARY,
        compact: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(
            parent,
            bg=COLOR_BG_CARD,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            padx=10 if not compact else 8,
            pady=8 if not compact else 6,
            **kwargs,
        )
        self.value_color = value_color
        self.value: str = str(initial_value)
        self.subtitle: str = subtitle

        # Card Title
        self._lbl_title = tk.Label(
            self,
            text=title.upper(),
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 8, "bold"),
            anchor="w",
        )
        self._lbl_title.pack(fill="x")

        # Large Metric Value
        value_font_size = 14 if compact else 18
        self._lbl_value = tk.Label(
            self,
            text=initial_value,
            bg=COLOR_BG_CARD,
            fg=self.value_color,
            font=(font_family(self), value_font_size, "bold"),
            anchor="w",
        )
        self._lbl_value.pack(fill="x", pady=(2, 0))

        # Optional descriptive subtitle
        self._lbl_subtitle = tk.Label(
            self,
            text=subtitle,
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 8),
            anchor="w",
        )
        if subtitle:
            self._lbl_subtitle.pack(fill="x")

    def update_value(self, value: str | int, subtitle: str | None = None) -> None:
        """Update the displayed value and optional subtitle."""
        self.value = str(value)
        self._lbl_value.config(text=self.value)
        if subtitle is not None:
            self.update_subtitle(subtitle)

    def update_subtitle(self, subtitle: str) -> None:
        """Update and ensure visibility of the descriptive subtitle."""
        self.subtitle = subtitle
        self._lbl_subtitle.config(text=subtitle)
        if subtitle and not self._lbl_subtitle.winfo_ismapped():
            self._lbl_subtitle.pack(fill="x")


class MetricsSummaryWidget(tk.Frame):
    """Persistent end-of-run and live execution summary panel.

    Displays consolidated run results directly in the UI without closing the app:
    - Generated, accepted, and rejected requests
    - Finished vehicles and cancelled requests
    - Peak occupancy and average waiting time
    - Explicit warnings if the run or audit was incomplete
    Remains visible after a run finishes until a new run is started.
    """

    def __init__(self, parent: tk.Widget, capacity: int = 5, **kwargs) -> None:
        super().__init__(
            parent,
            bg=COLOR_BG_CARD,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            padx=12,
            pady=8,
            **kwargs,
        )
        self.capacity = capacity
        self._last_report: str = ""
        self._summary_window: tk.Toplevel | None = None
        self.warning_message: str = ""

        header = tk.Frame(self, bg=COLOR_BG_CARD)
        header.pack(fill="x", pady=(0, 4))

        tk.Label(
            header,
            text="RESUMEN DE EJECUCIÓN Y TELEMETRÍA",
            bg=COLOR_BG_CARD,
            fg=COLOR_INFO,
            font=(font_family(self), 9, "bold"),
            anchor="w",
        ).pack(side="left")

        self._btn_report = tk.Button(
            header,
            text="Detalle Completo",
            bg=COLOR_INFO_BG,
            fg=COLOR_INFO,
            activebackground=COLOR_INFO,
            activeforeground=COLOR_BG_PRIMARY,
            font=(font_family(self), 8, "bold"),
            relief="flat",
            padx=8,
            pady=2,
            cursor="hand2",
            state="disabled",
            command=self.show_report_dialog,
        )
        self._btn_report.pack(side="right")

        self._lbl_banner = tk.Label(
            header,
            text="Sin ejecución finalizada aún",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 8, "italic"),
            padx=6,
        )
        self._lbl_banner.pack(side="right")

        # Consolidated summary metrics grid (visible directly without opening a dialog)
        metrics_row = tk.Frame(self, bg=COLOR_BG_CARD)
        metrics_row.pack(fill="x")

        self._items: dict[str, tk.Label] = {}
        definitions = (
            ("summary_counts", "Gen / Acep / Rech", "0 / 0 / 0", COLOR_TEXT_PRIMARY),
            ("summary_terminals", "Fin / Cancelados", "0 / 0", COLOR_INFO),
            ("avg_wait", "Espera Promedio", "0.00s", COLOR_WAITING),
            ("avg_parking", "Estac. Promedio", "0.00s", COLOR_AVAILABLE),
            ("peak_waiting", "Pico Espera", "0", COLOR_WAITING),
            ("peak_occupancy", "Máx. Ocupación", f"0 / {capacity}", COLOR_OCCUPIED),
            ("duration", "Duración", "N/D", COLOR_INFO),
        )
        cols_per_row = 4
        for idx, (key, label_text, initial, color) in enumerate(definitions):
            row_idx = idx // cols_per_row
            col_idx = idx % cols_per_row
            cell = tk.Frame(metrics_row, bg=COLOR_BG_PRIMARY, padx=8, pady=4)
            cell.grid(
                row=row_idx,
                column=col_idx,
                sticky="nsew",
                padx=(0, 4 if col_idx < cols_per_row - 1 else 0),
                pady=(0, 4 if row_idx == 0 else 0),
            )
            metrics_row.grid_columnconfigure(col_idx, weight=1, uniform="telemetry_col")

            tk.Label(
                cell,
                text=label_text.upper(),
                bg=COLOR_BG_PRIMARY,
                fg=COLOR_TEXT_MUTED,
                font=(font_family(self), 7, "bold"),
                anchor="w",
            ).pack(fill="x")

            val_lbl = tk.Label(
                cell,
                text=initial,
                bg=COLOR_BG_PRIMARY,
                fg=color,
                font=(font_family(self), 10, "bold"),
                anchor="w",
            )
            val_lbl.pack(fill="x", pady=(1, 0))
            self._items[key] = val_lbl

        # Integrity / Warning status bar at the bottom of the summary
        self._lbl_warning = tk.Label(
            self,
            text="Estado de integridad: sin advertencias.",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 8),
            anchor="w",
            pady=2,
        )
        self._lbl_warning.pack(fill="x", pady=(4, 0))

    def update_from_snapshot(
        self,
        snapshot: dict[str, float | int | None],
        report_text: str | None = None,
        warning: str | None = None,
    ) -> None:
        """Refresh visible summary fields and integrity warnings from `SimulationMetrics.snapshot()`."""
        gen = int(snapshot.get("total_generated") or 0)
        adm = int(snapshot.get("total_admitted") or 0)
        rej = int(snapshot.get("total_rejected") or 0)
        fin = int(snapshot.get("total_finished") or 0)
        can = int(snapshot.get("total_cancelled") or 0)
        avg_wait = float(snapshot.get("average_waiting_time") or 0.0)
        avg_park = float(snapshot.get("average_parking_time") or 0.0)
        peak_wait = int(snapshot.get("peak_waiting") or 0)
        peak_occ = int(snapshot.get("peak_occupancy") or 0)
        duration = snapshot.get("total_duration")

        self._items["summary_counts"].config(text=f"{gen} / {adm} / {rej}")
        self._items["summary_terminals"].config(text=f"{fin} / {can}")
        self._items["avg_wait"].config(text=f"{avg_wait:.2f}s")
        self._items["avg_parking"].config(text=f"{avg_park:.2f}s")
        self._items["peak_waiting"].config(text=str(peak_wait))
        self._items["peak_occupancy"].config(text=f"{peak_occ} / {self.capacity}")
        self._items["duration"].config(
            text=f"{float(duration):.2f}s"
            if duration is not None
            else ("En curso" if gen > 0 else "N/D")
        )

        if report_text:
            self._last_report = report_text
            self._btn_report.config(state="normal")

        if warning:
            self.set_warning(warning)
        elif duration is not None:
            self._lbl_banner.config(
                text=f"Última ejecución: {float(duration):.2f}s",
                fg=COLOR_AVAILABLE,
            )
            self._btn_report.config(state="normal")
            if can > 0:
                self.warning_message = (
                    f"Aviso: Ejecución detenida con {can} solicitud(es) cancelada(s) en espera."
                )
                self._lbl_warning.config(
                    text=self.warning_message,
                    fg=COLOR_WAITING,
                )
            elif not self.warning_message:
                self._lbl_warning.config(
                    text="Ejecución completada y drenada sin advertencias de integridad.",
                    fg=COLOR_AVAILABLE,
                )

    def set_warning(self, warning_text: str) -> None:
        """Display an explicit warning when a run or audit is incomplete."""
        self.warning_message = warning_text
        self._lbl_warning.config(text=warning_text, fg=COLOR_OCCUPIED)
        self._lbl_banner.config(text="Ejecución / auditoría incompleta", fg=COLOR_OCCUPIED)

    def reset(self) -> None:
        """Reset summary values when a new simulation run starts."""
        self.warning_message = ""
        self._items["summary_counts"].config(text="0 / 0 / 0")
        self._items["summary_terminals"].config(text="0 / 0")
        self._items["avg_wait"].config(text="0.00s")
        self._items["avg_parking"].config(text="0.00s")
        self._items["peak_waiting"].config(text="0")
        self._items["peak_occupancy"].config(text=f"0 / {self.capacity}")
        self._items["duration"].config(text="En curso")
        self._lbl_banner.config(text="Ejecución en progreso...", fg=COLOR_INFO)
        self._lbl_warning.config(
            text="Estado de integridad: ejecución en curso.",
            fg=COLOR_TEXT_MUTED,
        )

    def show_report_dialog(self) -> None:
        """Open or focus a Toplevel window showing the full text report."""
        if not self._last_report:
            return
        if self._summary_window is not None and self._summary_window.winfo_exists():
            self._summary_window.lift()
            return

        win = tk.Toplevel(self)
        win.title("Resumen Final de la Simulación")
        win.geometry("480x360")
        win.configure(bg=COLOR_BG_PRIMARY)
        self._summary_window = win

        container = tk.Frame(
            win,
            bg=COLOR_BG_CARD,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            padx=16,
            pady=14,
        )
        container.pack(fill="both", expand=True, padx=14, pady=14)

        tk.Label(
            container,
            text="ESTADÍSTICAS FINALES DE LA SIMULACIÓN",
            bg=COLOR_BG_CARD,
            fg=COLOR_INFO,
            font=(font_family(self), 10, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(0, 8))

        txt = tk.Text(
            container,
            bg=COLOR_LOG_BG,
            fg=COLOR_TEXT_PRIMARY,
            font=(font_family(self, fixed=True), 9),
            relief="flat",
            padx=10,
            pady=10,
            height=13,
            wrap="none",
        )
        report_body = self._last_report
        if self.warning_message:
            report_body = f"{report_body}\n{self.warning_message}\n"
        txt.insert("1.0", report_body)
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True)

        tk.Button(
            container,
            text="Cerrar",
            bg=COLOR_BORDER,
            fg=COLOR_TEXT_PRIMARY,
            font=(font_family(self), 9, "bold"),
            relief="flat",
            padx=12,
            pady=4,
            cursor="hand2",
            command=win.destroy,
        ).pack(anchor="e", pady=(10, 0))


class ControlBarWidget(tk.Frame):
    """Header and controls toolbar for starting/stopping the simulator.

    Clearly distinguishes the 6 lifecycle states:
    - INICIANDO (start command sent)
    - EN EJECUCIÓN (SIMULATION_STARTED confirmed)
    - DETENCIÓN SOLICITADA (user pressed Stop)
    - FINALIZANDO (terminal events / drain in progress)
    - FINALIZADA (run and drain confirmed; ready to start another)
    - ERROR (unrecoverable failure / controlled shutdown)
    """

    MAX_STATUS_CHARS = 36

    def __init__(
        self,
        parent: tk.Widget,
        on_start: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(parent, bg=COLOR_BG_CARD, padx=16, pady=10, **kwargs)
        self.on_start = on_start
        self.on_stop = on_stop
        self.status_message = "DETENIDO"

        # Application Title & Subtitle
        title_box = tk.Frame(self, bg=COLOR_BG_CARD)
        title_box.pack(side="left")

        tk.Label(
            title_box,
            text="Smart Parking Simulator",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_PRIMARY,
            font=(font_family(self), 14, "bold"),
        ).pack(anchor="w")

        tk.Label(
            title_box,
            text="Monitor de Concurrencia, Sincronización e IPC (Sistemas Operativos)",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 9),
        ).pack(anchor="w")

        # Action Buttons on the right
        btn_box = tk.Frame(self, bg=COLOR_BG_CARD)
        btn_box.pack(side="right")

        # Simulation status badge with bounded text length so long errors do not deform layout
        self._lbl_status = tk.Label(
            btn_box,
            text="DETENIDO",
            bg=COLOR_BORDER,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 9, "bold"),
            padx=10,
            pady=4,
        )
        self._lbl_status.pack(side="left", padx=(0, 14))

        # Start button
        self._btn_start = tk.Button(
            btn_box,
            text="Iniciar Simulación",
            bg=COLOR_AVAILABLE_BG,
            fg=COLOR_AVAILABLE,
            activebackground=COLOR_AVAILABLE,
            activeforeground=COLOR_BG_PRIMARY,
            font=(font_family(self), 9, "bold"),
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
            command=self._handle_start,
        )
        self._btn_start.pack(side="left", padx=(0, 8))

        # Stop button
        self._btn_stop = tk.Button(
            btn_box,
            text="Detener",
            bg=COLOR_OCCUPIED_BG,
            fg=COLOR_OCCUPIED,
            activebackground=COLOR_OCCUPIED,
            activeforeground=COLOR_BG_PRIMARY,
            font=(font_family(self), 9, "bold"),
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
            state="disabled",
            command=self._handle_stop,
        )
        self._btn_stop.pack(side="left")

    @classmethod
    def _format_status_text(cls, message: str) -> str:
        """Truncate overly long status messages so the control bar never deforms."""
        single_line = " ".join(str(message).splitlines()).strip()
        if len(single_line) > cls.MAX_STATUS_CHARS:
            return single_line[: cls.MAX_STATUS_CHARS - 1] + "…"
        return single_line

    def _handle_start(self) -> None:
        if self.on_start:
            self.on_start()

    def _handle_stop(self) -> None:
        if self.on_stop:
            self.on_stop()

    def set_running(self) -> None:
        """Update visual controls when simulation is active."""
        self.status_message = "EN EJECUCIÓN"
        self._lbl_status.config(
            text="EN EJECUCIÓN",
            bg=COLOR_AVAILABLE_BG,
            fg=COLOR_AVAILABLE,
        )
        self._btn_start.config(state="disabled")
        self._btn_stop.config(state="normal")

    def set_stopped(self) -> None:
        """Update visual controls when simulation finishes and drain is confirmed."""
        self.status_message = "FINALIZADA"
        self._lbl_status.config(
            text="FINALIZADA",
            bg=COLOR_INFO_BG,
            fg=COLOR_INFO,
        )
        self._btn_start.config(state="normal")
        self._btn_stop.config(state="disabled")

    def set_pending(self, message: str) -> None:
        """Keep both run controls unavailable during a lifecycle transition or error."""
        self.status_message = str(message)
        upper = self.status_message.upper()
        if upper.startswith("ERROR") or upper.startswith("WARNING"):
            bg_color, fg_color = COLOR_OCCUPIED_BG, COLOR_OCCUPIED
        elif "DETENCIÓN" in upper or "STOP" in upper or "CERRANDO" in upper:
            bg_color, fg_color = COLOR_WAITING_BG, COLOR_WAITING
        elif "INICIANDO" in upper or "FINALIZANDO" in upper:
            bg_color, fg_color = COLOR_INFO_BG, COLOR_INFO
        else:
            bg_color, fg_color = COLOR_BORDER, COLOR_INFO

        self._lbl_status.config(
            text=self._format_status_text(message),
            bg=bg_color,
            fg=fg_color,
        )
        self._btn_start.config(state="disabled")
        self._btn_stop.config(state="disabled")


__all__ = ["ControlBarWidget", "MetricsSummaryWidget", "StatCard"]
