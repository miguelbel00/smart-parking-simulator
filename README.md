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
