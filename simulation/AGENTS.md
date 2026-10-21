# Simulation Agent Instructions

## Current runtime

`Simulator` receives an explicit ordered plate sequence and generates
request-data `Vehicle` instances; it does not choose plates randomly. `main.py`
validates the authorization JSON before each run and passes its immutable
registry to `ParkingLot`. Core uses two task workers, FIFO by eligibility and
strict FIFO among requests for the same authorized slot. Do not add a thread
per vehicle or place admission/dwell waits in a vehicle request.

`simulation/authorizations.py` provides the authorization JSON domain loader.
Before each run, validate the complete file and pass the immutable registry to
core through its public API. Extra JSON keys are rejected (strict schema).
Different authorized plates may share a `space_id`, but only one request may
occupy that space at a time. FIFO applies to requests targeting that space,
not to the order of records in the JSON file.
The default registry path and deterministic example plate sequence are in
`config.py` and `default_authorizations.json`.

`ParkingLot.admit` returns `AdmissionResult` with accepted/rejected, a request
reference and one stable rejection reason: `UNKNOWN_PLATE`, `NOT_AUTHORIZED`,
`DUPLICATE_ACTIVE`, `LOT_CLOSED`, or `INVALID_REQUEST`. Accepted means
queued/active, not parked.

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
