# AGENTS.md

## 1. Objetivo del proyecto

Desarrollar un simulador de parqueadero inteligente utilizando Python y Tkinter.

El requisito académico incluye procesos reales y comunicación entre procesos
(IPC), además de conceptos fundamentales de Sistemas Operativos:

- Procesos e hilos.
- Concurrencia.
- Sincronización.
- Exclusión mutua.
- Locks.
- Semáforos.
- Bloqueo de procesos.
- Gestión de recursos compartidos.

Cada vehículo se representa mediante un objeto `Vehicle` que contiene los
datos de la solicitud; no hereda de `Thread`. Cada ejecución crea un
trabajador de admisión y otro de vencimientos/salidas en `ParkingLot`, además
del productor de `Simulator`.

El runtime implementa multiprocessing e IPC: un proceso de motor creado con
`spawn` ejecuta la simulación y posee el estado de `ParkingLot`; colas
multiprocessing transportan comandos, respuestas, eventos y ciertos registros
de auditoría entre ese proceso y el proceso de la UI. Esto describe la
implementación, pero no demuestra por sí solo el cumplimiento académico: la
validación de los requisitos sigue pendiente. La política aprobada es FIFO
entre solicitudes elegibles, con FIFO estricto por puesto autorizado; un puesto
bloqueado no impide atender solicitudes elegibles de otros puestos.
El profesor sugirió estudiar sesiones de usuario/usuarios concurrentes, pero
no exigió ese diseño.

Los espacios del parqueadero representan recursos limitados compartidos
entre los vehículos.

---

## 2. Arquitectura obligatoria

El proyecto está dividido en tres módulos principales:

core/
    Lógica del parqueadero y concurrencia.

ui/
    Interfaz gráfica desarrollada con Tkinter.

simulation/
    Generación de vehículos, configuración y métricas.

Los módulos deben mantenerse desacoplados.

La dirección de dependencias y eventos es:

`main.py` compone la UI, la sesión de auditoría y `MultiprocessController`.
El controlador inicia el proceso de motor; allí se crean `ParkingLot` y
`Simulator`, que usan la API de core. `MultiprocessGUIAdapter` mantiene un
hilo de transporte en el proceso de la UI, traslada eventos IPC a la
`queue.Queue` local de Tk y la UI consume esa cola. Esa `queue.Queue` comunica
hilos dentro del proceso de la UI; NO es el mecanismo IPC.

La interfaz gráfica NO debe controlar directamente los hilos.

Los hilos NO deben modificar directamente elementos de Tkinter.

---

## 3. Responsabilidades del equipo

### Persona A — Core y concurrencia

Responsable de:

- Clase Vehicle.
- Clase ParkingLot.
- Creación y manejo de Threads.
- Semaphore.
- Lock.
- Control de espacios.
- Entrada y salida de vehículos.
- Estados internos de los vehículos.
- Emisión de eventos hacia la cola.

Archivos principales:

core/vehicle.py
core/parking.py
core/events.py

### Persona B — Interfaz gráfica

Responsable de:

- Ventana principal de Tkinter.
- Representación gráfica de los espacios.
- Representación de vehículos.
- Contadores.
- Panel de eventos.
- Botones de control.
- Actualización visual mediante after().
- Lectura de eventos desde queue.Queue.

Archivos principales:

ui/interface.py
ui/widgets.py

### Persona C — Simulación y métricas

Responsable de:

- Generación automática de vehículos.
- Intervalos de llegada.
- Tiempo de permanencia.
- Configuración de simulación.
- Inicio y detención de la simulación.
- Recopilación de métricas.
- Estadísticas finales.

Archivos principales:

simulation/simulator.py
simulation/config.py
simulation/metrics.py

---

## 4. Contrato entre módulos

Este contrato NO debe modificarse unilateralmente.

La comunicación entre el adaptador de transporte y Tkinter dentro del proceso
de la UI debe realizarse mediante:

`queue.Queue` (local al proceso; no IPC).

La comunicación entre procesos usa las colas `multiprocessing.Queue` del
controlador y mensajes validados del protocolo en `simulation/ipc_protocol.py`.

Los eventos usan el dataclass inmutable compartido `ParkingEvent`, definido
en `core/events.py`:

```python
ParkingEvent(
    type: str,
    timestamp: float,
    vehicle_id: int | None = None,
    space_id: int | None = None,
    waiting_time: float | None = None,
    plate: str | None = None,
    authorized_space_id: int | None = None,
    reason: str | None = None,
)
```

Tipos iniciales permitidos:

VEHICLE_CREATED
VEHICLE_WAITING
VEHICLE_ENTERED
VEHICLE_EXITED
VEHICLE_FINISHED
VEHICLE_REJECTED
VEHICLE_CANCELLED
SIMULATION_STARTED
SIMULATION_FINISHED

Core es responsable de los eventos del ciclo de vida de vehículos.
`Simulator` es responsable de `SIMULATION_STARTED` y
`SIMULATION_FINISHED`. Los campos opcionales se informan cuando corresponda.
Los tres campos nuevos se agregan después de los cinco originales, preservando
compatibilidad posicional. CREATED solo corresponde a solicitudes aceptadas;
REJECTED lleva el motivo estable y no produce estado activo. CANCELLED termina
una solicitud aceptada aún en espera por `STOP_REQUESTED`, no es FINISHED.
FINISHED solo representa finalización normal tras estacionamiento. `space_id`
significa puesto ocupado/liberado físicamente; `authorized_space_id` puede
estar disponible antes de ocuparlo. Core publica sus terminales antes de que
Simulator envíe SIMULATION_FINISHED. Métricas cuentan REJECTED, FINISHED y
CANCELLED desde sus respectivos eventos.

No cambiar nombres de campos o tipos de eventos sin coordinarlo con
los otros módulos.

---

## 5. Reglas fundamentales de concurrencia

### Threads

El proceso de motor ejecuta `ParkingLot`, que usa dos hilos orientados a tareas
por ejecución: admisión y vencimientos/salidas. `Simulator` conserva un hilo
productor; el padre usa un hilo de transporte para atender IPC sin bloquear
Tkinter. No agregar hilos por vehículo ni ubicar esperas de admisión o
permanencia dentro de una solicitud. La separación funcional actual no implica
que cada vehículo tenga su propio hilo o proceso.

La política aprobada por el responsable del proyecto es FIFO entre solicitudes
elegibles, con FIFO estricto por puesto autorizado. Si el puesto del más antiguo
está ocupado, puede ingresar una solicitud posterior para otro puesto libre,
sin reasignar puestos. Al liberarse el puesto bloqueado, tiene prioridad la
solicitud más antigua que espera ese mismo recurso y continúa elegible.
Esto evita bloqueo global innecesario y preserva el orden entre competidores
por el mismo recurso; no es FIFO global estricto ni requiere otra autorización
de la profesora. El orden de llegada es el de aceptación bajo el Lock, no el
inicio de llamadas concurrentes a `admit`. No se garantiza un tiempo máximo de
espera si el recurso no se libera; el cierre temprano cancela pendientes.

### Semaphore

La capacidad del parqueadero debe controlarse utilizando:

threading.Semaphore

Ejemplo conceptual:

Semaphore(capacidad_del_parqueadero)

El permiso del `Semaphore` se adquiere únicamente al confirmar ocupación y se
libera al salir. Las solicitudes en espera no retienen permisos; `Lock` y
`Condition` protegen transiciones y coordinan trabajadores sin sondeo activo.

### Lock

Los datos compartidos que puedan ser modificados concurrentemente deben
protegerse utilizando:

threading.Lock

Ejemplos:

- Lista de espacios ocupados.
- Asignación de puestos.
- Registros de vehículos/placas activas y transiciones de estado.
- Contadores y estadísticas compartidas.
- Estadísticas concurrentes.

### Queue

La comunicación entre los hilos y Tkinter debe realizarse mediante:

queue.Queue

Los trabajadores colocan eventos en la cola.

La interfaz consume esos eventos.

---

## 6. Regla crítica de Tkinter

Tkinter debe ejecutarse únicamente en el hilo principal.

Nunca hacer esto desde un hilo trabajador (incluidos los hilos de tareas):

label.config(...)
canvas.create_rectangle(...)
widget.destroy(...)
variable.set(...)

Los hilos deben enviar un evento a queue.Queue.

La interfaz debe consultar periódicamente la cola mediante:

root.after(...)

Flujo actual:

Task worker
      ↓
queue.put(event)
      ↓
Queue
      ↓
Tkinter after()
      ↓
Actualizar interfaz

---

## 7. Estados conceptuales del vehículo

Los vehículos deben poder representar como mínimo los siguientes estados:

CREATED
WAITING
PARKED
FINISHED

Son estados del ciclo de vida del vehículo, no estados de un hilo específico.
En el runtime actual son estados del dato `Vehicle`; los hilos de tareas del
parqueadero ejecutan transiciones sin representar un vehículo individual.

CREATED
    La solicitud del vehículo fue creada.

WAITING
    La solicitud espera un recurso.

PARKED
    El vehículo obtuvo el puesto.

FINISHED
    El ciclo de vida del vehículo terminó.

Estos estados pueden ampliarse si el equipo lo considera necesario,
pero no deben eliminarse sin acuerdo.

---

## 8. Separación de responsabilidades

### core/

Puede importar:

- threading
- queue
- time
- dataclasses
- enum
- módulos estándar necesarios

NO debe importar:

- tkinter
- ui

### ui/

Puede importar:

- tkinter
- queue
- modelos/eventos compartidos

NO debe implementar:

- Semaphore
- lógica de asignación de espacios
- reglas de concurrencia

### simulation/

Puede utilizar:

- random
- time
- configuración
- API pública de core

NO debe:

- modificar widgets de Tkinter
- administrar directamente espacios internos del parqueadero

---

## 9. Integración

main.py será el punto de composición de los módulos.

Debe contener poca lógica.

`main.py` lee configuración y autorizaciones, crea una sola cola local para la
UI, inicia `MultiprocessController` y conecta `MultiprocessGUIAdapter` con
`ParkingApp`. La fábrica de recursos por ejecución se ejecuta en el proceso de
motor, no en `main.py`:

ui_queue = Queue()  # Queue local del proceso de la UI, no IPC
controller = MultiprocessController(PARKING_CAPACITY, audit=audit)
adapter = MultiprocessGUIAdapter(controller, ui_queue, payload_factory)
adapter.start_engine()  # inicia el hilo de transporte; este inicia el controlador y el motor de forma asíncrona
app = ParkingApp(event_queue=ui_queue, simulator=adapter,
                 capacity=PARKING_CAPACITY)
app.run()

`main.py` valida el registro JSON y lo incluye, junto con la configuración y
secuencia ordenada de patentes, en el payload START. El controlador valida el
payload y envía comandos por IPC. El proceso de motor construye un registro
inmutable, una instancia de métricas y, mediante `run_factory`, un `ParkingLot`
y su cola reenviadora para cada ejecución. Core/Simulator publican eventos al
adaptador de publicación del proceso de motor; el proceso padre los valida,
audita y el adaptador los proyecta a la cola local de la UI. La UI solicita
inicio/detención mediante el adaptador y no administra procesos, hilos de core
ni espacios. El informe final corresponde a las métricas de la última
ejecución. El contrato `ParkingEvent` no incluye `run_id`; este viaja en el
envoltorio IPC. La persistencia en base de datos está fuera del alcance actual
del proyecto, de acuerdo con §16.

La lógica específica debe permanecer en su módulo correspondiente.

### API pública mínima de core (runtime actual)

- `Vehicle` contiene `vehicle_id`, patente, duración y estado; no es un hilo.
- `ParkingLot(capacity, event_queue, authorization_registry)` expone
  `start()`, `admit(vehicle) -> AdmissionResult`, `snapshot()` y `close()`.
- `admit` valida, resuelve autorización, rechaza duplicados activos y encola
  de forma síncrona; aceptado significa activo/en cola, no estacionado.
- `AdmissionResult` conserva el identificador y la referencia de solicitud
  aceptada, o uno de los motivos estables de rechazo.
- `ParkingSnapshot` es una lectura inmutable/copiada con `capacity`,
  `occupied_count`, `waiting_count` y `occupied_spaces`, una tupla de pares
  `(space_id, vehicle_id)`. No expone estructuras mutables internas.
- El cierre temprano cancela solicitudes en espera y permite terminar las
  estacionadas. El cierre natural drena las aceptadas. `wait=True` une ambos
  trabajadores y no termina hilos a la fuerza.
- El primer `close` elige drenaje o cancelación; posteriores solicitudes de Stop
  pueden escalar un drenaje natural a cancelación de pendientes bajo la misma
  Condition. Una cancelación ya solicitada no puede volver a drenaje, aunque
  llegue un `close(cancel_pending=False)` atrasado. No se reabren admisiones.
- La UI consume eventos de la cola. Si lee un snapshot, lo hace solo como
  consulta segura, nunca para alterar el estado del core.

### Arquitectura de admisión y autorización

La arquitectura implementada mantiene FIFO por elegibilidad y FIFO estricto
entre solicitudes del mismo puesto autorizado. Solicitudes bloqueadas para un
puesto no impiden progreso en otro puesto elegible.

Esta política es el criterio de diseño aprobado. Su contrato y evidencia de
pruebas están en `openspec/specs/parking-capacity/spec.md`; el estado de una
revisión administrativa no determina por sí solo la corrección del algoritmo.

El dominio de autorizaciones está definido en `simulation/authorizations.py`.
El JSON se valida completo antes de iniciar los trabajadores y se entrega a
core como registro inmutable. El orden de la secuencia del Simulator determina
las llegadas; el orden del JSON no determina la generación.

`ParkingLot` resuelve el puesto desde el registro inmutable. `AdmissionResult`
incluye aceptado/rechazado y el motivo estable (`UNKNOWN_PLATE`,
`NOT_AUTHORIZED`, `DUPLICATE_ACTIVE`, `LOT_CLOSED` o `INVALID_REQUEST`).

---

## 10. Parámetros configurables

Evitar números mágicos dentro del código.

Los parámetros de la simulación deben centralizarse en:

simulation/config.py

Ejemplos:

PARKING_CAPACITY = 5

TOTAL_VEHICLES = 15

MIN_ARRIVAL_TIME = 1
MAX_ARRIVAL_TIME = 4

MIN_PARKING_TIME = 3
MAX_PARKING_TIME = 8

---

## 11. Pruebas mínimas

Antes de integrar una funcionalidad debe comprobarse:

1. Ningún vehículo puede entrar si todos los espacios están ocupados.

2. Nunca puede haber más vehículos estacionados que la capacidad definida.

3. Cuando un vehículo sale, otro vehículo en espera puede ingresar.

4. Dos vehículos no pueden recibir el mismo espacio simultáneamente.

5. Cerrar la aplicación no debe dejar hilos problemáticos ejecutándose.

6. La interfaz gráfica no debe congelarse durante la simulación.

7. Los eventos deben reflejar correctamente el estado interno del sistema.

---

## 12. Reglas para modificar otros módulos

Cada integrante es responsable principalmente de su módulo.

No realizar modificaciones estructurales en el módulo de otro integrante
sin comunicarlo previamente.

Especialmente NO modificar unilateralmente:

- nombres de eventos;
- estructura de eventos;
- nombres de clases públicas;
- parámetros de constructores públicos;
- estados del vehículo;
- estructura principal de carpetas.

Si es necesario cambiar el contrato compartido:

1. Proponer el cambio.
2. Revisar impacto en los tres módulos.
3. Actualizar AGENTS.md.
4. Implementar el cambio.

---

## 13. Git

Ramas de trabajo del equipo:

feature/core
feature/ui
feature/simulation

No desarrollar directamente sobre main.

Usar `integration` como rama compartida de integración entre las ramas
`feature/*` y `main`:

1. Integrar las ramas de funcionalidad en `integration`.
2. Verificar allí el comportamiento entre módulos y ejecutar las pruebas
   acordadas.
3. Promover `integration` a `main` solo cuando el proyecto integrado cumpla
   los requisitos y las pruebas pasen.

No promover ramas de funcionalidad directamente a `main`. Mantener `main`
ejecutable y evitar acumular en `integration` cambios que no se hayan probado.

Los cambios deben realizarse mediante commits pequeños y descriptivos.

Ejemplos:

feat(core): implementar control de capacidad con Semaphore

feat(ui): representar espacios disponibles

feat(simulation): agregar generación aleatoria de vehículos

fix(core): evitar asignación simultánea de un espacio

main debe mantenerse ejecutable.

---

## 14. Criterios de calidad

Priorizar:

1. Correcto funcionamiento de la concurrencia.
2. Uso adecuado de Semaphore y Lock.
3. Ausencia de condiciones de carrera.
4. Separación clara entre lógica e interfaz.
5. Interfaz responsiva.
6. Código legible.
7. Relación clara con conceptos de Sistemas Operativos.

Evitar complejidad que no contribuya a los objetivos académicos del proyecto.

---

## 15. Regla para asistentes de IA

Antes de generar o modificar código:

1. Identificar a qué módulo pertenece el cambio.
2. Respetar las responsabilidades establecidas.
3. No crear dependencias innecesarias entre módulos.
4. No modificar contratos compartidos sin indicarlo.
5. Reutilizar las estructuras existentes.
6. Explicar cualquier decisión que afecte concurrencia.
7. Mantener el código comprensible para estudiantes.

No resolver problemas de concurrencia eliminando los Threads,
Semaphore o Lock, ya que son parte fundamental del objetivo académico.

---

## 16. Database scope

SQLite persistence is explicitly excluded from the current project scope.
Do not add a database, seed records, persistence fields, or database
abstractions unless the team separately authorizes a scope change.

## 17. Registro de auditoría

- El proceso padre es dueño de una sesión con `QueueHandler`, `QueueListener`
  y un archivo UTF-8 único bajo `logs/`. Esta cola de logging es distinta de
  la cola local de eventos Tk y de las colas multiprocessing de IPC.
- El proceso hijo no abre un archivo: reenvía ciertos registros de operación
  y error por IPC. El padre valida secuencias y escribe esos registros; los
  eventos se registran una sola vez al procesar el envoltorio IPC. Cada
  ejecución tiene `run_id`, sin añadirlo a `ParkingEvent`.
- Los requisitos académicos de trazabilidad contemplan solicitudes,
  validaciones, decisiones, entradas, salidas, esperas y errores, con marcas de
  tiempo y contexto de proceso/hilo. Estos requisitos deben distinguirse de lo
  que el runtime registra actualmente; la cobertura no está completamente
  verificada.
- El cierre confirma drenaje mediante una barrera y detiene el listener tras
  el cierre del motor. Fallos de escritura, colas, transporte o confirmación
  marcan la auditoría incompleta e informan por stderr; no garantizan
  persistencia ante fallos.
- El hook temporal de excepciones conserva y delega al hook anterior. El
  registro diagnostica errores, no recupera ni repara el motor.

La auditoría actual cruza procesos hacia un único escritor padre: se transmiten
eventos y ciertos registros de auditoría, no todo el logging. Los intentos del
Simulator se correlacionan con resultados canónicos por ejecución y vehículo;
CREATED acredita aceptación validada, no ocupación. No se registran todas las
comprobaciones internas ni decisiones de selección FIFO por separado.
ENTERED persiste `waiting_time` en segundos desde la aceptación en cola hasta
la ocupación; WAITING es una observación opcional, no el inicio exacto de toda
espera. Los campos `result`, `waiting_time` y `error_summary` se anexan al formato
previo; errores resumidos del hijo no ocupan `traceback`. No cambiar contratos
de eventos/IPC para añadir estos datos ya disponibles. `origin_*` identifica al
productor, mientras `processName`/`threadName` identifica recepción/registro
padre, no el listener. Confirmación y cierre técnico de auditoría no certifican
cobertura académica ni persistencia ante caídas. Proteger datos sensibles y no
añadir escritores independientes; ver `openspec/specs/parking-events/spec.md`.

## 18. Protocolo de trabajo y decisiones académicas pendientes

- Diagnosticar el comportamiento actual antes de proponer cambios. Indicar el
  requisito incumplido y el contrato/módulo afectado; aplicar el cambio mínimo
  justificado académicamente y evitar refactorizaciones ajenas sin evidencia.
- Elegir pruebas unitarias, de integración, concurrencia y ciclo de vida
  apropiadas al cambio. Distinguir inspección estática, pruebas realmente
  ejecutadas, hipótesis y conclusiones verificadas. Que las pruebas pasen no
  demuestra por sí solo la ausencia de carreras o interbloqueos.
- Priorizar corrección académica por encima de estética.
- No modificar ramas personales cuyo nombre termine en `_edwd3v`, ni
  reincorporar el experimento descartado `fde3a8e`. Sin autorización, no hacer
  merge, push, force-push, reset destructivo, borrar ramas ni descartar cambios.
  Los archivos locales no prueban qué código está publicado en GitHub.
- Multiprocessing e IPC están implementados mediante un proceso de motor
  `spawn`, colas IPC con mensajes validados y un adaptador de transporte en el
  padre; el proceso de motor posee el estado de core. Mantener esta separación
  y no confundir la `queue.Queue` local de Tk con IPC. La conformidad académica
  integral aún requiere validación. La política FIFO entre elegibles y por puesto
  ya fue aprobada por el responsable del proyecto. No cambiar unilateralmente el
  contrato `ParkingEvent` ni las APIs públicas. El logging hijo-padre tiene un
  escritor padre, pero su cobertura debe verificarse contra los requisitos de
  trazabilidad, no darse por completa.
- Los requisitos de procesos reales no convierten en obligatorio el diseño de
  sesiones de usuario concurrentes; esa posibilidad fue solo sugerida para
  estudio.
