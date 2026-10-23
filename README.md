# Simulador de parqueadero inteligente

Proyecto académico en Python y Tkinter para representar procesos, hilos,
concurrencia, sincronización y gestión de recursos compartidos. El runtime
actual representa vehículos como solicitudes de datos coordinadas por hilos
orientados a tareas; no crea un hilo por vehículo. Multiprocessing e IPC son
requisitos académicos obligatorios aún pendientes de implementación y diseño.

## Módulos

- `core/`: ciclo de vida de vehículos, capacidad, sincronización y eventos.
- `simulation/`: configuración, generación de vehículos y métricas; utiliza
  solo la API pública de `core`.
- `ui/`: interfaz Tkinter que consume eventos de la cola compartida sin
  controlar hilos ni administrar espacios.
- `main.py`: composición de los módulos y de la cola compartida; obtiene la
  capacidad desde `simulation/config.py`.

## Contrato de integración

Los detalles de la API mínima, los eventos y las reglas de concurrencia se
mantienen en el [contrato de equipo](AGENTS.md). La UI actualiza la vista
desde el hilo principal al consumir eventos; un snapshot, si se consulta,
es únicamente una lectura segura del estado del parqueadero.
