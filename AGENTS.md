# AGENTS.md

## 1. Objetivo del proyecto

Desarrollar un simulador de parqueadero inteligente utilizando Python y Tkinter.

El proyecto debe representar conceptos fundamentales de Sistemas Operativos:

- Procesos e hilos.
- Concurrencia.
- Sincronización.
- Exclusión mutua.
- Locks.
- Semáforos.
- Bloqueo de procesos.
- Gestión de recursos compartidos.

La implementación actual representa cada vehículo mediante un `Vehicle`
que hereda de `Thread`. Este es un hecho del runtime actual, no una
prescripción para desarrollo nuevo. La migración al modelo objetivo sigue
pendiente y no está implementada.

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
)
```

Tipos iniciales permitidos:

VEHICLE_CREATED
VEHICLE_WAITING
VEHICLE_ENTERED
VEHICLE_EXITED
VEHICLE_FINISHED
SIMULATION_STARTED
SIMULATION_FINISHED

Core es responsable de los eventos del ciclo de vida de vehículos.
`Simulator` es responsable de `SIMULATION_STARTED` y
`SIMULATION_FINISHED`. Los campos opcionales se informan cuando corresponda.

No cambiar nombres de campos o tipos de eventos sin coordinarlo con
los otros módulos.

---

## 5. Reglas fundamentales de concurrencia

### Threads

El runtime actual usa un hilo por vehículo; esa implementación se conserva
como referencia hasta completar la migración. No agregar desarrollo nuevo
basado en un hilo por vehículo ni ubicar la espera de admisión dentro de un
hilo propio del vehículo. El objetivo aprobado usa hilos orientados a tareas,
con admisión FIFO por elegibilidad y FIFO estricto entre solicitudes que
compiten por el mismo puesto autorizado. No crear hilos únicamente para
animaciones o elementos gráficos.

### Semaphore

La capacidad del parqueadero debe controlarse utilizando:

threading.Semaphore

Ejemplo conceptual:

Semaphore(capacidad_del_parqueadero)

La seguridad de capacidad debe mantenerse con `Semaphore` y sincronización
apropiada. El runtime actual espera dentro del hilo del vehículo; esto no es
el diseño objetivo. La futura admisión debe encolar sin bloquear al llamador.

### Lock

Los datos compartidos que puedan ser modificados concurrentemente deben
protegerse utilizando:

threading.Lock

Ejemplos:

- Lista de espacios ocupados.
- Asignación de puestos.
- Contadores compartidos.
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

Flujo objetivo (migración pendiente; el runtime actual aún usa `Vehicle(Thread)`):

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
En el runtime actual se reflejan mediante `Vehicle(Thread)`; el mapeo a tareas
del modelo objetivo está pendiente.

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

`Simulator` admite, detiene y cierra cada ejecución mediante la API pública
de su propio `ParkingLot`; publica los eventos de inicio y fin en la cola
reenviadora de esa ejecución. La fábrica crea un parqueadero y métricas
independientes por ejecución; la UI solo consume la cola compartida y solicita
inicio o detención a `Simulator`, sin administrar hilos ni recursos de core.
El informe final corresponde únicamente a las métricas de la última ejecución.
No se modifican las API públicas de core ni los tipos o campos de los eventos.
Este acuerdo no asigna la persistencia SQLite: su propietario, punto de
integración y sincronización siguen pendientes de decisión según §16.

La lógica específica debe permanecer en su módulo correspondiente.

### API pública mínima de core (implementación actual)

- `Vehicle(Thread)` recibe `vehicle_id`, `parking` y `parking_duration`.
  `ParkingLot` registra, admite e inicia el hilo; el vehículo coordina su
  ciclo de vida mediante `ParkingLot`.
- `ParkingLot(capacity: int, event_queue: Queue)` expone
  `admit(vehicle: Vehicle) -> bool`, `snapshot() -> ParkingSnapshot` y
  `close(wait: bool = True) -> None`.
- `admit` devuelve `True` si el vehículo fue aceptado e iniciado, no si
  obtuvo un espacio inmediatamente. En el runtime actual la espera y los
  eventos correspondientes ocurren dentro del hilo `Vehicle`; esto no define
  la arquitectura objetivo.
- `ParkingSnapshot` es una lectura inmutable/copiada con `capacity`,
  `occupied_count`, `waiting_count` y `occupied_spaces`, una tupla de pares
  `(space_id, vehicle_id)`. No expone estructuras mutables internas.
- `close` rechaza nuevas admisiones, cancela vehículos que esperan y permite
  terminar a los ya estacionados. Con `wait=True`, espera a que terminen los
  hilos activos. No se terminan hilos a la fuerza; la política requiere
  sincronización interna.
- La UI consume eventos de la cola. Si lee un snapshot, lo hace solo como
  consulta segura, nunca para alterar el estado del core.

### Arquitectura objetivo aprobada — migración pendiente

No se ha implementado coordinador, hilos orientados a tareas ni cambio de
admisión. El runtime actual sigue usando `Vehicle(Thread)` y la API descrita
arriba. No agregar desarrollo nuevo basado en un hilo por vehículo. El diseño
objetivo establece FIFO por elegibilidad y FIFO estricto entre solicitudes
del mismo puesto autorizado.

El dominio de autorizaciones está definido en `simulation/authorizations.py`.
El JSON se validará completo antes de una futura ejecución y se entregará a
core mediante su API pública; el runtime actual todavía no lo carga ni utiliza.

En una futura integración, `AdmissionCommand` tendrá `vehicle_id` único dentro
de la ejecución, patente canónica y duración; `ParkingLot` resolverá
`authorized_space_id` desde el registro inmutable. `AdmissionResult` llevará
aceptado/rechazado, referencia a la solicitud y, si se rechaza, una razón
estable: `UNKNOWN_PLATE`, `NOT_AUTHORIZED`, `DUPLICATE_ACTIVE`, `LOT_CLOSED` o
`INVALID_REQUEST`. Aceptado significa encolado/activo, no estacionado. Estos
contratos no están conectados al runtime y no cambian la API actual de core o
eventos.

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
