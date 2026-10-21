# Simulation Agent Instructions

## Current runtime and approved target

The runtime currently generates `Vehicle` instances through the existing
`Simulator` and core API; it does not load authorization JSON. Migration to the
approved task-oriented admission model is pending and not implemented. Do not
add new development based on one thread per vehicle or place admission waits
inside a vehicle thread. The target is FIFO by eligibility, with strict FIFO
among requests for the same authorized slot.

`simulation/authorizations.py` provides the authorization JSON domain loader.
Before a future run, validate the complete file and pass the immutable registry
to core through its public API. Extra JSON keys are rejected (strict schema).
Different authorized plates may share a `space_id`, but only one request may
occupy that space at a time. FIFO applies to requests targeting that space,
not to the order of records in the JSON file.
The loader is not yet integrated into the runtime.

Future contracts only: `AdmissionCommand` contains a run-scoped unique
`vehicle_id`, canonical plate, and duration. Core resolves
`authorized_space_id` from the immutable registry. `AdmissionResult` carries
accepted/rejected, a request reference, and one stable rejection reason:
`UNKNOWN_PLATE`, `NOT_AUTHORIZED`, `DUPLICATE_ACTIVE`, `LOT_CLOSED`, or
`INVALID_REQUEST`. Accepted means queued/active, not parked. These contracts
are not implemented or wired into the current runtime.

## Responsable

Persona C — Simulación, configuración y métricas.

## Objetivo

Controlar el escenario de prueba del parqueadero.


## Responsabilidades

Implementar:

- Creación de vehículos.
- Intervalos entre llegadas.
- Tiempo de permanencia.
- Inicio de simulación.
- Detención de simulación.
- Parámetros configurables.
- Métricas y estadísticas.


## Configuración

Todos los parámetros generales deben estar en:

config.py


Ejemplos:

PARKING_CAPACITY
TOTAL_VEHICLES
MIN_ARRIVAL_TIME
MAX_ARRIVAL_TIME
MIN_PARKING_TIME
MAX_PARKING_TIME


## Métricas

Como mínimo considerar:

- Vehículos creados.
- Vehículos procesados.
- Tiempo promedio de espera.
- Máximo número de vehículos esperando.
- Máxima ocupación alcanzada.


## Restricciones

No modificar directamente la interfaz.

No modificar directamente la estructura interna de espacios del parqueadero.

Utilizar las funciones públicas proporcionadas por core/.

## Contrato con core y UI

La simulación utiliza únicamente la API pública de `core`, definida en el
[contrato raíz](../AGENTS.md#9-integración). `main.py` compone Simulator,
ParkingLot y la cola compartida; Simulator no administra espacios internos.
Simulator publica `SIMULATION_STARTED` y `SIMULATION_FINISHED` en la cola.
Los eventos del ciclo de vida de vehículos pertenecen a core.

La configuración, incluida la capacidad del parqueadero, se centraliza en
`config.py`. No importar ni modificar widgets de Tkinter.

## Reglas compartidas

Seguir los requisitos de base de datos y flujo Git del
[AGENTS.md raíz](../AGENTS.md).
La persistencia no está asignada a Simulation; no decidir su propiedad,
integración ni sincronización sin acuerdo del equipo.
