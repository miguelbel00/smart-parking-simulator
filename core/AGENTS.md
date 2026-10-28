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
- `ParkingEvent` añade `plate`, `authorized_space_id` y `reason` tras los
  cinco campos previos. REJECTED no crea solicitudes activas; CANCELLED
  terminaliza pendientes por `STOP_REQUESTED`; FINISHED solo indica salida
  normal. Snapshots contienen tuplas de vistas inmutables WAITING/PARKED.

## Concurrencia

- Dos hilos orientados a tareas por lote realizan admisión y salidas/deadlines;
  no crear un hilo por vehículo ni mantener un trabajador durante su estadía.
- Un `Semaphore` y un `Lock`/`Condition` mantienen capacidad y estado seguros.
- La política aprobada admite por elegibilidad y mantiene FIFO estricto por
  puesto autorizado. Si el más antiguo tiene su puesto ocupado, otro vehículo
  puede ingresar a su propio puesto libre; nunca se reasignan puestos. El orden
  es el de aceptación bajo el Lock, no el inicio de llamadas concurrentes.
  Evita bloqueo global innecesario; no es FIFO global estricto. Ver el
  [protocolo raíz](../AGENTS.md#18-protocolo-de-trabajo-y-decisiones-académicas-pendientes).
- Un `Lock` protege el estado compartido y la asignación de espacios.
- Evitar asignaciones duplicadas y liberaciones dobles del Semaphore.
- El cierre temprano cancela solicitudes en espera; el cierre natural drena
  las aceptadas. Ambos permiten completar las solicitudes estacionadas.
- El primer cierre selecciona el modo; un Stop posterior puede escalar drenaje
  a cancelación. Bajo la misma Condition, ninguna llamada posterior puede
  desactivar una cancelación ya solicitada, incluso si calculó antes el modo
  natural. No se reabren admisiones ni se cancelan vehículos estacionados.

## Restricciones

No importar Tkinter ni depender de `ui/`. Publicar información para la
interfaz mediante `event_queue.put(...)`; no modificar widgets.

## Reglas compartidas

La persistencia con SQLite está explícitamente excluida del alcance actual; no
agregar trabajo de base de datos a Core salvo que el alcance del proyecto se
modifique por separado. Seguir las reglas de Git del [AGENTS.md raíz](../AGENTS.md).

El runtime actual cuenta con un proceso de motor `spawn` que es dueño del estado
de `ParkingLot`; Core se ejecuta dentro de ese proceso. El controlador de
simulación gestiona IPC, no la `Queue` de eventos de Core. Esta implementación
no demuestra por sí sola el cumplimiento académico. No trasladar la propiedad
del estado ni cambiar unilateralmente la API pública de Core o el contrato de
`ParkingEvent`. La política FIFO entre elegibles, con FIFO estricto por puesto,
es una decisión definitiva del responsable del proyecto; ver el
[protocolo raíz](../AGENTS.md#18-protocolo-de-trabajo-y-decisiones-académicas-pendientes).
