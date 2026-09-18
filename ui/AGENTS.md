# UI Agent Instructions

## Responsable

Persona B — Interfaz gráfica.

## Objetivo

Visualizar el estado del simulador sin controlar directamente
la concurrencia.


## Responsabilidades

Implementar:

- Ventana principal.
- Representación de espacios.
- Estado visual de cada espacio.
- Vehículos.
- Contadores.
- Panel de eventos.
- Controles de simulación.
- Actualización mediante after().


## Regla crítica

Tkinter solamente puede ser actualizado desde el hilo principal.


Nunca actualizar widgets desde Vehicle Threads.


## Comunicación

La interfaz recibe eventos mediante:

queue.Queue


Debe consultar periódicamente la cola:

root.after(intervalo, process_events)


## Eventos

La UI debe reaccionar a:

VEHICLE_CREATED
VEHICLE_WAITING
VEHICLE_ENTERED
VEHICLE_EXITED
VEHICLE_FINISHED
SIMULATION_STARTED
SIMULATION_FINISHED


## Restricciones

No implementar Semaphore.

No implementar Lock para administrar espacios.

No decidir qué vehículo obtiene un puesto.

No acceder directamente a estructuras internas de ParkingLot
para alterar su estado.


La UI representa el estado.

El core determina el estado.
