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

Esta es la implementación actual basada en hilos; todavía no implementa
multiprocessing ni IPC. Su incorporación es obligatoria, pero siguen pendientes
de decisión el reparto de responsabilidades entre procesos, el mecanismo IPC y
la propiedad/sincronización del estado crítico. No presentar la arquitectura
actual como cumplimiento de ese requisito. El profesor sugirió estudiar
sesiones de usuario/usuarios concurrentes, pero no exigió ese diseño.

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

main.py compone `simulation`, `core`, `queue.Queue` y `ui`. `simulation`
invoca únicamente la API pública de `core`. Core y Simulator publican sus
eventos en la cola compartida, que consume la UI.

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

La comunicación entre los hilos y la interfaz debe realizarse mediante:

queue.Queue

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

El runtime actual de `ParkingLot` usa dos hilos orientados a tareas por
ejecución: admisión y vencimientos/salidas. `Simulator` conserva un hilo
productor. No agregar hilos por vehículo ni ubicar esperas de admisión o
permanencia dentro de una solicitud. La arquitectura multiproceso académica
obligatoria aún debe diseñarse; no implica que cada vehículo tenga su propio
hilo o proceso.

La regla académica de FIFO respeta el orden de llegada y da prioridad al
vehículo que lleva más tiempo esperando cuando cumple su autorización y su
puesto específico está disponible. Sigue pendiente definir qué ocurre si el
vehículo más antiguo tiene bloqueado su puesto. El runtime actual busca
solicitudes elegibles y mantiene FIFO estricto por puesto autorizado; no
considerar ese comportamiento una decisión sobre la política académica aún
pendiente.

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

Tras proponer el cambio y revisar su impacto con los responsables de los
tres módulos conforme a §12, se acordó que `main.py` lea la capacidad desde
`simulation/config.py`, cree una sola cola para la UI y suministre a
`Simulator` una fábrica de recursos nuevos para cada ejecución. Ejemplo
conceptual:

ui_queue = Queue()

def run_factory():
    metrics = SimulationMetrics()
    event_queue = MetricsForwardingQueue(destination=ui_queue, metrics=metrics)
    parking = ParkingLot(capacity=PARKING_CAPACITY, event_queue=event_queue)
    return parking, event_queue, metrics

simulator = Simulator(run_factory=run_factory)

app = ParkingApp(
    event_queue=ui_queue,
    simulator=simulator,
    capacity=PARKING_CAPACITY,
)

app.run()

`Simulator` recibe una secuencia ordenada de patentes. `main.py` valida el
registro JSON completo antes de iniciar la ejecución y lo inyecta en el
`ParkingLot` recién creado. `Simulator` admite, detiene y cierra la ejecución
mediante la API de `ParkingLot`; publica los eventos de inicio y fin en la cola
reenviadora de esa ejecución. La fábrica crea un parqueadero y métricas
independientes por ejecución; la UI solo consume la cola compartida y solicita
inicio o detención a `Simulator`, sin administrar hilos ni recursos de core.
El informe final corresponde únicamente a las métricas de la última ejecución.
No se modifican las API públicas de core ni los tipos o campos de los eventos.
Este acuerdo no asigna la persistencia SQLite: su propietario, punto de
integración y sincronización siguen pendientes de decisión según §16.

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
- La UI consume eventos de la cola. Si lee un snapshot, lo hace solo como
  consulta segura, nunca para alterar el estado del core.

### Arquitectura de admisión y autorización

La arquitectura implementada mantiene FIFO por elegibilidad y FIFO estricto
entre solicitudes del mismo puesto autorizado. Solicitudes bloqueadas para un
puesto no impiden progreso en otro puesto elegible.

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

## 16. Database documentation requirements

- Use SQLite as the local SQL database engine.
- Include sample vehicle records so SQL queries can be demonstrated.
- Persist one parking movement/visit record per parking session, including
  its entry and exit times.
- Keep sample seed records distinguishable from data created during a program
  run; do not treat sample records as runtime-generated records.
- Preserve the existing module boundaries: the UI must not perform database
  work or control vehicle threads, and worker threads must not update Tkinter.
- The database ownership, integration point, and synchronization approach are
  not specified here. Agree on them before assigning persistence
  responsibility or changing shared module contracts.
- Keep this educational application simple and explainable. Do not add
  unconfirmed database features, fields, migrations, or abstraction layers.

## 17. Registro de auditoría

- Cada sesión de la aplicación usa un `QueueHandler`, un `QueueListener` y un
  archivo UTF-8 único bajo `logs/`; esta cola es independiente de la cola Tk.
- Los eventos se auditan una sola vez en el adaptador de publicación, sin
  modificar `ParkingEvent`; cada ejecución tiene un `run_id` propio.
- La sesión detiene y vacía el listener solo después de detener y unir los
  trabajadores. Si falla la escritura o el encolado, informa por stderr y
  marca la auditoría como incompleta; no garantiza persistencia ante fallos.
- El hook temporal de excepciones conserva y delega al hook anterior. El
  registro diagnostica errores, no recupera ni repara el motor.

La auditoría actual usa colas de logging dentro del proceso. El requisito
académico de logging concurrente, seguro y trazable debe mantenerse al integrar
multiprocessing; el diseño compartido de logging todavía no está decidido. El
registro debe permitir reconstruir solicitudes, validaciones, decisiones de
admisión, esperas, entradas, salidas y errores, con marcas temporales y contexto
concurrente suficiente para correlacionar proceso/hilo y ejecución. No afirmar
que el logging actual cubre todos estos campos sin verificarlo; evitar exponer
datos sensibles y evitar escritores independientes no sincronizados para el
estado crítico.

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
- Multiprocessing e IPC son requisitos obligatorios aún no implementados. Antes
  de asignar responsabilidades o cambiar contratos, acordar el reparto entre
  procesos, el mecanismo de IPC, la propiedad y sincronización del estado crítico,
  la política FIFO cuando el puesto del más antiguo está bloqueado y el logging
  seguro/trazable entre procesos. No cambiar el contrato actual de eventos
  `queue.Queue` ni las APIs públicas unilateralmente. Los procesos deben tener
  responsabilidades funcionales reales, no ser procesos decorativos; evitar
  escritores independientes del estado crítico salvo que exista sincronización
  explícita y una propiedad de estado acordada.
- Los requisitos de procesos reales no convierten en obligatorio el diseño de
  sesiones de usuario concurrentes; esa posibilidad fue solo sugerida para
  estudio.
