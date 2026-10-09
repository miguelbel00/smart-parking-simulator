"""Main GUI application for the Smart Parking Simulator.

This module implements `ParkingApp`, which:
- Assembles the UI layout using widgets from `ui.widgets`.
- Polls events periodically from the thread-safe `queue.Queue` using `root.after()`.
- Dispatches event updates to UI widgets strictly on the main thread.
- Provides start and stop controls to interface with the Simulator.

Operating System Concepts:
- Producer-Consumer Pattern: Vehicle threads (producers) post events to `queue.Queue`.
  Tkinter on the Main Thread (consumer) polls and processes those events.
- Tkinter Thread Safety: UI toolkits must never be mutated directly by worker threads;
  instead, synchronization is achieved via message passing through the queue.
"""

from __future__ import annotations

import queue
import time
from datetime import datetime
import customtkinter as ctk
from typing import Any

from ui.widgets import (
    COLOR_AVAILABLE,
    COLOR_BG_PRIMARY,
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
        on_waiting_time: Any | None = None,
    ) -> None:
        self.event_queue = event_queue
        self.simulator = simulator
        self.capacity = capacity
        self.poll_interval_ms = poll_interval_ms
        self.on_waiting_time = on_waiting_time

        # UI metrics counters
        self.occupied_count = 0
        self.waiting_count = 0
        self.total_finished = 0
        self._waiting_vehicle_ids: set[int] = set()
        self._occupied_spaces: dict[int, int] = {}

        # Initialize Main Window
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.root = ctk.CTk()
        self.root.title("Smart Parking Simulator — Monitor de Concurrencia")
        self.root.geometry("1100x740")
        self.root.minsize(900, 600)
        self.root.configure(fg_color=COLOR_BG_PRIMARY)

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

        # 2. KPI Stat Cards Row (Displays Semaphore state and Counters)
        stats_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        stats_frame.pack(fill="x", padx=16, pady=(0, 12))

        self.card_occupied = StatCard(
            stats_frame,
            title="Espacios Ocupados",
            initial_value="0",
            subtitle="Vehículos estacionados",
            value_color=COLOR_OCCUPIED,
        )
        self.card_occupied.pack(side="left", fill="both", expand=True, padx=(0, 8))

        self.card_available = StatCard(
            stats_frame,
            title="Espacios Disponibles",
            initial_value=str(self.capacity),
            subtitle="Puestos libres",
            value_color=COLOR_AVAILABLE,
        )
        self.card_available.pack(side="left", fill="both", expand=True, padx=(0, 8))

        self.card_waiting = StatCard(
            stats_frame,
            title="Cola de Espera",
            initial_value="0",
            subtitle="Hilos bloqueados por capacidad",
            value_color=COLOR_WAITING,
        )
        self.card_waiting.pack(side="left", fill="both", expand=True)

        # 3. Main Center Area (Split Left / Right)
        center_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        center_frame.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        # Left Column: Parking Bay Grid + Waiting Queue Lane
        left_col = ctk.CTkFrame(center_frame, fg_color="transparent")
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 10))

        ctk.CTkLabel(left_col, text="Mapa del parqueadero", text_color=COLOR_TEXT_PRIMARY,
                     font=("Roboto", 18, "bold"), anchor="w").pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(left_col, text=f"{self.capacity} espacios · vista en tiempo real",
                     text_color="#94a3b8", font=("Roboto", 12), anchor="w").pack(fill="x", pady=(0, 8))

        # Visual Grid of Parking Slots
        self.parking_grid = ParkingLotGridWidget(left_col, columns=5)
        self.parking_grid.pack(fill="both", expand=True, pady=(0, 10))
        self.parking_grid.setup_slots(self.capacity)

        legend = ctk.CTkFrame(left_col, fg_color="transparent")
        legend.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(legend, text="Disponible", text_color=COLOR_AVAILABLE,
                     font=("Roboto", 12, "bold")).pack(side="left", padx=(4, 16))
        ctk.CTkLabel(legend, text="Ocupado", text_color=COLOR_OCCUPIED,
                     font=("Roboto", 12, "bold")).pack(side="left", padx=(0, 16))
        ctk.CTkLabel(legend, text="En espera", text_color=COLOR_WAITING,
                     font=("Roboto", 12, "bold")).pack(side="left")

        # Visual Waiting Queue Lane
        self.waiting_lane = WaitingQueueWidget(left_col)
        self.waiting_lane.pack(fill="x")

        # Right Column: Live Event Log Terminal
        right_col = ctk.CTkFrame(center_frame, fg_color="transparent", width=320)
        right_col.pack(side="right", fill="both", expand=False, padx=(10, 0))
        right_col.pack_propagate(False)

        self.event_log = EventLogWidget(right_col)
        self.event_log.pack(fill="both", expand=True)

        # 4. Status Bar (Footer)
        self._build_footer()

    def _build_footer(self) -> None:
        """Construct the bottom status bar displaying OS concepts."""
        footer_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        footer_frame.pack(fill="x", side="bottom")

        lbl_os_info = ctk.CTkLabel(
            footer_frame,
            text="Conceptos SO: semáforo (capacidad), lock (asignación), cola de eventos (hilos a interfaz)",
            text_color="#64748b",
            font=("Roboto", 12),
        )
        lbl_os_info.pack(side="left")

        self._lbl_poll_info = ctk.CTkLabel(
            footer_frame,
            text=f"Refresco: after({self.poll_interval_ms}ms) | Hilo Tkinter: Main",
            text_color="#64748b",
            font=("Roboto", 12),
        )
        self._lbl_poll_info.pack(side="right")

    def _schedule_poll(self) -> None:
        """Schedule periodic queue polling on the main thread via root.after().

        This guarantees that all Tkinter widget updates are executed safely
        on the Main Thread, adhering to Tkinter's single-threaded GUI model.
        """
        self._process_events()
        self.root.after(self.poll_interval_ms, self._schedule_poll)

    def _process_events(self) -> None:
        """Drain all available events from the thread-safe queue.Queue.

        Acts as the consumer in the Producer-Consumer pattern.
        """
        while True:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break
            except Exception:
                break

            self._dispatch_event(event)

    def _dispatch_event(self, event: Any) -> None:
        """Dispatch a single ParkingEvent to update relevant visual components.

        Attributes follow the team contract defined in AGENTS.md (Section 4):
        - event.type: Event type string (e.g. VEHICLE_ENTERED, VEHICLE_WAITING)
        - event.timestamp: Epoch timestamp
        - event.vehicle_id: Optional integer ID of the vehicle thread
        - event.space_id: Optional integer ID of the assigned parking slot
        - event.waiting_time: Optional float duration spent in WAITING state
        """
        event_type = getattr(event, "type", str(event))
        timestamp = getattr(event, "timestamp", time.time())
        vehicle_id = getattr(event, "vehicle_id", None)
        space_id = getattr(event, "space_id", None)
        waiting_time = getattr(event, "waiting_time", None)

        time_str = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")

        # 1. Simulation Lifecycle: Started
        if event_type == "SIMULATION_STARTED":
            self.control_bar.set_running()
            self.event_log.log(
                event_type,
                "Simulación iniciada. Productor de vehículos activo.",
                time_str,
            )

        # 2. Simulation Lifecycle: Finished
        elif event_type == "SIMULATION_FINISHED":
            self.control_bar.set_stopped()
            self.event_log.log(
                event_type,
                f"Simulación terminada. Total vehículos atendidos: {self.total_finished}.",
                time_str,
            )

        # 3. OS Concept: Vehicle thread created (state: CREATED)
        elif event_type == "VEHICLE_CREATED":
            msg = f"Hilo de Auto #{vehicle_id} creado."
            self.event_log.log(event_type, msg, time_str)

        # 4. OS Concept: Vehicle thread blocked waiting for Semaphore (state: WAITING)
        elif event_type == "VEHICLE_WAITING":
            if vehicle_id is not None:
                if vehicle_id not in self._waiting_vehicle_ids:
                    self._waiting_vehicle_ids.add(vehicle_id)
                    self.waiting_lane.add_vehicle(vehicle_id)
                    self.waiting_count = len(self._waiting_vehicle_ids)
                    self.card_waiting.update_value(self.waiting_count)

            wait_info = f" (espera inicial: {waiting_time:.2f}s)" if waiting_time is not None else ""
            msg = f"Auto #{vehicle_id} en espera de semáforo libre{wait_info}."
            self.event_log.log(event_type, msg, time_str)

        # 5. OS Concept: Thread acquired Semaphore and was assigned a slot (state: PARKED)
        elif event_type == "VEHICLE_ENTERED":
            if waiting_time is not None and self.on_waiting_time is not None:
                self.on_waiting_time(waiting_time)

            if vehicle_id is not None:
                if vehicle_id in self._waiting_vehicle_ids:
                    self._waiting_vehicle_ids.remove(vehicle_id)
                    self.waiting_lane.remove_vehicle(vehicle_id)
                    self.waiting_count = len(self._waiting_vehicle_ids)
                    self.card_waiting.update_value(self.waiting_count)

            if space_id is not None and vehicle_id is not None:
                display_space_id = space_id + 1
                if self._occupied_spaces.get(space_id) != vehicle_id:
                    self._occupied_spaces[space_id] = vehicle_id
                    self.parking_grid.occupy_slot(display_space_id, vehicle_id)
                    self._update_occupancy_cards()

            display_space_id = space_id + 1 if space_id is not None else None
            msg = f"Auto #{vehicle_id} obtuvo Semaphore e ingresó al Espacio #{display_space_id}."
            self.event_log.log(event_type, msg, time_str)

        # 6. OS Concept: Thread released slot resource and signaled Semaphore
        elif event_type == "VEHICLE_EXITED":
            display_space_id = space_id + 1 if space_id is not None else None
            if (
                space_id in self._occupied_spaces
                and (vehicle_id is None or self._occupied_spaces[space_id] == vehicle_id)
            ):
                del self._occupied_spaces[space_id]
                self.parking_grid.free_slot(display_space_id)
                self._update_occupancy_cards()

            msg = f"Auto #{vehicle_id} liberó Espacio #{display_space_id} y señalizó Semaphore."
            self.event_log.log(event_type, msg, time_str)

        # 7. OS Concept: Thread terminated execution (state: FINISHED)
        elif event_type == "VEHICLE_FINISHED":
            self.total_finished += 1
            msg = f"Hilo de Auto #{vehicle_id} finalizó su ciclo de vida."
            self.event_log.log(event_type, msg, time_str)

        # Fallback for generic or custom events
        else:
            msg = f"Vehículo #{vehicle_id}, Espacio #{space_id}."
            self.event_log.log(event_type, msg, time_str)

    def _update_occupancy_cards(self) -> None:
        """Update both capacity cards from the same occupied-space projection."""
        self.occupied_count = len(self._occupied_spaces)
        available = max(0, self.capacity - self.occupied_count)
        self.card_occupied.update_value(self.occupied_count)
        self.card_available.update_value(available)

    def _start_simulation(self) -> None:
        """Trigger simulator start if provided."""
        if self.simulator is not None:
            if hasattr(self.simulator, "start"):
                self.simulator.start()
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
        """Clean shutdown when closing the Tkinter window."""
        self._stop_simulation()
        self.root.destroy()

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

        # Vehicles arrive: slots 1 to 5 enter immediately; slot 6 and 7 wait
        for i in range(1, 8):
            demo_queue.put(
                MockParkingEvent(type="VEHICLE_CREATED", timestamp=time.time(), vehicle_id=i)
            )
            time.sleep(0.3)

            if i <= 5:
                # Capacity available: vehicle enters slot i
                demo_queue.put(
                    MockParkingEvent(
                        type="VEHICLE_ENTERED",
                        timestamp=time.time(),
                        vehicle_id=i,
                        space_id=i,
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
                space_id=1,
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

        # Vehicle 6 waiting gets the released slot 1
        demo_queue.put(
            MockParkingEvent(
                type="VEHICLE_ENTERED",
                timestamp=time.time(),
                vehicle_id=6,
                space_id=1,
                waiting_time=3.2,
            )
        )

    threading.Thread(target=_demo_producer, daemon=True).start()
    app.run()
