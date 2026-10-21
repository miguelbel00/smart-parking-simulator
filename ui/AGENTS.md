# UI Agent Instructions

## Integración actual

Core representa vehículos como datos de solicitud y ejecuta trabajadores
orientados a tareas con FIFO por elegibilidad y FIFO estricto entre solicitudes
del mismo puesto autorizado. `AdmissionResult` y sus motivos de rechazo están
conectados al runtime, pero no generan eventos nuevos. La UI sigue siendo solo
consumidora de los eventos compartidos y no administra la admisión.

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


Nunca actualizar widgets desde hilos trabajadores, incluidos los hilos de tareas.


## Comunicación

La interfaz recibe eventos mediante:

queue.Queue


Debe consultar periódicamente la cola:

root.after(intervalo, process_events)

La UI consume los `ParkingEvent` de la cola compartida, respetando los tipos
del [contrato raíz](../AGENTS.md#4-contrato-entre-módulos). Puede consultar
`ParkingLot.snapshot()` únicamente como lectura segura e inmutable; no debe
alterar el estado del core ni controlar directamente sus hilos.


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

## Reglas compartidas

Seguir los requisitos de base de datos y flujo Git del
[AGENTS.md raíz](../AGENTS.md).
La UI no realiza operaciones de base de datos; la propiedad e integración de
la persistencia deben acordarse antes de asignarlas a un módulo.
