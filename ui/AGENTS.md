# UI Agent Instructions

## Integración actual

Core representa vehículos como datos de solicitud y actualmente ejecuta
trabajadores orientados a tareas. Su búsqueda de puestos elegibles y FIFO
estricto dentro de cada puesto autorizado describen el runtime, no la política
académica aún pendiente para el caso en que el puesto del vehículo más antiguo
esté bloqueado. `AdmissionResult` y sus motivos de rechazo están conectados al
runtime; rechazos emiten `VEHICLE_REJECTED` y pendientes cancelados por cierre
temprano emiten `VEHICLE_CANCELLED`. La UI sigue siendo solo consumidora de los
eventos y no administra la admisión. El runtime usa un proceso de motor
`spawn`; el adaptador ejecuta un hilo de transporte en el proceso padre y
reenvía los eventos IPC a la cola local de Tk. Esto describe la implementación,
no valida por sí solo el cumplimiento académico; ver el [protocolo raíz](../AGENTS.md#18-protocolo-de-trabajo-y-decisiones-académicas-pendientes).

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


Nunca actualizar widgets desde hilos trabajadores ni procesos secundarios.
La comunicación entre procesos, cuando se diseñe, no habilita llamadas Tkinter
fuera del hilo principal.


## Comunicación

El hilo de transporte entrega eventos al hilo principal de Tk mediante una
`queue.Queue` local al proceso de la UI. Esta cola NO es IPC. El transporte
entre el proceso padre y el proceso de motor usa colas `multiprocessing` y el
protocolo validado descrito en el [contrato raíz](../AGENTS.md#4-contrato-entre-módulos).

Tk debe consultar periódicamente la cola local:

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
VEHICLE_REJECTED
VEHICLE_CANCELLED
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

La persistencia con SQLite está explícitamente excluida del alcance actual; no
agregar trabajo de base de datos en la UI salvo que el alcance del proyecto se
modifique por separado. Seguir las reglas de Git del [AGENTS.md raíz](../AGENTS.md).
