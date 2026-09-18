# Core Agent Instructions

## Responsable

Persona A — Motor del parqueadero y concurrencia.

## Objetivo

Implementar la lógica concurrente del simulador sin depender de Tkinter.

## Archivos

vehicle.py
parking.py
events.py


## Responsabilidades

Implementar:

- Vehicle como Thread.
- ParkingLot.
- Semaphore para capacidad.
- Lock para estado compartido.
- Asignación y liberación de espacios.
- Estados de vehículos.
- Generación de eventos.


## Restricciones

No importar tkinter.

No modificar widgets.

No implementar lógica visual.

No introducir dependencia hacia ui/.


## Flujo esperado de un vehículo

CREATED
   ↓
llegada
   ↓
intenta acquire()
   ↓
WAITING si no existe recurso
   ↓
obtiene Semaphore
   ↓
PARKED
   ↓
permanece determinado tiempo
   ↓
libera espacio
   ↓
release()
   ↓
FINISHED


## Salida del módulo

Toda información relevante hacia la interfaz debe emitirse mediante
event_queue.put(...).


## Condiciones que nunca deben ocurrir

occupied_spaces > parking_capacity

Dos vehículos con el mismo espacio.

Liberación doble de Semaphore.

Modificación concurrente de estructuras compartidas sin Lock.
