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
import time
from datetime import datetime
import tkinter as tk
from typing import Any

from core.parking import ParkingSnapshot
from simulation import config
from ui.fonts import font_family
from ui.projection import ParkingProjection
from ui.widgets import (
    COLOR_AVAILABLE,
    COLOR_BG_PRIMARY,
    COLOR_INFO,
    COLOR_OCCUPIED,
    COLOR_TEXT_PRIMARY,
    COLOR_WAITING,
    ControlBarWidget,
    EventLogWidget,
    MetricsSummaryWidget,
    ParkingLotGridWidget,
    StatCard,
    WaitingQueueWidget,
)


class ParkingApp:
    """Main Tkinter application coordinating UI rendering and event consumption."""

    def __init__(
        self,
        event_queue: queue.Queue,
        simulator: Any | None = None,
        capacity: int = 5,
        poll_interval_ms: int = 100,
    ) -> None:
        self.event_queue = event_queue
        self.simulator = simulator
        self.capacity = capacity
        self.poll_interval_ms = poll_interval_ms
        self._closing = False
        self._shutdown_complete = False
        self._restart_polling = False
        self._close_started_at = 0.0

        # Run-local display state, independent of core's mutable internals.
        self.projection = ParkingProjection(capacity)
        self.occupied_count = 0
        self.waiting_count = 0
        self.total_finished = 0

        # Initialize Main Window
        self.root = tk.Tk()
        self.root.title("Smart Parking Simulator — Monitor de Concurrencia")
        self.root.geometry("1160x740")
        self.root.minsize(980, 620)
        self.root.configure(bg=COLOR_BG_PRIMARY)

        # Build UI layout
        self._build_ui()

        # Handle window close gracefully
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Start periodic event polling loop
        self._schedule_poll()

    def _build_ui(self) -> None:
        """Construct the entire visual hierarchy."""
        # 1. Top Control Bar (Header + Start/Stop Buttons)
        self.control_bar = ControlBarWidget(
            self.root,
            on_start=self._start_simulation,
            on_stop=self._stop_simulation,
        )
        self.control_bar.pack(fill="x", padx=16, pady=(16, 10))

        # 2. Status Bar (Footer) packed at bottom before center_frame expands
        self._build_footer()

        # 3. Main Dashboard Area (Grid Split: Left Workspace / Full-Height Right Event Log)
        center_frame = tk.Frame(self.root, bg=COLOR_BG_PRIMARY)
        center_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        center_frame.grid_columnconfigure(0, weight=5, minsize=540)
        center_frame.grid_columnconfigure(1, weight=4, minsize=380)
        center_frame.grid_rowconfigure(0, weight=1)

        # Left Column: KPI Cards + Parking Bay Grid + Waiting Queue + Telemetry Summary
        left_col = tk.Frame(center_frame, bg=COLOR_BG_PRIMARY)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        # KPI Stat Cards Grid (2 rows so 7 cards never squish on narrow screens)
        stats_frame = tk.Frame(left_col, bg=COLOR_BG_PRIMARY)
        stats_frame.pack(fill="x", pady=(0, 10))

        kpi_definitions = (
            ("generated", "Generados", COLOR_TEXT_PRIMARY, ""),
            ("accepted", "Aceptados", COLOR_AVAILABLE, ""),
            ("rejected", "Rechazados", COLOR_OCCUPIED, ""),
            ("entries", "Ingresos", COLOR_INFO, ""),
            ("occupied", "Ocupación actual", COLOR_OCCUPIED, f"de {self.capacity} ({self.capacity} libres)"),
            ("finished", "Finalizados", COLOR_INFO, ""),
            ("cancelled", "Cancelados", COLOR_WAITING, ""),
        )
        kpi_columns = 4
        for idx, (name, title, color, subtitle) in enumerate(kpi_definitions):
            row = idx // kpi_columns
            col = idx % kpi_columns
            card = StatCard(
                stats_frame,
                title=title,
                initial_value="0",
                subtitle=subtitle,
                value_color=color,
            )
            card.grid(
                row=row,
                column=col,
                sticky="nsew",
                padx=(0, 6 if col < kpi_columns - 1 else 0),
                pady=(0, 6 if row == 0 else 0),
            )
            setattr(self, f"card_{name}", card)

        for col_idx in range(kpi_columns):
            stats_frame.grid_columnconfigure(col_idx, weight=1, uniform="kpi_col")

        # Visual Grid of Parking Slots (expand=False keeps proportional height when maximized)
        self.parking_grid = ParkingLotGridWidget(left_col, columns=5)
        self.parking_grid.pack(fill="x", expand=False, pady=(0, 10))
        self.parking_grid.setup_slots(self.capacity)

        # Visual Waiting Queue Lane
        self.waiting_lane = WaitingQueueWidget(left_col)
        self.waiting_lane.pack(fill="x", pady=(0, 10))

        # Extended Telemetry & Final Report Summary Panel
        self.metrics_summary = MetricsSummaryWidget(left_col, capacity=self.capacity)
        self.metrics_summary.pack(fill="x")

        # Right Column: Full-height Live Event Log Terminal with guaranteed width
        right_col = tk.Frame(center_frame, bg=COLOR_BG_PRIMARY)
        right_col.grid(row=0, column=1, sticky="nsew")

        self.event_log = EventLogWidget(right_col)
        self.event_log.pack(fill="both", expand=True)

    def _build_footer(self) -> None:
        """Construct the bottom status bar displaying OS concepts."""
        footer_frame = tk.Frame(self.root, bg=COLOR_BG_PRIMARY, padx=16, pady=4)
        footer_frame.pack(fill="x", side="bottom")

        lbl_os_info = tk.Label(
            footer_frame,
            text="SO Concept: Semaphore (Capacidad) | Mutex Lock (Asignación) | Queue (Workers -> UI)",
            bg=COLOR_BG_PRIMARY,
            fg="#64748b",
            font=(font_family(self.root), 8),
        )
        lbl_os_info.pack(side="left")

        self._lbl_poll_info = tk.Label(
            footer_frame,
            text=f"Refresco: after({self.poll_interval_ms}ms) | Hilo Tkinter: Main",
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
        self._process_events()
        if not self._shutdown_complete:
            self.root.after(self.poll_interval_ms, self._schedule_poll)

    def _process_events(self) -> bool:
        """Drain all available events from the thread-safe queue.Queue.

        Acts as the consumer in the Producer-Consumer pattern.
        """
        processed = 0
        limit = 128
        if self.simulator is not None and hasattr(self.simulator, "poll_results"):
            for name, run_id, error in self.simulator.poll_results():
                if name == "ERROR":
                    self.control_bar.set_pending(f"ERROR: {error}")
                    self.event_log.log("ENGINE_ERROR", str(error), datetime.now().strftime("%H:%M:%S"))
                # CLEANUP_COMPLETE and START_ACCEPTED need no handling here:
                # _check_shutdown reads simulator.cleanup_complete directly, and
                # SIMULATION_STARTED remains the authoritative lifecycle event.
        while processed < limit:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break
            except Exception:
                return False

            self._dispatch_event(event)
            processed += 1
        return processed < limit

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

        # 1. Simulation Lifecycle: Started
        if event_type == "SIMULATION_STARTED":
            self.parking_grid.reset()
            self.waiting_lane.clear()
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
            # Generated/accepted cards must not depend on a later event.
            self._update_display_counters()
            msg = f"Solicitud #{vehicle_id} creada: {plate}."
            self.event_log.log(event_type, msg, time_str)

        # 4. OS Concept: Request waits for an eligible resource (state: WAITING)
        elif event_type == "VEHICLE_WAITING":
            if vehicle_id is not None:
                self.waiting_lane.add_vehicle(vehicle_id, plate)
            self._update_display_counters()

            # Core reports waiting_time on VEHICLE_ENTERED, not while waiting.
            destination = (f" para Espacio autorizado #{authorized_space_id + 1}"
                           if authorized_space_id is not None else "")
            msg = f"{plate} (#{vehicle_id}) en espera{destination}."
            self.event_log.log(event_type, msg, time_str)

        # 5. OS Concept: Request acquired a slot (state: PARKED)
        elif event_type == "VEHICLE_ENTERED":
            if vehicle_id is not None:
                self.waiting_lane.remove_vehicle(vehicle_id)
            if slot_key is not None and vehicle_id is not None:
                self.parking_grid.occupy_slot(slot_key, vehicle_id, vehicle_plate)
            self._update_display_counters()

            wait_info = f" tras esperar {waiting_time:.2f}s" if waiting_time is not None else ""
            msg = f"{plate} (#{vehicle_id}) ingresó al Espacio #{slot_key}{wait_info}."
            self.event_log.log(event_type, msg, time_str)

        # 6. OS Concept: Request released its slot resource
        elif event_type == "VEHICLE_EXITED":
            if slot_key is not None:
                self.parking_grid.free_slot(slot_key)
            self._update_display_counters()

            msg = f"{plate} (#{vehicle_id}) salió del Espacio #{slot_key}."
            self.event_log.log(event_type, msg, time_str)

        # 7. OS Concept: Request completed normally (state: FINISHED)
        elif event_type == "VEHICLE_FINISHED":
            if vehicle_id is not None:
                self.waiting_lane.remove_vehicle(vehicle_id)
            self._update_display_counters()
            msg = f"{plate} (#{vehicle_id}) finalizó normalmente."
            self.event_log.log(event_type, msg, time_str)

        elif event_type == "VEHICLE_REJECTED":
            self.event_log.log(event_type, f"Solicitud #{vehicle_id} ({plate}) rechazada: {reason or 'motivo no informado'}.", time_str)
            self._update_display_counters()

        elif event_type == "VEHICLE_CANCELLED":
            if vehicle_id is not None:
                self.waiting_lane.remove_vehicle(vehicle_id)
            self._update_display_counters()
            self.event_log.log(event_type, f"{plate} (#{vehicle_id}) cancelado mientras esperaba.", time_str)

        # Fallback for generic or custom events
        else:
            msg = f"Vehículo #{vehicle_id}, Espacio #{space_id}."
            self.event_log.log(event_type, msg, time_str)

    def _update_display_counters(self) -> None:
        """Keep cards synchronized with the projected grid and waiting IDs."""
        self.occupied_count = self.projection.occupied_count
        self.waiting_count = len(self.projection.waiting)
        self.card_occupied.update_value(self.occupied_count)
        if hasattr(self.card_occupied, "update_subtitle"):
            self.card_occupied.update_subtitle(
                f"de {self.capacity} ({self.projection.available_count} libres)"
            )
        self.total_finished = self.projection.finished_count
        self.card_finished.update_value(self.total_finished)
        metrics = getattr(getattr(self, "simulator", None), "metrics", None)
        snapshot = metrics.snapshot() if metrics is not None else {}
        self.card_generated.update_value(snapshot.get("total_generated", 0))
        self.card_accepted.update_value(snapshot.get("total_admitted", 0))
        self.card_rejected.update_value(snapshot.get("total_rejected", 0))
        self.card_entries.update_value(snapshot.get("total_parked", 0))
        self.card_cancelled.update_value(snapshot.get("total_cancelled", 0))
        if hasattr(self, "metrics_summary"):
            report_text = (
                metrics.report()
                if metrics is not None
                and hasattr(metrics, "report")
                and snapshot.get("total_duration") is not None
                else None
            )
            self.metrics_summary.update_from_snapshot(snapshot, report_text=report_text)

    def _reconcile_snapshot(self, snapshot: ParkingSnapshot) -> None:
        """Refresh displayed occupancy from a safe core snapshot when supplied."""
        self.projection.reconcile_snapshot(snapshot)
        self.parking_grid.render_occupied(self.projection.occupied, self.projection.plates)
        self._update_display_counters()

    def _start_simulation(self) -> None:
        """Trigger simulator start if provided."""
        if self._closing:
            return
        if self.simulator is not None:
            if hasattr(self.simulator, "start"):
                if self.simulator.start():
                    self.control_bar.set_pending("INICIANDO")
                else:
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
            self.control_bar.set_running()
            now_str = datetime.now().strftime("%H:%M:%S")
            self.event_log.log(
                "SIMULATION_STARTED",
                "Modo demo UI (sin simulador conectado).",
                now_str,
            )

    def _stop_simulation(self) -> None:
        """Trigger simulator stop if provided."""
        if self._closing:
            return
        if self.simulator is not None:
            if hasattr(self.simulator, "stop"):
                self.simulator.stop()
        else:
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
        self.control_bar.set_pending("CERRANDO: esperando vehículos")
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
                self.control_bar.set_pending("ERROR: proceso detenido; auditoría/ejecución incompleta")
                self._shutdown_complete = True
                self.root.destroy()
                return
            if self.simulator.error is not None:
                self.control_bar.set_pending(f"ERROR: shutdown incomplete: {self.simulator.error}")
        elif self.simulator is None or (
            not self.simulator.is_active() and self.simulator.is_drained()
        ):
            if queue_drained:
                self._shutdown_complete = True
                self.root.destroy()
                return
            self.control_bar.set_pending("WARNING: event queue drain failed")
        if time.monotonic() - self._close_started_at >= config.SHUTDOWN_DRAIN_WARNING_SECONDS:
            self.control_bar.set_pending("WARNING: shutdown still waiting for drain")
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
    app = ParkingApp(event_queue=demo_queue, capacity=5)

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
