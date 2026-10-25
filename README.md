# Simulador de parqueadero inteligente

Proyecto académico en Python y Tkinter para representar procesos, hilos,
concurrencia, sincronización y gestión de recursos compartidos. El runtime
actual representa vehículos como solicitudes de datos coordinadas por hilos
orientados a tareas; no crea un hilo por vehículo. Un proceso de motor creado
con `spawn` posee el estado de la simulación. Se comunica mediante colas
`multiprocessing` y mensajes IPC validados con el proceso padre que ejecuta Tk.
Esta implementación no certifica por sí sola todos los requisitos académicos.

## Módulos

- `core/`: ciclo de vida de vehículos, capacidad, sincronización y eventos.
- `simulation/`: configuración, generación de vehículos y métricas; utiliza
  solo la API pública de `core`.
- `ui/`: interfaz Tkinter que consume eventos de la cola compartida sin
  controlar hilos ni administrar espacios.
- `main.py`: composición de la auditoría, controlador IPC, adaptador de
  transporte y cola local de Tk; obtiene la capacidad de `simulation/config.py`.

## Contrato de integración

Los detalles de la API mínima, los eventos y las reglas de concurrencia se
mantienen en el [contrato de equipo](AGENTS.md). La UI actualiza la vista
desde el hilo principal al consumir eventos; un snapshot, si se consulta,
es únicamente una lectura segura del estado del parqueadero.

Mientras espera una respuesta, el controlador conserva una sola entrega pública
de cada mensaje recibido, en el orden observado. Las respuestas se correlacionan
por solicitud, comando y ejecución; los eventos y registros de auditoría previos
no se vuelven a encolar al comprobar esa respuesta.

## Política FIFO aprobada

Se aplica FIFO entre solicitudes elegibles, con FIFO estricto por puesto
autorizado. Si A espera por su puesto ocupado, B puede ingresar a su propio
puesto libre, aunque haya llegado después. Al liberarse el puesto de A, se
atiende primero a la solicitud más antigua que sigue esperando ese recurso.
Nunca se reasignan puestos. El orden corresponde a la aceptación bajo el lock,
no al inicio de llamadas concurrentes.

Esta decisión del responsable del proyecto evita bloqueo global innecesario y
mantiene el orden entre competidores por el mismo recurso. No es FIFO global
estricto ni queda pendiente de autorización de la profesora. Las garantías,
límites, pruebas y estado de revisión se detallan en la
[especificación de capacidad](openspec/specs/parking-capacity/spec.md#requirement-arrival-order-and-eligible-fifo).

## Auditoría y trazabilidad

El motor envía eventos y ciertos registros de operación/error por IPC. El padre
los valida y registra mediante `AuditSession`: una cola local de logging y un
listener escriben un archivo UTF-8 por sesión en `logs/`. No hay un escritor de
archivo en el hijo. La cola de logging, las colas IPC y la cola de Tk son distintas.

Cada intento del Simulator se correlaciona por `run_id` y `vehicle_id` con
CREATED (aceptación validada, no ocupación) o REJECTED (motivo estable). Los
eventos canónicos registran espera observable, ocupación, liberación y terminales
sin crear un segundo registro equivalente. ENTERED persiste `waiting_time` en
segundos desde la aceptación en cola hasta el compromiso de ocupación; WAITING
es opcional y no marca necesariamente el comienzo de toda espera.

El formato agrega al final `waiting_time`, `result` y `error_summary`; conserva
las columnas previas. Los resúmenes de errores del hijo (hasta 1000 caracteres
antes de escapar delimitadores) van a `error_summary`, no a `traceback`.
Los consumidores que antes interpretaban esa columna como error del hijo deben
usar la nueva; no se modifican archivos históricos ni el protocolo IPC v1.
Los mensajes de excepción pueden contener información sensible: no incluir
credenciales ni datos ajenos a la operación en ellos y proteger el acceso a logs.

`timestamp` identifica el registro en el padre y `event_time` el tiempo original
cuando está disponible. `origin_*` identifica al productor; `processName` y
`threadName` identifican el contexto padre que recibe/registra, no el hilo del
listener que escribe físicamente. `audit_confirmed` y `audit_complete` expresan
confirmación/drenaje técnico, no cobertura académica ni durabilidad ante caídas.
Las métricas, la pantalla y stdout no sustituyen el archivo de auditoría.

El [contrato de eventos y auditoría](openspec/specs/parking-events/spec.md#requirement-concurrent-audit-is-safe-and-traceable)
detalla resultados, límites y pruebas. SQLite está fuera del alcance.

## Detención y errores de interfaz

Stop cancela las solicitudes todavía pendientes, incluso si el productor ya
terminó de generar y el motor comenzó un drenaje natural. Los vehículos
estacionados finalizan y liberan sus recursos. La cancelación puede escalar un
cierre previo, pero una llamada natural atrasada no puede desactivarla.
