# Simulation Agent Instructions

## Responsable

Persona C — Simulación, configuración y métricas.

## Objetivo

Controlar el escenario de prueba del parqueadero.


## Responsabilidades

Implementar:

- Creación de vehículos.
- Intervalos entre llegadas.
- Tiempo de permanencia.
- Inicio de simulación.
- Detención de simulación.
- Parámetros configurables.
- Métricas y estadísticas.


## Configuración

Todos los parámetros generales deben estar en:

config.py


Ejemplos:

PARKING_CAPACITY
TOTAL_VEHICLES
MIN_ARRIVAL_TIME
MAX_ARRIVAL_TIME
MIN_PARKING_TIME
MAX_PARKING_TIME


## Métricas

Como mínimo considerar:

- Vehículos creados.
- Vehículos procesados.
- Tiempo promedio de espera.
- Máximo número de vehículos esperando.
- Máxima ocupación alcanzada.


## Restricciones

No modificar directamente la interfaz.

No modificar directamente la estructura interna de espacios del parqueadero.

Utilizar las funciones públicas proporcionadas por core/.

## Contrato con core y UI

La simulación utiliza únicamente la API pública de `core`, definida en el
[contrato raíz](../AGENTS.md#9-integración). `main.py` compone Simulator,
ParkingLot y la cola compartida; Simulator no administra espacios internos.
Simulator publica `SIMULATION_STARTED` y `SIMULATION_FINISHED` en la cola.
Los eventos del ciclo de vida de vehículos pertenecen a core.

La configuración, incluida la capacidad del parqueadero, se centraliza en
`config.py`. No importar ni modificar widgets de Tkinter.
