"""Main GUI application for the Smart Parking Simulator.

This module implements `ParkingApp`, which:
- Assembles the UI layout using widgets from `ui.widgets`.
- Polls events periodically from the thread-safe `queue.Queue` using `root.after()`.
- Dispatches event updates to UI widgets strictly on the main thread.
- Provides start and stop controls to interface with the Simulator.

Operating System Concepts:
- Producer-Consumer Pattern: Core and simulation workers post events to `queue.Queue`.
  Tkinter on the Main Thread (consumer) polls and processes those events.
- Tkinter Thread Safety: UI toolkits must never be mutated directly by worker threads;
  instead, synchronization is achieved via message passing through the queue.
"""

from __future__ import annotations

import queue
import sys
import time
import traceback
from copy import deepcopy
from datetime import datetime
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Mapping

from core.parking import ParkingSnapshot
from simulation import config
from simulation.metrics import SimulationMetrics
from ui.fonts import font_family
from ui.projection import ParkingProjection
from ui.widgets import (
    COLOR_AVAILABLE,
    COLOR_BG_CARD,
    COLOR_BG_PRIMARY,
    COLOR_BORDER,
    COLOR_INFO,
    COLOR_OCCUPIED,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_WAITING,
    ControlBarWidget,
    EventLogWidget,
    MetricsSummaryWidget,
    ParkingLotGridWidget,
    RequestTrackingTableWidget,
    StatCard,
    WaitingQueueWidget,
)


class ParkingApp:
    """Main Tkinter application coordinating UI rendering and event consumption."""

    def __init__(
        self,
        event_queue: queue.Queue,
        simulator: Any | None = None,
        capacity: int = config.PARKING_CAPACITY,
        poll_interval_ms: int = 100,
        scenario_options: Mapping[str, tuple[str, int]] | None = None,
        on_scenario_selected: Callable[[str | None], None] | None = None,
    ) -> None:
        self.event_queue = event_queue
        self.simulator = simulator
        self.capacity = capacity
        self._default_capacity = capacity
        self._scenario_options = dict(scenario_options or {})
        self._on_scenario_selected_callback = on_scenario_selected
        self._selected_scenario_name: str | None = None
        self._selected_scenario_capacity = capacity
        self.poll_interval_ms = poll_interval_ms
        self._closing = False
        self._shutdown_complete = False
        self._poll_token = None
        self._cleanup_complete = False
        self._processing_events = False
        self._projection_unsafe = False
        self._render_failed = False
        self._recovery_used = False
        self._vehicle_plates: dict[int, str] = {}
        self._restart_polling = False
        self._close_started_at = 0.0

        # Run-local display state, independent of core's mutable internals.
        self.projection = ParkingProjection(capacity)
        self._ui_metrics = SimulationMetrics()
        self._ui_metrics_active = False
        self.occupied_count = 0
        self.waiting_count = 0
        self.total_finished = 0

        # Initialize Main Window
        self.root = tk.Tk()
        self.root.title("Smart Parking Simulator — Monitor de Concurrencia")
        self.root.geometry("1220x780")
        self.root.minsize(1020, 660)
        self.root.configure(bg=COLOR_BG_PRIMARY)

        # Build UI layout
        self._build_ui()

        # Handle window close gracefully
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Start periodic event polling loop
        self._schedule_poll()

    def _build_ui(self) -> None:
        """Construct a persistent four-view workspace with global controls."""
        style = ttk.Style(self.root)
        style.configure("Parking.TNotebook", background=COLOR_BG_PRIMARY, borderwidth=0)
        style.configure(
            "Parking.TNotebook.Tab", background=COLOR_BG_CARD,
            foreground=COLOR_TEXT_MUTED, padding=(18, 9),
        )
        style.map(
            "Parking.TNotebook.Tab",
            background=[("selected", COLOR_BG_PRIMARY)],
            foreground=[("selected", COLOR_INFO)],
        )

        # 1. Top Control Bar (Header + Start/Stop Buttons)
        self.control_bar = ControlBarWidget(
            self.root,
            on_start=self._start_simulation,
            on_stop=self._stop_simulation,
        )
        self.control_bar.pack(fill="x", padx=16, pady=(12, 8))
        self._build_scenario_selector()
        self._build_footer()

        self.views = ttk.Notebook(self.root, style="Parking.TNotebook")
        self.views.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        self.simulation_view = tk.Frame(self.views, bg=COLOR_BG_PRIMARY, padx=12, pady=12)
        self.requests_view = tk.Frame(self.views, bg=COLOR_BG_PRIMARY, padx=12, pady=12)
        self.telemetry_view = tk.Frame(self.views, bg=COLOR_BG_PRIMARY, padx=12, pady=12)
        self.events_view = tk.Frame(self.views, bg=COLOR_BG_PRIMARY, padx=12, pady=12)
        for view, title in (
            (self.simulation_view, "Simulación"),
            (self.requests_view, "Solicitudes"),
            (self.telemetry_view, "Telemetría"),
            (self.events_view, "Eventos"),
        ):
            self.views.add(view, text=title)

        # The default view contains only immediate operational state.
        self._build_stat_cards(
            self.simulation_view,
            (("occupied", "Ocupación", COLOR_OCCUPIED),
             ("available", "Disponibles", COLOR_AVAILABLE),
             ("waiting", "Pendientes", COLOR_WAITING)),
        )
        simulation_content = tk.Frame(self.simulation_view, bg=COLOR_BG_PRIMARY)
        simulation_content.pack(fill="both", expand=True, pady=(10, 8))
        simulation_content.grid_columnconfigure(0, weight=1)
        simulation_content.grid_columnconfigure(1, weight=1)
        simulation_content.grid_rowconfigure(0, weight=1)

        self.parking_grid = ParkingLotGridWidget(simulation_content, columns=3)
        self.parking_grid.grid_propagate(False)
        self.parking_grid.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.parking_grid.setup_slots(self.capacity)
        self.waiting_lane = WaitingQueueWidget(simulation_content)
        self.waiting_lane.pack_propagate(False)
        self.waiting_lane.grid(row=0, column=1, sticky="nsew", pady=5)
        tk.Button(
            self.simulation_view, text="Ver todas las solicitudes →",
            command=lambda: self.views.select(self.requests_view),
            bg=COLOR_BG_CARD, fg=COLOR_INFO, relief="flat", padx=12, pady=6,
        ).pack(anchor="e")

        self.request_table = RequestTrackingTableWidget(self.requests_view)
        self.request_table.pack(fill="both", expand=True)

        self._build_stat_cards(
            self.telemetry_view,
            (("generated", "Generados", COLOR_TEXT_PRIMARY),
             ("accepted", "Aceptados", COLOR_AVAILABLE),
             ("rejected", "Rechazados", COLOR_OCCUPIED),
             ("entries", "Ingresos", COLOR_INFO),
             ("finished", "Finalizados", COLOR_INFO),
             ("cancelled", "Cancelados", COLOR_WAITING),
             ("peak_occupancy", "Máx. ocupación", COLOR_OCCUPIED),
             ("avg_wait", "Espera promedio", COLOR_WAITING)),
        )
        self.metrics_summary = MetricsSummaryWidget(self.telemetry_view, capacity=self.capacity)
        self.metrics_summary.pack(fill="x", pady=(12, 0))
        tk.Label(
            self.telemetry_view,
            text="Arquitectura observada: proceso motor → IPC → adaptador → cola local → Tkinter",
            bg=COLOR_BG_PRIMARY, fg=COLOR_TEXT_MUTED,
            font=(font_family(self.root), 9), anchor="w",
        ).pack(fill="x", pady=(10, 0))

        self.event_log = EventLogWidget(self.events_view)
        self.event_log.pack(fill="both", expand=True)

    def _build_stat_cards(self, parent: tk.Misc, definitions: tuple) -> None:
        """Create a responsive row of cards while retaining existing counter APIs."""
        row = tk.Frame(parent, bg=COLOR_BG_PRIMARY)
        row.pack(fill="x")
        for column, (name, title, color) in enumerate(definitions):
            initial = str(self.capacity) if name == "available" else "0"
            if name == "avg_wait":
                initial = "0.00s"
            subtitle = f"de {self.capacity}" if name == "peak_occupancy" else ""
            card = StatCard(
                row, title=title, initial_value=initial,
                subtitle=subtitle, value_color=color, compact=True,
            )
            card.grid(row=0, column=column, sticky="nsew", padx=4, pady=4)
            row.grid_columnconfigure(column, weight=1, uniform="view_kpi")
            setattr(self, f"card_{name}", card)

    def _build_scenario_selector(self) -> None:
        """Offer scenario inputs without moving simulation control into the UI."""
        if not self._scenario_options:
            self.scenario_selector = None
            return

        selector_row = tk.Frame(self.root, bg=COLOR_BG_PRIMARY)
        selector_row.pack(fill="x", padx=20, pady=(0, 8))
        tk.Label(
            selector_row,
            text="Escenario de simulación",
            bg=COLOR_BG_PRIMARY,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self.root), 9, "bold"),
        ).pack(side="left", padx=(0, 10))

        self._scenario_by_label = {}
        for name, (title, capacity) in self._scenario_options.items():
            self._scenario_by_label[f"{title} · {capacity} puestos"] = name
        initial_label = next(iter(self._scenario_by_label))
        self._scenario_var = tk.StringVar(value=initial_label)
        self.scenario_selector = ttk.Combobox(
            selector_row,
            textvariable=self._scenario_var,
            values=tuple(self._scenario_by_label),
            state="readonly",
            width=58,
        )
        self.scenario_selector.pack(side="left", fill="x", expand=True)
        self.scenario_selector.bind("<<ComboboxSelected>>", self._handle_scenario_selection)
        self._handle_scenario_selection()

    def _handle_scenario_selection(self, _event: Any = None) -> None:
        """Record selection on Tk's thread; the adapter reads it when Start is pressed."""
        if self.scenario_selector is None:
            return
        name = self._scenario_by_label.get(self._scenario_var.get())
        self._selected_scenario_name = name
        if name is None:
            self._selected_scenario_capacity = self._default_capacity
        else:
            self._selected_scenario_capacity = self._scenario_options[name][1]
        if self._on_scenario_selected_callback is not None:
            self._on_scenario_selected_callback(name)

    def _set_scenario_selector_enabled(self, enabled: bool) -> None:
        selector = getattr(self, "scenario_selector", None)
        if selector is not None:
            selector.configure(state="readonly" if enabled else "disabled")

    def _apply_selected_capacity(self) -> None:
        """Resize the display to the selected run only after Core starts it."""
        capacity = getattr(self, "_selected_scenario_capacity", self.capacity)
        if capacity == self.capacity:
            return
        self.capacity = capacity
        self.projection = ParkingProjection(capacity)
        self.parking_grid.setup_slots(capacity)
        self.card_available.update_value(capacity)
        self.card_occupied.update_value(0)
        self.card_occupied.update_subtitle(f"de {capacity} ({capacity} libres)")
        self.card_waiting.update_value(0)
        self.card_peak_occupancy.update_subtitle(f"de {capacity}")
        self.metrics_summary.capacity = capacity

    def _build_footer(self) -> None:
        """Construct the bottom status bar explaining the real IPC architecture."""
        footer_frame = tk.Frame(self.root, bg=COLOR_BG_PRIMARY, padx=16, pady=4)
        footer_frame.pack(fill="x", side="bottom")

        self._lbl_arch_info = tk.Label(
            footer_frame,
            text="Arquitectura: Motor hijo → IPC → adaptador del proceso padre → cola local → Tkinter",
            bg=COLOR_BG_PRIMARY,
            fg="#64748b",
            font=(font_family(self.root), 8),
        )
        self._lbl_arch_info.pack(side="left")

        self._lbl_poll_info = tk.Label(
            footer_frame,
            text=f"Refresco: after({self.poll_interval_ms}ms) | Hilo principal Tkinter | Estado determinado por Core",
            bg=COLOR_BG_PRIMARY,
            fg="#64748b",
            font=(font_family(self.root), 8),
        )
        self._lbl_poll_info.pack(side="right")

    def _schedule_poll(self) -> None:
        """Schedule periodic queue polling on the main thread via root.after().

        This guarantees that all Tkinter widget updates are executed safely
        on the Main Thread, adhering to Tkinter's single-threaded GUI model.
        """
        if (self._closing or self._shutdown_complete
                or getattr(self, "_poll_token", None) is not None
                or getattr(self, "_processing_events", False)):
            return
        try:
            self._process_events()
        finally:
            if not self._closing and not self._shutdown_complete:
                self._poll_token = self.root.after(self.poll_interval_ms, self._poll_events)

    def _poll_events(self) -> None:
        self._poll_token = None
        if self._closing:
            self._process_events()
            return
        self._schedule_poll()

    def _process_events(self) -> bool:
        """Drain events on Tk's thread without permitting reentrant consumption."""
        if getattr(self, "_processing_events", False):
            return False
        self._processing_events = True
        try:
            return self._drain_events()
        finally:
            self._processing_events = False

    def _drain_events(self) -> bool:
        processed = 0
        limit = 128
        if self.simulator is not None and hasattr(self.simulator, "poll_results"):
            for name, run_id, error in self.simulator.poll_results():
                if name == "ERROR":
                    try:
                        self._set_status(f"ERROR: {error}")
                        if not getattr(self, "_render_failed", False):
                            self.event_log.log(
                                "ENGINE_ERROR", str(error), datetime.now().strftime("%H:%M:%S"))
                        if hasattr(self, "metrics_summary"):
                            self.metrics_summary.set_warning(
                                f"ADVERTENCIA: Ejecución o auditoría incompleta ({error})")
                    except Exception as widget_error:
                        self._fail_rendering(widget_error)
                elif name == "SHUTDOWN_COMPLETE":
                    self._shutdown_complete = True
                elif name == "CLEANUP_COMPLETE":
                    self._cleanup_complete = True
                elif name == "START_ACCEPTED":
                    # This acknowledges the command only; SIMULATION_STARTED
                    # remains the authoritative visible lifecycle event.
                    pass
        while processed < limit:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break
            except Exception:
                return False

            self._consume_event(event)
            processed += 1
        return processed < limit

    def _consume_event(self, event: Any) -> None:
        """Apply canonical state before widget effects; never replay a removed event."""
        if getattr(self, "_projection_unsafe", False):
            return
        if getattr(event, "type", None) == "SIMULATION_STARTED":
            self._apply_selected_capacity()
        try:
            canonical = deepcopy(self.projection)
            canonical.apply_event(event)
        except Exception as error:
            self._projection_unsafe = True
            self._fail_rendering(error)
            return

        if event.type == "SIMULATION_STARTED" and not getattr(self, "_render_failed", False):
            self._recovery_used = False
            self._vehicle_plates = {}
        plates = getattr(self, "_vehicle_plates", {})
        if event.vehicle_id is not None and event.plate:
            plates[event.vehicle_id] = event.plate
        if event.type in {"VEHICLE_FINISHED", "VEHICLE_CANCELLED", "VEHICLE_REJECTED"}:
            plates.pop(event.vehicle_id, None)
        self._vehicle_plates = plates

        if getattr(self, "_render_failed", False):
            self.projection = canonical
            return
        try:
            self._dispatch_event(event)
        except Exception as error:
            self.projection = canonical
            self._report_ui_error(error)
            if getattr(self, "_recovery_used", False):
                self._fail_rendering()
                return
            self._recovery_used = True
            try:
                self._rebuild_views_from_canonical_state()
                if event.type == "SIMULATION_FINISHED" and not self._closing:
                    self._schedule_restart_check()
            except Exception as rebuild_error:
                self._fail_rendering(rebuild_error)
        else:
            self.projection = canonical

    def _report_ui_error(self, error: BaseException) -> None:
        """Report through the existing audit/Tk path, with stderr as fallback."""
        try:
            reporter = getattr(self.simulator, "report_ui_error", None)
            if reporter is not None:
                reporter(error)
                return
            callback = getattr(self.root, "report_callback_exception", None)
            if callback is not None:
                callback(type(error), error, error.__traceback__)
                return
        except Exception:
            pass
        traceback.print_exception(type(error), error, error.__traceback__, file=sys.stderr)

    def _set_status(self, message: str) -> None:
        try:
            self.control_bar.set_pending(message)
        except Exception:
            print(message, file=sys.stderr)

    def _fail_rendering(self, error: BaseException | None = None) -> None:
        self._render_failed = True
        if error is not None:
            self._report_ui_error(error)
        self._on_close()

    def _record_ui_metric_event(self, event: Any) -> None:
        """Fold a processed event into the UI-local `SimulationMetrics` instance.

        Ensures displayed metrics never run ahead of events actually consumed
        by Tkinter when a backlog exists in `event_queue`.
        """
        if not hasattr(self, "_ui_metrics") or self._ui_metrics is None:
            self._ui_metrics = SimulationMetrics()
        event_type = getattr(event, "type", str(event))
        if event_type == "SIMULATION_STARTED":
            self._ui_metrics = SimulationMetrics()
            self._ui_metrics_active = True
        elif event_type in {"VEHICLE_CREATED", "VEHICLE_REJECTED"}:
            self._ui_metrics_active = True
            self._ui_metrics.record_generated()
            if event_type == "VEHICLE_CREATED":
                self._ui_metrics.record_admitted()
        if getattr(self, "_ui_metrics_active", False):
            self._ui_metrics.record_event(event)

    def _sync_tracking_views(self, vehicle_id: int | None = None) -> None:
        """Keep the grouped pending queue and request tracking table synchronized."""
        if hasattr(self.waiting_lane, "sync_from_projection"):
            self.waiting_lane.sync_from_projection(self.projection)
        if hasattr(self, "request_table"):
            if vehicle_id is not None and vehicle_id in self.projection.requests:
                self.request_table.upsert_record(self.projection.requests[vehicle_id])
            else:
                self.request_table.sync_from_projection(self.projection)

    def _rebuild_views_from_canonical_state(self) -> None:
        """Reconstruct all visual widgets from canonical projection and UI metrics.

        Called after snapshot reconciliation or if a transient widget error occurs,
        without duplicating events, requests, or metrics.
        """
        vehicle_plates = getattr(self, "_vehicle_plates", {})
        if hasattr(self.parking_grid, "render_occupied"):
            self.parking_grid.render_occupied(self.projection.occupied, self.projection.plates)
        else:
            for slot in range(1, self.capacity + 1):
                self.parking_grid.free_slot(slot)
            for slot, vehicle in self.projection.occupied.items():
                self.parking_grid.occupy_slot(
                    slot, vehicle, vehicle_plates.get(vehicle)
                    or self.projection.plates.get(vehicle))
        if hasattr(self.waiting_lane, "sync_from_projection"):
            self.waiting_lane.sync_from_projection(self.projection)
        else:
            self.waiting_lane.clear()
            for vehicle in sorted(self.projection.waiting):
                plate = (vehicle_plates.get(vehicle)
                         or self.projection.plates.get(vehicle)
                         or f"Auto #{vehicle}")
                self.waiting_lane.add_vehicle(vehicle, plate)
        if hasattr(self, "request_table"):
            self.request_table.sync_from_projection(self.projection)
        self._update_display_counters()

    def _dispatch_event(self, event: Any) -> None:
        """Dispatch a single ParkingEvent to update relevant visual components.

        Attributes follow the team contract defined in AGENTS.md (Section 4):
        - event.type: Event type string (e.g. VEHICLE_ENTERED, VEHICLE_WAITING)
        - event.timestamp: Epoch timestamp
        - event.vehicle_id: Optional integer request ID
        - event.space_id: Optional integer ID of the assigned parking slot
        - event.waiting_time: Optional float duration spent in WAITING state
        """
        event_type = getattr(event, "type", str(event))
        timestamp = getattr(event, "timestamp", time.time())
        vehicle_id = getattr(event, "vehicle_id", None)
        space_id = getattr(event, "space_id", None)
        waiting_time = getattr(event, "waiting_time", None)
        vehicle_plate = getattr(event, "plate", None)
        plate = vehicle_plate or f"Auto #{vehicle_id}"
        authorized_space_id = getattr(event, "authorized_space_id", None)
        reason = getattr(event, "reason", None)

        time_str = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")
        slot_key = self.projection.apply_event(event)
        self._record_ui_metric_event(event)

        try:
            # 1. Simulation Lifecycle: Started
            if event_type == "SIMULATION_STARTED":
                self.parking_grid.reset()
                self.waiting_lane.clear()
                if hasattr(self, "request_table"):
                    self.request_table.clear()
                if hasattr(self, "metrics_summary"):
                    self.metrics_summary.reset()
                self._update_display_counters()
                if not self._closing:
                    self.control_bar.set_running()
                self.event_log.log(
                    event_type,
                    "Simulación iniciada. Productor de vehículos activo.",
                    time_str,
                )

            # 2. Simulation Lifecycle: Finished
            elif event_type == "SIMULATION_FINISHED":
                self._update_display_counters()
                if not self._closing:
                    self.control_bar.set_pending("FINALIZANDO")
                    self._schedule_restart_check()
                self.event_log.log(
                    event_type,
                    f"Simulación terminada. Finalizaciones normales: {self.total_finished}.",
                    time_str,
                )

            # 3. OS Concept: Vehicle request created (state: CREATED)
            elif event_type == "VEHICLE_CREATED":
                self._sync_tracking_views(vehicle_id)
                self._update_display_counters()
                msg = f"Solicitud #{vehicle_id} creada: {plate}."
                self.event_log.log(event_type, msg, time_str)

            # 4. OS Concept: Request waits for an eligible resource (state: WAITING)
            elif event_type == "VEHICLE_WAITING":
                if (vehicle_id is not None
                        and not hasattr(self.waiting_lane, "sync_from_projection")):
                    self.waiting_lane.add_vehicle(vehicle_id, plate)
                self._sync_tracking_views(vehicle_id)
                self._update_display_counters()

                # Core reports waiting_time on VEHICLE_ENTERED, not while waiting.
                destination = (
                    f" para Espacio autorizado #{authorized_space_id + 1}"
                    if authorized_space_id is not None
                    else ""
                )
                msg = f"{plate} (#{vehicle_id}) en espera{destination}."
                self.event_log.log(event_type, msg, time_str)

            # 5. OS Concept: Request acquired a slot (state: PARKED)
            elif event_type == "VEHICLE_ENTERED":
                if (vehicle_id is not None
                        and not hasattr(self.waiting_lane, "sync_from_projection")):
                    self.waiting_lane.remove_vehicle(vehicle_id)
                if slot_key is not None and vehicle_id is not None:
                    self.parking_grid.occupy_slot(slot_key, vehicle_id, vehicle_plate)
                self._sync_tracking_views(vehicle_id)
                self._update_display_counters()

                wait_info = (
                    f" tras esperar {waiting_time:.2f}s"
                    if waiting_time is not None
                    else ""
                )
                msg = f"{plate} (#{vehicle_id}) ingresó al Espacio #{slot_key}{wait_info}."
                self.event_log.log(event_type, msg, time_str)

            # 6. OS Concept: Request released its slot resource
            elif event_type == "VEHICLE_EXITED":
                if slot_key is not None:
                    self.parking_grid.free_slot(slot_key)
                self._sync_tracking_views(vehicle_id)
                self._update_display_counters()

                msg = f"{plate} (#{vehicle_id}) salió del Espacio #{slot_key}."
                self.event_log.log(event_type, msg, time_str)

            # 7. OS Concept: Request completed normally (state: FINISHED)
            elif event_type == "VEHICLE_FINISHED":
                if vehicle_id is not None:
                    self.waiting_lane.remove_vehicle(vehicle_id)
                self._sync_tracking_views(vehicle_id)
                self._update_display_counters()
                msg = f"{plate} (#{vehicle_id}) finalizó normalmente."
                self.event_log.log(event_type, msg, time_str)

            elif event_type == "VEHICLE_REJECTED":
                self._sync_tracking_views(vehicle_id)
                self.event_log.log(
                    event_type,
                    f"Solicitud #{vehicle_id} ({plate}) rechazada: {reason or 'motivo no informado'}.",
                    time_str,
                )
                self._update_display_counters()

            elif event_type == "VEHICLE_CANCELLED":
                if vehicle_id is not None:
                    self.waiting_lane.remove_vehicle(vehicle_id)
                self._sync_tracking_views(vehicle_id)
                self._update_display_counters()
                self.event_log.log(
                    event_type,
                    f"{plate} (#{vehicle_id}) cancelado mientras esperaba.",
                    time_str,
                )

            elif event_type == "ENGINE_ERROR":
                err_detail = reason or "Fallo inesperado en el motor."
                self.control_bar.set_pending(f"ERROR: {err_detail}")
                if hasattr(self, "metrics_summary"):
                    self.metrics_summary.set_warning(
                        f"Advertencia: Ejecución o auditoría incompleta ({err_detail})"
                    )
                self.event_log.log(
                    event_type,
                    f"Error del motor: {err_detail}",
                    time_str,
                )

            # Fallback for generic or custom events
            else:
                msg = f"Vehículo #{vehicle_id}, Espacio #{space_id}."
                self.event_log.log(event_type, msg, time_str)
        except Exception as error:
            self._report_ui_error(error)
            if getattr(self, "_recovery_used", False):
                self._fail_rendering()
                return
            self._recovery_used = True
            try:
                self._rebuild_views_from_canonical_state()
                if event_type == "SIMULATION_FINISHED" and not self._closing:
                    self._schedule_restart_check()
            except Exception as rebuild_error:
                self._fail_rendering(rebuild_error)

    def _active_metrics_source(self) -> tuple[Any, dict[str, Any]]:
        """Return the metrics object and snapshot coherent with UI-processed events."""
        sim_metrics = getattr(getattr(self, "simulator", None), "metrics", None)
        ui_metrics = getattr(self, "_ui_metrics", None)
        ui_active = getattr(self, "_ui_metrics_active", False)
        queue_has_backlog = not self.event_queue.empty()

        # If simulator.metrics is a real SimulationMetrics and either the UI queue
        # still has unprocessed events or _ui_metrics is actively tracking the run,
        # use _ui_metrics so counters never jump ahead of processed UI events.
        if (
            ui_metrics is not None
            and isinstance(sim_metrics, SimulationMetrics)
            and (queue_has_backlog or ui_active)
        ):
            ui_snap = ui_metrics.snapshot()
            sim_snap = sim_metrics.snapshot()
            # Only fall back to sim_metrics if a test populated sim_metrics directly
            # without dispatching SIMULATION_STARTED / VEHICLE_CREATED through the UI.
            if ui_snap.get("total_generated", 0) > 0 or queue_has_backlog:
                return ui_metrics, ui_snap
            return sim_metrics, sim_snap

        if sim_metrics is not None:
            return sim_metrics, sim_metrics.snapshot()
        if ui_metrics is not None and ui_active:
            return ui_metrics, ui_metrics.snapshot()
        return None, {}

    def _update_display_counters(self) -> None:
        """Keep cards synchronized with the projected grid and UI-processed events."""
        self.occupied_count = self.projection.occupied_count
        self.waiting_count = len(self.projection.waiting)

        self.card_occupied.update_value(self.occupied_count)
        if hasattr(self.card_occupied, "update_subtitle"):
            self.card_occupied.update_subtitle(
                f"de {self.capacity} ({self.projection.available_count} libres)"
            )
        if hasattr(self, "card_available"):
            self.card_available.update_value(self.projection.available_count)
        if hasattr(self, "card_waiting"):
            self.card_waiting.update_value(self.waiting_count)

        self.total_finished = self.projection.finished_count
        self.card_finished.update_value(self.total_finished)

        metrics_obj, snapshot = self._active_metrics_source()
        self.card_generated.update_value(snapshot.get("total_generated", 0))
        self.card_accepted.update_value(snapshot.get("total_admitted", 0))
        self.card_rejected.update_value(snapshot.get("total_rejected", 0))
        self.card_entries.update_value(snapshot.get("total_parked", 0))
        self.card_cancelled.update_value(snapshot.get("total_cancelled", 0))

        if hasattr(self, "card_peak_occupancy"):
            self.card_peak_occupancy.update_value(snapshot.get("peak_occupancy", 0))
        if hasattr(self, "card_avg_wait"):
            avg_wait = float(snapshot.get("average_waiting_time") or 0.0)
            self.card_avg_wait.update_value(f"{avg_wait:.2f}s")

        if hasattr(self, "metrics_summary"):
            report_text = (
                metrics_obj.report()
                if metrics_obj is not None
                and hasattr(metrics_obj, "report")
                and snapshot.get("total_duration") is not None
                else None
            )
            sim_err = getattr(getattr(self, "simulator", None), "error", None)
            warning = (
                f"ADVERTENCIA: Ejecución o auditoría incompleta ({sim_err})"
                if sim_err is not None
                else None
            )
            self.metrics_summary.update_from_snapshot(
                snapshot, report_text=report_text, warning=warning
            )

    def _reconcile_snapshot(self, snapshot: ParkingSnapshot) -> None:
        """Refresh displayed occupancy from a safe core snapshot when supplied."""
        self.projection.reconcile_snapshot(snapshot)
        self._rebuild_views_from_canonical_state()

    def _start_simulation(self) -> None:
        """Trigger simulator start if provided."""
        if self._closing:
            return
        if self.simulator is not None:
            if hasattr(self.simulator, "start"):
                self._set_scenario_selector_enabled(False)
                if self.simulator.start():
                    self.control_bar.set_pending("INICIANDO")
                else:
                    self._set_scenario_selector_enabled(True)
                    self.control_bar.set_pending("INICIO RECHAZADO")
                    self.event_log.log(
                        "START_REFUSED",
                        "Start refused: the previous run has not fully exited or drained.",
                        datetime.now().strftime("%H:%M:%S"),
                    )
                    self._schedule_restart_check()
            elif hasattr(self.simulator, "run"):
                self.simulator.run()
        else:
            self._set_scenario_selector_enabled(False)
            self.control_bar.set_running()
            now_str = datetime.now().strftime("%H:%M:%S")
            self.event_log.log(
                "SIMULATION_STARTED",
                "Modo demo UI (sin simulador conectado).",
                now_str,
            )

    def _stop_simulation(self) -> None:
        """Trigger simulator stop if provided and reflect stop-requested state."""
        if self._closing:
            return
        if self.simulator is not None:
            if hasattr(self.simulator, "stop"):
                self.control_bar.set_pending("DETENCIÓN SOLICITADA")
                self.simulator.stop()
        else:
            self._set_scenario_selector_enabled(False)
            self.control_bar.set_stopped()
            now_str = datetime.now().strftime("%H:%M:%S")
            self.event_log.log(
                "SIMULATION_FINISHED",
                "Simulación demo detenida por el usuario.",
                now_str,
            )

    def _on_close(self) -> None:
        """Request a stop once and let Tk continue processing while the run drains."""
        if self._closing:
            return
        self._closing = True
        self._close_started_at = time.monotonic()
        self._set_status("CERRANDO: esperando vehículos")
        if self.simulator is not None and hasattr(self.simulator, "shutdown_async"):
            self.simulator.shutdown_async()
        elif self.simulator is not None and self.simulator.is_active():
            self.simulator.stop()
        self._check_shutdown()

    def _check_shutdown(self) -> None:
        """Destroy only after the background thread and its lot have both drained."""
        queue_drained = self._process_events()
        if self.simulator is not None and hasattr(self.simulator, "shutdown_complete"):
            if self.simulator.shutdown_complete and queue_drained:
                self._shutdown_complete = True
                self.root.destroy()
                return
            if getattr(self.simulator, "cleanup_complete", False) and queue_drained:
                self._set_status("ERROR: proceso detenido; auditoría/ejecución incompleta")
                self._shutdown_complete = True
                self.root.destroy()
                return
            if self.simulator.error is not None:
                self._set_status(f"ERROR: shutdown incomplete: {self.simulator.error}")
        elif self.simulator is None or (
            not self.simulator.is_active() and self.simulator.is_drained()
        ):
            if queue_drained:
                self._shutdown_complete = True
                self.root.destroy()
                return
            self._set_status("WARNING: event queue drain failed")
        if time.monotonic() - self._close_started_at >= config.SHUTDOWN_DRAIN_WARNING_SECONDS:
            self._set_status("WARNING: shutdown still waiting for drain")
        self.root.after(config.SHUTDOWN_POLL_INTERVAL_MS, self._check_shutdown)

    def _schedule_restart_check(self) -> None:
        if not self._restart_polling and not self._closing:
            self._restart_polling = True
            self.root.after(config.SHUTDOWN_POLL_INTERVAL_MS, self._check_restart)

    def _check_restart(self) -> None:
        self._restart_polling = False
        if self._closing:
            return
        if not self.simulator.is_active():
            if self.simulator.is_drained():
                self.control_bar.set_stopped()
                self._set_scenario_selector_enabled(True)
            else:
                self.control_bar.set_pending("ERROR: shutdown did not drain")
        else:
            self._schedule_restart_check()

    def run(self) -> None:
        """Start the Tkinter main event loop."""
        self.root.mainloop()


# --- Standalone UI Preview Demo ---
# This block runs ONLY when executing `python3 -m ui.interface` directly.
# It enables testing and previewing the GUI without needing the core or simulation modules.
if __name__ == "__main__":
    import threading

    class MockParkingEvent:
        """Simple, explicit event class for standalone GUI demonstration."""

        def __init__(
            self,
            type: str,
            timestamp: float,
            vehicle_id: int | None = None,
            space_id: int | None = None,
            waiting_time: float | None = None,
        ) -> None:
            self.type = type
            self.timestamp = timestamp
            self.vehicle_id = vehicle_id
            self.space_id = space_id
            self.waiting_time = waiting_time

    demo_queue: queue.Queue = queue.Queue()
    app = ParkingApp(event_queue=demo_queue, capacity=config.PARKING_CAPACITY)

    def _demo_producer() -> None:
        """Simulate incoming concurrency events in a background thread."""
        time.sleep(1.0)
        demo_queue.put(MockParkingEvent(type="SIMULATION_STARTED", timestamp=time.time()))
        time.sleep(0.5)

        # Vehicles arrive: core spaces 0 to 4 fill; vehicles 6 and 7 wait.
        for i in range(1, 8):
            demo_queue.put(
                MockParkingEvent(type="VEHICLE_CREATED", timestamp=time.time(), vehicle_id=i)
            )
            time.sleep(0.3)

            if i <= 5:
                # Capacity available: core assigns zero-based space i - 1.
                demo_queue.put(
                    MockParkingEvent(
                        type="VEHICLE_ENTERED",
                        timestamp=time.time(),
                        vehicle_id=i,
                        space_id=i - 1,
                        waiting_time=0.0,
                    )
                )
            else:
                # Capacity full: vehicle enters WAITING state
                demo_queue.put(
                    MockParkingEvent(
                        type="VEHICLE_WAITING",
                        timestamp=time.time(),
                        vehicle_id=i,
                        waiting_time=1.5,
                    )
                )
            time.sleep(0.6)

        time.sleep(2.0)
        # Vehicle 1 leaves its slot and terminates
        demo_queue.put(
            MockParkingEvent(
                type="VEHICLE_EXITED",
                timestamp=time.time(),
                vehicle_id=1,
                space_id=0,
            )
        )
        demo_queue.put(
            MockParkingEvent(
                type="VEHICLE_FINISHED",
                timestamp=time.time(),
                vehicle_id=1,
            )
        )
        time.sleep(0.5)

        # Vehicle 6 waiting gets the released core space 0.
        demo_queue.put(
            MockParkingEvent(
                type="VEHICLE_ENTERED",
                timestamp=time.time(),
                vehicle_id=6,
                space_id=0,
                waiting_time=3.2,
            )
        )

    threading.Thread(target=_demo_producer, daemon=True).start()
    app.run()
