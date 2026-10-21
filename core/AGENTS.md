# Instrucciones del agente de Core

## Responsable

Persona A — Motor del parqueadero y concurrencia.

## Responsabilidades y API

El runtime actual implementa `Vehicle(Thread)`, `ParkingLot` y el evento
compartido según el contrato del [AGENTS.md raíz](../AGENTS.md#9-integración).
Esta descripción es factual y no autoriza desarrollo nuevo con un hilo por
vehículo; la migración al modelo objetivo sigue pendiente. En particular, la
API actual es:

- `Vehicle` recibe `vehicle_id`, `parking` y `parking_duration`; gestiona su
  ciclo de vida coordinándose con `ParkingLot`.
- `ParkingLot(capacity: int, event_queue: Queue)` registra, admite e inicia
  vehículos mediante `admit(vehicle: Vehicle) -> bool`; la admisión no espera
  por un espacio disponible.
- `snapshot() -> ParkingSnapshot` ofrece una lectura inmutable/copiada, sin
  exponer estructuras internas. `close(wait: bool = True) -> None` aplica la
  política de cierre descrita en el contrato raíz.
- `core/events.py` define el dataclass inmutable `ParkingEvent` y los tipos
  de evento compartidos. Core emite eventos del ciclo de vida vehicular.

## Concurrencia

- Un `Semaphore` y un `Lock` mantienen capacidad y estado seguros. Actualmente
  los vehículos esperan en su hilo; no extender este patrón. El objetivo es
  admisión FIFO por elegibilidad y FIFO estricto por puesto autorizado usando
  hilos orientados a tareas, sin espera dentro de un hilo por vehículo.
- Un `Lock` protege el estado compartido y la asignación de espacios.
- Evitar asignaciones duplicadas y liberaciones dobles del Semaphore.
- El cierre no termina hilos a la fuerza: cancela los que esperan y permite
  completar a los ya estacionados, con sincronización interna.

## Restricciones

No importar Tkinter ni depender de `ui/`. Publicar información para la
interfaz mediante `event_queue.put(...)`; no modificar widgets.

## Reglas compartidas

Seguir los requisitos de base de datos y flujo Git del
[AGENTS.md raíz](../AGENTS.md).
La persistencia no está asignada a Core: no asumir propiedad, integración ni
sincronización de la base de datos sin acuerdo del equipo.
