# UI Agent Instructions

## Implementación actual y objetivo aprobado

El runtime actual usa un `Vehicle` por hilo; esta es una descripción factual,
no una instrucción para desarrollo nuevo. La migración está pendiente y no
está implementada. No agregar desarrollo que dependa de un hilo por vehículo
ni colocar allí la espera de admisión. El objetivo usa hilos orientados a
tareas, FIFO por elegibilidad y FIFO estricto entre solicitudes del mismo
puesto autorizado. Los contratos futuros `AdmissionCommand` y
`AdmissionResult` y sus motivos de rechazo están definidos en el
[AGENTS.md raíz](../AGENTS.md#9-integración); todavía no están conectados al
runtime. La UI sigue siendo solo consumidora de eventos y no administra la
admisión.

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
