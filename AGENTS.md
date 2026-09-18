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

Cada vehículo debe comportarse como una unidad independiente de ejecución
representada mediante un hilo.

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

La dependencia general debe ser:

simulation
    ↓
core
    ↓ eventos
queue.Queue
    ↓
ui

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

Los eventos deben utilizar una estructura común.

Ejemplo:

{
    "type": "VEHICLE_ENTERED",
    "vehicle_id": 4,
    "space_id": 2
}

Tipos iniciales permitidos:

VEHICLE_CREATED
VEHICLE_WAITING
VEHICLE_ENTERED
VEHICLE_EXITED
VEHICLE_FINISHED
SIMULATION_STARTED
SIMULATION_FINISHED

Cuando corresponda, los eventos podrán incluir:

vehicle_id
space_id
timestamp
waiting_time

No cambiar nombres de campos o tipos de eventos sin coordinarlo con
los otros módulos.

---

## 5. Reglas fundamentales de concurrencia

### Threads

Cada vehículo debe ejecutarse como un Thread independiente.

No crear hilos únicamente para animaciones o elementos gráficos.

### Semaphore

La capacidad del parqueadero debe controlarse utilizando:

threading.Semaphore

Ejemplo conceptual:

Semaphore(capacidad_del_parqueadero)

Cuando no existan espacios disponibles, el hilo del vehículo debe quedar
esperando hasta que se libere un recurso.

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

Nunca hacer esto desde un hilo de vehículo:

label.config(...)
canvas.create_rectangle(...)
widget.destroy(...)
variable.set(...)

Los hilos deben enviar un evento a queue.Queue.

La interfaz debe consultar periódicamente la cola mediante:

root.after(...)

Arquitectura correcta:

Vehicle Thread
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

Interpretación respecto a Sistemas Operativos:

CREATED
    El hilo ha sido creado.

WAITING
    El hilo espera un recurso.

PARKED
    El hilo obtuvo el recurso.

FINISHED
    El hilo terminó su ejecución.

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

Ejemplo conceptual:

event_queue = Queue()

parking = ParkingLot(
    capacity=5,
    event_queue=event_queue
)

simulator = Simulator(
    parking=parking
)

app = ParkingApp(
    event_queue=event_queue,
    simulator=simulator
)

app.run()

La lógica específica debe permanecer en su módulo correspondiente.

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

Ramas principales de trabajo:

feature/core
feature/ui
feature/simulation

No desarrollar directamente sobre main.

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
