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
        self._poll_token = None
        self._processing_events = False
        self._shutdown_checking = False
        self._recovery_used = False
        self._render_failed = False
        self._projection_unsafe = False
        self._vehicle_plates: dict[int, str] = {}

        # Run-local display state, independent of core's mutable internals.
        self.projection = ParkingProjection(capacity)
        self.occupied_count = 0
        self.waiting_count = 0
        self.total_finished = 0

        # Initialize Main Window
        self.root = tk.Tk()
        self.root.title("Smart Parking Simulator — Monitor de Concurrencia")
        self.root.geometry("1100x740")
        self.root.minsize(900, 600)
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

        # 2. KPI Stat Cards Row (run-local event metrics)
        stats_frame = tk.Frame(self.root, bg=COLOR_BG_PRIMARY)
        stats_frame.pack(fill="x", padx=16, pady=(0, 12))

        for name, title, color in (
            ("generated", "Generados", COLOR_TEXT_PRIMARY),
            ("accepted", "Aceptados", COLOR_AVAILABLE),
            ("rejected", "Rechazados", COLOR_OCCUPIED),
            ("entries", "Ingresos", COLOR_INFO),
            ("occupied", "Ocupación actual", COLOR_OCCUPIED),
            ("finished", "Finalizados", COLOR_INFO),
            ("cancelled", "Cancelados", COLOR_WAITING),
        ):
            card = StatCard(stats_frame, title=title, initial_value="0", value_color=color)
            card.pack(side="left", fill="both", expand=True, padx=(0, 5))
            setattr(self, f"card_{name}", card)

        # 3. Main Center Area (Split Left / Right)
        center_frame = tk.Frame(self.root, bg=COLOR_BG_PRIMARY)
        center_frame.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        # Left Column: Parking Bay Grid + Waiting Queue Lane
        left_col = tk.Frame(center_frame, bg=COLOR_BG_PRIMARY)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 10))

        # Visual Grid of Parking Slots
        self.parking_grid = ParkingLotGridWidget(left_col, columns=5)
        self.parking_grid.pack(fill="both", expand=True, pady=(0, 10))
        self.parking_grid.setup_slots(self.capacity)

        # Visual Waiting Queue Lane
        self.waiting_lane = WaitingQueueWidget(left_col)
        self.waiting_lane.pack(fill="x")

        # Right Column: Live Event Log Terminal
        right_col = tk.Frame(center_frame, bg=COLOR_BG_PRIMARY, width=420)
        right_col.pack(side="right", fill="both", expand=False)
        right_col.pack_propagate(False)

        self.event_log = EventLogWidget(right_col)
        self.event_log.pack(fill="both", expand=True)

        # 4. Status Bar (Footer)
        self._build_footer()

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
        if (self._closing or self._shutdown_complete
                or getattr(self, '_poll_token', None) is not None
                or getattr(self, '_processing_events', False)):
            return
        try:
            self._process_events()
        finally:
            if not self._closing and not self._shutdown_complete:
                self._poll_token = self.root.after(self.poll_interval_ms, self._poll_events)

    def _poll_events(self) -> None:
        self._poll_token = None
        self._schedule_poll()

    def _process_events(self) -> bool:
        """Drain all available events from the thread-safe queue.Queue.

        Acts as the consumer in the Producer-Consumer pattern.
        """
        if getattr(self, '_processing_events', False):
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
                    self._set_status(f"ERROR: {error}")
                    if not getattr(self, '_render_failed', False):
                        try:
                            self.event_log.log("ENGINE_ERROR", str(error), datetime.now().strftime("%H:%M:%S"))
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
        """Fold before rendering; a removed event is never requeued or replayed."""
        if getattr(self, '_projection_unsafe', False):
            return  # Drain transport even when the visual model cannot be trusted.
        try:
            canonical = deepcopy(self.projection)
            canonical.apply_event(event)
        except Exception as error:
            self._projection_unsafe = True
            self._fail_rendering(error)
            return
        if event.type == 'SIMULATION_STARTED' and not getattr(self, '_render_failed', False):
            self._recovery_used = False
            self._vehicle_plates = {}
        plates = getattr(self, '_vehicle_plates', {})
        if event.vehicle_id is not None and event.plate:
            plates[event.vehicle_id] = event.plate
        if event.type in {'VEHICLE_FINISHED', 'VEHICLE_CANCELLED', 'VEHICLE_REJECTED'}:
            plates.pop(event.vehicle_id, None)
        self._vehicle_plates = plates
        if getattr(self, '_render_failed', False):
            self.projection = canonical
            return
        try:
            self._dispatch_event(event)
        except Exception as error:
            self.projection = canonical
            self._report_ui_error(error)
            if getattr(self, '_recovery_used', False):
                self._fail_rendering()
                return
            self._recovery_used = True
            try:
                self._rebuild_view()
                if event.type == 'SIMULATION_FINISHED' and not self._closing:
                    self._schedule_restart_check()
            except Exception as rebuild_error:
                self._fail_rendering(rebuild_error)
        else:
            self.projection = canonical

    def _rebuild_view(self) -> None:
        """Reconcile only stateful widgets, never logs, metrics or event callbacks."""
        for slot in range(1, self.capacity + 1):
            self.parking_grid.free_slot(slot)
        for slot, vehicle in self.projection.occupied.items():
            self.parking_grid.occupy_slot(slot, vehicle, self._vehicle_plates.get(vehicle))
        self.waiting_lane.clear()
        for vehicle in sorted(self.projection.waiting):
            self.waiting_lane.add_vehicle(vehicle, self._vehicle_plates.get(vehicle) or f'Auto #{vehicle}')
        self._update_display_counters()
        if not self._closing and self.simulator is not None and self.simulator.is_active():
            self.control_bar.set_running()
        # A status-widget failure must not invalidate an otherwise coherent view.
        try:
            self._lbl_poll_info.configure(text='UI error: display recovered; see diagnostics')
        except Exception:
            print('UI error: display recovered; see diagnostics', file=sys.stderr)

    def _report_ui_error(self, error: BaseException) -> None:
        """Persist once through the parent writer, with a nonrecursive fallback."""
        try:
            reporter = getattr(self.simulator, 'report_ui_error', None)
            if reporter is not None:
                reporter(error)
                return
            callback = getattr(self.root, 'report_callback_exception', None)
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
            msg = f"Solicitud #{vehicle_id} creada: {plate}."
            self.event_log.log(event_type, msg, time_str)

        # 4. OS Concept: Request waits for an eligible resource (state: WAITING)
        elif event_type == "VEHICLE_WAITING":
            if vehicle_id is not None:
                self.waiting_lane.add_vehicle(vehicle_id, plate)
            self._update_display_counters()

            wait_info = f" (espera inicial: {waiting_time:.2f}s)" if waiting_time is not None else ""
            destination = (f" para Espacio autorizado #{authorized_space_id + 1}"
                           if authorized_space_id is not None else "")
            msg = f"{plate} (#{vehicle_id}) en espera{destination}{wait_info}."
            self.event_log.log(event_type, msg, time_str)

        # 5. OS Concept: Request acquired a slot (state: PARKED)
        elif event_type == "VEHICLE_ENTERED":
            if vehicle_id is not None:
                self.waiting_lane.remove_vehicle(vehicle_id)
            if slot_key is not None and vehicle_id is not None:
                self.parking_grid.occupy_slot(slot_key, vehicle_id, vehicle_plate)
            self._update_display_counters()

            msg = f"{plate} (#{vehicle_id}) ingresó al Espacio #{slot_key}."
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
        self.total_finished = self.projection.finished_count
        self.card_finished.update_value(self.total_finished)
        metrics = getattr(getattr(self, "simulator", None), "metrics", None)
        snapshot = metrics.snapshot() if metrics is not None else {}
        self.card_generated.update_value(snapshot.get("total_generated", 0))
        self.card_accepted.update_value(snapshot.get("total_admitted", 0))
        self.card_rejected.update_value(snapshot.get("total_rejected", 0))
        self.card_entries.update_value(snapshot.get("total_parked", 0))
        self.card_cancelled.update_value(snapshot.get("total_cancelled", 0))

    def _reconcile_snapshot(self, snapshot: ParkingSnapshot) -> None:
        """Refresh displayed occupancy from a safe core snapshot when supplied."""
        self.projection.reconcile_snapshot(snapshot)
        self.parking_grid.render_occupied(self.projection.occupied)
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
        token = getattr(self, '_poll_token', None)
        if token is not None:
            self.root.after_cancel(token)
            self._poll_token = None
        self._set_status("ERROR UI: cerrando de forma controlada" if getattr(self, '_render_failed', False)
                         else "CERRANDO: esperando vehículos")
        if self.simulator is not None and hasattr(self.simulator, "shutdown_async"):
            self.simulator.shutdown_async()
        elif self.simulator is not None and self.simulator.is_active():
            self.simulator.stop()
        if getattr(self, '_processing_events', False):
            self.root.after(config.SHUTDOWN_POLL_INTERVAL_MS, self._check_shutdown)
        else:
            self._check_shutdown()

    def _check_shutdown(self) -> None:
        """Destroy only after the background thread and its lot have both drained."""
        if getattr(self, '_shutdown_checking', False) or self._shutdown_complete:
            return
        self._shutdown_checking = True
        try:
            self._shutdown_step()
        finally:
            self._shutdown_checking = False
            if not self._shutdown_complete:
                self.root.after(config.SHUTDOWN_POLL_INTERVAL_MS, self._check_shutdown)

    def _shutdown_step(self) -> None:
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
