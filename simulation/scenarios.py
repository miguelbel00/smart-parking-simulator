"""Declarative academic scenario registry for the parking simulator.

Each ScenarioDefinition captures a reproducible, fully-authorized input
configuration (capacity, authorizations, plate arrival sequence, timing)
that exercises real Core behavior (admit/FIFO-per-slot/Semaphore/Condition)
through the exact payload contract main.py and the engine already use. No
admission, FIFO, or authorization decision is simulated here; only inputs
are declared, and the Core makes every real decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from simulation.authorizations import load_authorizations
from simulation.config import PARKING_CAPACITY

_SCENARIO_DATA_DIR = Path(__file__).with_name("scenario_data")


@dataclass(frozen=True)
class ScenarioDefinition:
    name: str
    title: str
    academic_requirement: str
    capacity: int
    authorization_path: Path
    plate_sequence: tuple[str, ...]
    min_arrival_time: int
    max_arrival_time: int
    min_parking_time: int
    max_parking_time: int
    editable_fields: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class ScenarioSummary:
    name: str
    title: str
    academic_requirement: str
    editable_fields: tuple[str, ...]


FIFO_PER_SLOT = ScenarioDefinition(
    name="fifo_per_slot",
    title="FIFO por puesto autorizado",
    academic_requirement=(
        "Capacidad limitada, exclusion mutua por puesto, FIFO por puesto "
        "autorizado (no FIFO global: una solicitud posterior para un "
        "puesto libre entra antes que una anterior que espera un puesto "
        "ocupado), liberacion de recursos y progreso de solicitudes "
        "elegibles."
    ),
    capacity=PARKING_CAPACITY,
    authorization_path=_SCENARIO_DATA_DIR / "fifo_per_slot_authorizations.json",
    plate_sequence=("FIFO-A", "FIFO-B", "FIFO-C", "FIFO-D"),
    min_arrival_time=1,
    max_arrival_time=1,
    min_parking_time=3,
    max_parking_time=3,
    editable_fields=frozenset({
        "min_arrival_time", "max_arrival_time",
        "min_parking_time", "max_parking_time",
    }),
)

CAPACITY_SATURATION = ScenarioDefinition(
    name="capacity_saturation_and_release",
    title="Escenario 2 — Concurrencia, capacidad y FIFO",
    academic_requirement=(
        "Seis vehiculos ocupan las seis plazas. G, H e I esperan por la "
        "plaza 1 y entran en ese orden tras cada liberacion, sin superar "
        "la capacidad."
    ),
    capacity=PARKING_CAPACITY,
    authorization_path=_SCENARIO_DATA_DIR / "capacity_saturation_authorizations.json",
    plate_sequence=(
        "QDQ-021", "YQO-792", "UHD-319", "INZ-019", "FFQ-932", "PVD-377",
        "BIV-976", "ZON-782", "JJK-247",
    ),
    min_arrival_time=0,
    max_arrival_time=0,
    min_parking_time=8,
    max_parking_time=8,
    editable_fields=frozenset({
        "min_arrival_time", "max_arrival_time",
        "min_parking_time", "max_parking_time",
    }),
)

AUTHORIZATION_REJECTIONS = ScenarioDefinition(
    name="authorization_rejections",
    title="Escenario 1 — Control de acceso y autorizaciones",
    academic_requirement=(
        "A ocupa la plaza 1, B es rechazada por placa desconocida, C ocupa "
        "la plaza 2, la segunda solicitud de A se rechaza como duplicada y "
        "D espera por la plaza 1 hasta que A sale. Las decisiones usan el "
        "AuthorizationRegistry y ParkingLot.admit() reales."
    ),
    capacity=PARKING_CAPACITY,
    authorization_path=_SCENARIO_DATA_DIR / "authorization_rejections.json",
    plate_sequence=("OND-830", "BZO-132", "NGX-553", "OND-830", "CWR-850"),
    min_arrival_time=1,
    max_arrival_time=1,
    min_parking_time=5,
    max_parking_time=5,
    editable_fields=frozenset({
        "min_arrival_time", "max_arrival_time",
        "min_parking_time", "max_parking_time",
    }),
)

NORMAL_ENTRY_AND_EXIT = ScenarioDefinition(
    name="normal_entry_and_exit",
    title="Escenario 3 — Multiprocessing, IPC y ciclo de vida",
    academic_requirement=(
        "Treinta solicitudes activan el motor multiprocessing y el transporte "
        "IPC real. La actividad concurrente permite solicitar Stop desde la "
        "interfaz y comenzar otra ejecucion independiente tras el drenaje."
    ),
    capacity=PARKING_CAPACITY,
    authorization_path=_SCENARIO_DATA_DIR / "normal_entry_and_exit.json",
    plate_sequence=(
        "ASL-428", "VTF-849", "VNC-427", "BUD-856", "VGW-990", "NBB-386",
        "PIA-160", "IPZ-354", "HVG-983", "DFK-846", "QZJ-586", "ULP-109",
        "SOJ-773", "IHG-940", "MPI-027", "QPI-189", "LBN-602", "CRV-483",
        "LXZ-440", "FSG-462", "OFO-331", "PAL-133", "RLW-256", "PGO-038",
        "BBL-111", "NZW-942", "QTA-202", "MMB-124", "DFD-476", "DYH-037",
    ),
    min_arrival_time=1,
    max_arrival_time=1,
    min_parking_time=12,
    max_parking_time=12,
    editable_fields=frozenset({
        "min_arrival_time", "max_arrival_time",
        "min_parking_time", "max_parking_time",
    }),
)

STOP_CANCELLATION_DEMO = ScenarioDefinition(
    name="stop_cancellation_demo",
    title="Stop temprano/tardio/repetido y reinicio",
    academic_requirement=(
        "Stop temprano cancela solicitudes pendientes (reason "
        "STOP_REQUESTED) sin afectar a un vehiculo ya estacionado, que "
        "finaliza su ciclo con normalidad; Stop tardio (sin pendientes) no "
        "cancela nada; Stop repetido no duplica eventos terminales ni "
        "libera recursos de mas; y ejecuciones sucesivas sobre el mismo "
        "motor mantienen estado, numeracion de vehiculos y metricas "
        "independientes entre si."
    ),
    capacity=PARKING_CAPACITY,
    authorization_path=_SCENARIO_DATA_DIR / "stop_cancellation_demo.json",
    plate_sequence=("STOP-A", "STOP-B"),
    min_arrival_time=1,
    max_arrival_time=1,
    min_parking_time=3,
    max_parking_time=3,
    editable_fields=frozenset({
        "min_arrival_time", "max_arrival_time",
        "min_parking_time", "max_parking_time",
    }),
)

_REGISTRY: Mapping[str, ScenarioDefinition] = {
    FIFO_PER_SLOT.name: FIFO_PER_SLOT,
    CAPACITY_SATURATION.name: CAPACITY_SATURATION,
    AUTHORIZATION_REJECTIONS.name: AUTHORIZATION_REJECTIONS,
    NORMAL_ENTRY_AND_EXIT.name: NORMAL_ENTRY_AND_EXIT,
    STOP_CANCELLATION_DEMO.name: STOP_CANCELLATION_DEMO,
}


def list_scenarios() -> tuple[ScenarioSummary, ...]:
    """Pure, read-only catalog for a UI selector. No Core logic here."""
    return tuple(
        ScenarioSummary(scenario.name, scenario.title, scenario.academic_requirement,
                        tuple(sorted(scenario.editable_fields)))
        for scenario in _REGISTRY.values()
    )


def list_academic_scenarios() -> tuple[ScenarioSummary, ...]:
    """Return the three reproducible scenarios presented in the Tk selector."""
    names = (AUTHORIZATION_REJECTIONS.name, CAPACITY_SATURATION.name, NORMAL_ENTRY_AND_EXIT.name)
    summaries = {summary.name: summary for summary in list_scenarios()}
    return tuple(summaries[name] for name in names)


def get_scenario(name: str) -> ScenarioDefinition:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown scenario: {name}") from None


def build_payload(name: str, overrides: Mapping[str, object] | None = None) -> dict:
    """Build the exact START payload shape main.py and the engine consume.

    `overrides` may only touch fields the scenario lists in
    `editable_fields`; anything else raises, so a scenario can fix the
    conditions it needs to stay reproducible while still allowing the
    parameters it declares safe to vary.
    """
    scenario = get_scenario(name)
    overrides = dict(overrides or {})
    unknown = set(overrides) - scenario.editable_fields
    if unknown:
        raise ValueError(f"scenario {name!r} does not allow overriding: {sorted(unknown)}")
    values = {
        "min_arrival_time": scenario.min_arrival_time,
        "max_arrival_time": scenario.max_arrival_time,
        "min_parking_time": scenario.min_parking_time,
        "max_parking_time": scenario.max_parking_time,
        **overrides,
    }
    registry = load_authorizations(scenario.authorization_path, scenario.capacity)
    return {
        "config": {
            "capacity": scenario.capacity,
            "total_vehicles": len(scenario.plate_sequence),
            "min_arrival_time": values["min_arrival_time"],
            "max_arrival_time": values["max_arrival_time"],
            "min_parking_time": values["min_parking_time"],
            "max_parking_time": values["max_parking_time"],
        },
        "authorization": {"vehicles": [
            {"plate": record.plate, "authorized": record.authorized, "space_id": record.space_id}
            for record in registry.records.values()
        ]},
        "plate_sequence": list(scenario.plate_sequence),
    }
