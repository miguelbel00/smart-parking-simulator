# Instrucciones del agente de Core

## Responsable

Persona A — Motor del parqueadero y concurrencia.

## Responsabilidades y API

El runtime implementa solicitudes `Vehicle` (no son hilos), `ParkingLot` y el
evento compartido según el contrato del [AGENTS.md raíz](../AGENTS.md#9-integración).
La API actual es:

- `Vehicle` almacena `vehicle_id`, `parking`, `parking_duration` y patente.
- `ParkingLot(capacity, event_queue, authorization_registry)` requiere el
  registro inmutable, y expone `start()`, `admit(vehicle) -> AdmissionResult`,
  `snapshot()` y `close()`.
- La admisión valida y encola sin esperar; `AdmissionResult` incluye el
  vehículo aceptado o un motivo estable de rechazo.
- `snapshot() -> ParkingSnapshot` ofrece una lectura inmutable/copiada, sin
  exponer estructuras internas. `close(wait: bool = True) -> None` aplica la
  política de cierre descrita en el contrato raíz.
- `core/events.py` define el dataclass inmutable `ParkingEvent` y los tipos
  de evento compartidos. Core emite eventos del ciclo de vida vehicular.

## Concurrencia

- Dos hilos orientados a tareas por lote realizan admisión y salidas/deadlines;
  no crear un hilo por vehículo ni mantener un trabajador durante su estadía.
- Un `Semaphore` y un `Lock`/`Condition` mantienen capacidad y estado seguros.
- La admisión respeta FIFO por elegibilidad y FIFO estricto por puesto.
- Un `Lock` protege el estado compartido y la asignación de espacios.
- Evitar asignaciones duplicadas y liberaciones dobles del Semaphore.
- El cierre temprano cancela solicitudes en espera; el cierre natural drena
  las aceptadas. Ambos permiten completar las solicitudes estacionadas.

## Restricciones

No importar Tkinter ni depender de `ui/`. Publicar información para la
interfaz mediante `event_queue.put(...)`; no modificar widgets.

## Reglas compartidas

Seguir los requisitos de base de datos y flujo Git del
[AGENTS.md raíz](../AGENTS.md).
La persistencia no está asignada a Core: no asumir propiedad, integración ni
sincronización de la base de datos sin acuerdo del equipo.
