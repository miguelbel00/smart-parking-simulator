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
    title="Saturacion de capacidad y liberacion concurrente",
    academic_requirement=(
        "Capacidad maxima alcanzada sin excederla (invariante del "
        "Semaphore), espera simultanea de distintas solicitudes por dos "
        "puestos ocupados distintos, y liberacion con avance concurrente "
        "e independiente por puesto cuando cada ocupante termina."
    ),
    capacity=PARKING_CAPACITY,
    authorization_path=_SCENARIO_DATA_DIR / "capacity_saturation_authorizations.json",
    plate_sequence=(
        "SAT-A", "SAT-B", "SAT-C", "SAT-F", "SAT-G", "SAT-H",
        "SAT-I", "SAT-J", "SAT-K", "SAT-L", "SAT-D", "SAT-E",
    ),
    min_arrival_time=0,
    max_arrival_time=0,
    min_parking_time=4,
    max_parking_time=4,
    editable_fields=frozenset({
        "min_arrival_time", "max_arrival_time",
        "min_parking_time", "max_parking_time",
    }),
)

AUTHORIZATION_REJECTIONS = ScenarioDefinition(
    name="authorization_rejections",
    title="Rechazos reales por autorizacion",
    academic_requirement=(
        "Rechazo de una placa desconocida (UNKNOWN_PLATE), rechazo de una "
        "placa registrada pero no autorizada (NOT_AUTHORIZED), y rechazo de "
        "una placa activa duplicada (DUPLICATE_ACTIVE) mientras su primera "
        "solicitud sigue estacionada, todo evaluado por el AuthorizationRegistry "
        "y ParkingLot.admit() reales, sin atajos."
    ),
    capacity=PARKING_CAPACITY,
    authorization_path=_SCENARIO_DATA_DIR / "authorization_rejections.json",
    plate_sequence=("REJ-OK", "REJ-DENIED", "REJ-UNKNOWN", "REJ-OK"),
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
    title="Flujo gradual de 30 vehiculos con espera y salida",
    academic_requirement=(
        "Flujo de 30 solicitudes autorizadas con capacidad fija de 10 "
        "puestos, una llegada por segundo y 12 segundos de permanencia: "
        "ocupacion completa, solicitudes pendientes visibles y finalizacion "
        "natural tras liberar puestos, sin rechazos ni cancelaciones."
    ),
    capacity=PARKING_CAPACITY,
    authorization_path=_SCENARIO_DATA_DIR / "normal_entry_and_exit.json",
    plate_sequence=tuple(f"NORM-{number:03d}" for number in range(1, 31)),
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
