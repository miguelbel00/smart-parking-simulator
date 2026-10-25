# Simulation Agent Instructions

## Current runtime

`Simulator` receives an explicit ordered plate sequence and generates
request-data `Vehicle` instances; it does not choose plates randomly. `main.py`
validates the authorization JSON before each run and passes its immutable
registry to `ParkingLot`. Core currently uses two task workers and scans by
eligibility, with strict FIFO among requests for the same authorized slot. The
approved arrival/longest-wait rule applies among eligible requests: an occupied
oldest slot does not block requests for other free authorized slots. The project
owner adopted this policy definitively; it is not strict global FIFO. Arrival
order means acceptance order under the core lock (see the
[root protocol](../AGENTS.md#18-protocolo-de-trabajo-y-decisiones-académicas-pendientes)). Do not add a thread
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

`record_generated` y `record_admitted` se registran desde Simulator. Los
rechazos se cuentan una sola vez al recibir `VEHICLE_REJECTED`. `total_finished`
cuenta solo `VEHICLE_FINISHED`; `total_cancelled` solo `VEHICLE_CANCELLED`.
Cada ejecución obtiene una instancia nueva de métricas.

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
[contrato raíz](../AGENTS.md#9-integración). `main.py` compone el controlador
de multiprocessing, el adaptador y la UI. El proceso de motor crea Simulator,
ParkingLot y los recursos de cada ejecución; Simulator no administra espacios
internos. Sus eventos y los de Core se serializan por el adaptador de
publicación y cruzan IPC en mensajes del protocolo validado. El proceso padre
proyecta los eventos recibidos a la `queue.Queue` local de Tk: esa cola no es
IPC. Los eventos de ciclo de vida vehicular pertenecen a Core; Simulator
publica inicio y fin de simulación.

La configuración, incluida la capacidad del parqueadero, se centraliza en
`config.py`. No importar ni modificar widgets de Tkinter.

## Reglas compartidas

La persistencia con SQLite está explícitamente excluida del alcance actual; no
agregar trabajo de base de datos salvo que el alcance del proyecto se modifique
por separado. Seguir las reglas de Git del [AGENTS.md raíz](../AGENTS.md).

## Auditoría

`main.py` es dueño de la sesión de auditoría del proceso padre. En el proceso de
motor, `MetricsForwardingQueue` actualiza las métricas por ejecución y publica
mediante el publicador IPC; el padre valida y registra los mensajes de eventos
antes de que el adaptador de GUI los reenvíe a Tk. El proceso hijo reenvía
ciertos registros de operación y error por IPC; esto no establece una cobertura
completa de cada comprobación interna. CREATED/REJECTED registran el resultado
de admisión sin duplicar decisiones; ENTERED conserva `waiting_time` en segundos.
WAITING no garantiza el comienzo exacto de toda espera. El formato persistido
anexa `waiting_time`, `result` y `error_summary`; el resumen de error del hijo
no es un traceback completo. No agregar `run_id` al evento compartido ni cambiar
IPC v1. Confirmación/drenaje de auditoría no son certificación académica.
