# Stop escalation and bounded Tk polling recovery
Branch: dev/academic-requirements-sync; delivery: five local functional commits authorized on 2026-10-25; no push or merge. Runner: .venv/bin/python -m pytest.
Original scope: two reproduced defects only; forecast approximately 500–700 authored lines including regression tests. The dirty baseline at /tmp/opencode/stop-polling-fixes.fHYyPt/baseline was temporary evidence and has been removed.

Historical evidence: the no-commit restrictions and verification counts below describe the original implementation session, not the later consolidation authorization. Other temporary paths are historical references, not available fixtures. Original requests and outcomes are retained unchanged. The authorized consolidation preserves five functional units: FIFO, IPC reply delivery, audit traceability, late Stop and polling recovery. Each staged snapshot must be checked independently before its local commit; final verification covers the consolidated state.

## Specs

- S1: "Las solicitudes que todavía no ocupan su puesto deben cancelarse, incluso si la finalización natural ya comenzó." "Los vehículos efectivamente estacionados deben finalizar y liberar sus recursos de forma controlada." "Cada vehículo debe producir un único resultado terminal coherente."
- S2: "Verifica específicamente la carrera entre Stop y close(cancel_pending=False)." "No elimines indiscriminadamente la condición AND ni cambies la semántica general de close() sin analizar sus invariantes, idempotencia y consecuencias concurrentes."
- S3: "Una excepción durante el procesamiento de un evento no debe detener silenciosamente y de forma permanente el consumo normal de eventos." "Continuar el polling cuando sea seguro." "Evitar ciclos infinitos de excepciones o reintentos." "Evitar programar múltiples callbacks de polling simultáneos."
- S4: "Capturar y registrar el error con información diagnóstica suficiente." "Preservar la consistencia de la proyección visual y las métricas." "Ejecutar un cierre controlado cuando la recuperación segura no sea posible." "Considera errores después de actualizaciones parciales de widgets y el tratamiento de eventos que ya fueron retirados de la cola."
- S5: "Antes de aplicar cada corrección, construye o adapta pruebas que reproduzcan los defectos originales." "Ejecuta pruebas focalizadas y la suite completa, tratando excepciones no capturadas de hilos como errores." "Posteriormente, repite la validación con Tkinter real, widgets y mainloop(), motor spawn e IPC originales."
- S6: "No reabras FIFO, logging ni la corrección de duplicación del controlador sin evidencia concreta de regresión." "Mantén fuera de alcance el límite de shutdown() prematuro utilizado directamente sobre el controlador, salvo que las nuevas pruebas demuestren que afecta la ruta normal de la aplicación." "Conserva los cambios locales preexistentes. No realices commits, push, merge, reset, stash, cambios de rama ni modificaciones del índice Git sin autorización."

## Tasks

- [x] T1 — S1,S2,S5,S6 — delegated Stop writer; 6 intended RED failures, then 42 focused tests passed; commit prohibited. Risk: items 3/4 (shared close contract and ordering).
- [x] T2 — S3–S6 — delegated UI writer; 6 intended RED failures, then 48 focused tests passed; commit prohibited. Risk: items 3/4 (polling, partial state and callback ordering).
- [x] T3 — S1–S6 — parent inline documentation and seam checks; 2 finish-recovery RED cases corrected; 232 focused / 273 full tests passed; commit prohibited.
- [x] T4 — S1–S6 — independent verifier: 232 focused tests, 7 independent probes and 5 real-Tk scenarios passed; no confirmed blockers; commit prohibited. Native isolated review remains administrative pending.

## Log

- L1 — User request (verbatim):

Continúa con el desarrollo de Smart Parking Simulator.

El diagnóstico de integración con Tkinter real identificó dos defectos reproducibles: Stop tardío no cancela solicitudes pendientes y una excepción durante el despacho de eventos interrumpe el polling normal de la interfaz.

Se autoriza corregir exclusivamente estos dos defectos, con modificaciones mínimas y pruebas de regresión.

Antes de modificar código, verifica el estado actual del repositorio, los AGENTS.md aplicables y los cambios locales pendientes.

1. Inspecciona la interacción entre Simulator.stop(), Simulator._run(), ParkingLot.close() y el parámetro cancel_pending.

Establece y preserva el siguiente contrato funcional:

- La finalización natural de una simulación puede permitir el drenaje de las solicitudes previamente aceptadas, conforme al comportamiento vigente.
- Una solicitud explícita de Stop debe detener nuevas generaciones y admisiones según los contratos actuales.
- Las solicitudes que todavía no ocupan su puesto deben cancelarse, incluso si la finalización natural ya comenzó.
- Los vehículos efectivamente estacionados deben finalizar y liberar sus recursos de forma controlada.
- Cada vehículo debe producir un único resultado terminal coherente.
- No deben producirse sobreocupación, pérdida de permisos del Semaphore ni inconsistencias en los registros de placas y puestos.
- Se debe preservar la política FIFO aprobada.

Verifica específicamente la carrera entre Stop y close(cancel_pending=False).

No elimines indiscriminadamente la condición AND ni cambies la semántica general de close() sin analizar sus invariantes, idempotencia y consecuencias concurrentes.

Implementa el mecanismo mínimo que permita aplicar correctamente la cancelación solicitada por el usuario.

2. Inspecciona el ciclo de polling en ui/interface.py, especialmente _schedule_poll(), el procesamiento de la cola y _dispatch_event().

Una excepción durante el procesamiento de un evento no debe detener silenciosamente y de forma permanente el consumo normal de eventos.

Define una política mínima y segura que permita:

- Capturar y registrar el error con información diagnóstica suficiente.
- Mantener disponible la posibilidad de detener o cerrar la aplicación.
- Continuar el polling cuando sea seguro.
- Evitar ciclos infinitos de excepciones o reintentos.
- Evitar programar múltiples callbacks de polling simultáneos.
- Preservar la consistencia de la proyección visual y las métricas.
- Ejecutar un cierre controlado cuando la recuperación segura no sea posible.

No asumas que agregar un finally que reprograme el polling es suficiente. Considera errores después de actualizaciones parciales de widgets y el tratamiento de eventos que ya fueron retirados de la cola.

3. Antes de aplicar cada corrección, construye o adapta pruebas que reproduzcan los defectos originales.

Para Stop, valida como mínimo:

- Stop antes de completar la generación.
- Stop después de completar la generación, con solicitudes esperando.
- Stop cuando la finalización natural ya comenzó.
- Stop repetido.
- Liberación de puestos mientras ocurre la cancelación.
- Resultados terminales únicos y consistentes.
- Ausencia de fugas de capacidad y recursos.

Para el polling, valida:

- Excepción controlada durante el despacho.
- Continuidad del polling cuando la recuperación sea segura.
- Registro del error.
- Ausencia de duplicación de callbacks.
- Coherencia de la interfaz después de recuperarse o iniciar un cierre controlado.
- Stop y cierre disponibles después del error.
- Drenaje y terminación de recursos.

4. Ejecuta pruebas focalizadas y la suite completa, tratando excepciones no capturadas de hilos como errores.

Posteriormente, repite la validación con Tkinter real, widgets y mainloop(), motor spawn e IPC originales.

Incluye escenarios de Stop temprano, Stop tardío, reinicio, excepción controlada y cierre con backlog.

5. Comprueba que las modificaciones no alteran:

- FIFO entre solicitudes elegibles y FIFO por puesto.
- Autorizaciones JSON y exclusión de placas activas.
- Semaphore, Lock y Condition.
- Los contratos de multiprocessing e IPC.
- La entrega única de mensajes del controlador.
- La trazabilidad y los terminales de auditoría.
- La propiedad de Tkinter de actualizar widgets exclusivamente desde el hilo principal.

6. Mantén fuera de alcance el límite de shutdown() prematuro utilizado directamente sobre el controlador, salvo que las nuevas pruebas demuestren que afecta la ruta normal de la aplicación.

No rediseñes cleanup, IPC, logging ni la GUI para abordar riesgos hipotéticos.

7. Actualiza únicamente las pruebas y la documentación vigente que deban reflejar los contratos corregidos. Evita cambios cosméticos y refactorizaciones generales.

Al finalizar, informa:

- Causa raíz confirmada de cada defecto.
- Pruebas que reproducían el comportamiento anterior.
- Archivos y funciones modificados.
- Justificación de las modificaciones mínimas.
- Semántica final de Stop y finalización natural.
- Política de recuperación o cierre ante excepciones de polling.
- Resultados de pruebas focalizadas y suite completa.
- Resultados de integración con Tkinter real.
- Evidencia de consistencia entre terminales, auditoría, métricas y pantalla.
- Procesos e hilos propios restantes después del cierre.
- Riesgos y limitaciones pendientes.

Conserva los cambios locales preexistentes. No realices commits, push, merge, reset, stash, cambios de rama ni modificaciones del índice Git sin autorización.

No reabras FIFO, logging ni la corrección de duplicación del controlador sin evidencia concreta de regresión.

Detente después de implementar y validar ambos defectos. No inicies mejoras visuales ni ampliaciones funcionales de la simulación.

- L2 — Baseline: branch dev/academic-requirements-sync, HEAD6e9f805, 15 dirty tracked paths and existing audit task untracked; no index changes. Stop design: first close selects its mode, later cancellation can escalate monotonically under the same Condition. UI design: never replay consumed widget dispatch; bounded reconstruction from canonical state, then fail closed if unsafe/repeated. Parent owns all shared docs and Git. No source mutation before task creation. No CLI changes planned.
- L3 — T1: first close selects the requested mode; subsequent cancellation is monotonic under the original Condition. No Simulator production changes. Regression tests cover both Stop/natural-close orderings, repeated requests, release/cancellation races, terminal uniqueness, plates, slots and permits. The initial test harness had a teardown timeout; corrected RED reproduced 6 intended failures, then 42 tests passed in 1.43 s (recheck 1.47 s).
- L4 — T2: canonical state is folded before rendering. Removed events never replay; first render error reconstructs stateful widgets once per run, repeated/unrepairable errors request Stop and drain canonically without retrying broken widgets. One normal after token and nonrecursive shutdown checks. Existing parent audit records UI diagnostics through a small adapter method, with Tk/stderr fallback. Worker RED: 6 intended failures; final 48 tests passed in 3.98 s. Parent added 2 RED cases for recovered finish before restart scheduling and restored the guarded restart check. All shared docs updated by parent only.
- L5 — Combined verification: 232 focused tests passed in 13.75 s; full suite 273 passed in 13.73 s. Commands: `.venv/bin/python -m pytest` (focused: parking, simulator, app_shutdown, ui_projection, multiprocess_gui_adapter, multiprocess, audit_logging, ipc_protocol, main), `-q -p no:cacheprovider -W error::pytest.PytestUnhandledThreadExceptionWarning --tb=short`; external HOME/TMPDIR and no bytecode writes. Diff check passed. No CLI change, normalization tool, new IPC/message field, logging schema change or controller mutation. Authored change forecast exceeded by coherent regression coverage; no commit is authorized, so no delivery split is attempted.
- L6 — Independent verification: S1–S6 met, no confirmed blockers. 232 focused tests passed in 13.78 s; 7 independent probes passed in 1.62 s. Baseline comparison reproduced 3 intended core failures and preserved 2 cases; a baseline native-Tk seam stopped polling while the candidate continued. Initial probe assumptions about optional WAITING and a transient graphical observation predicate were corrected in the harness, not production.
- L7 — Fresh real Tk 8.6.14/X11, actual main composition, widgets/mainloop and original spawn/IPC: late Stop 6 accepted -> 2 FINISHED/4 CANCELLED; restart -> 6/0; early Stop 5 -> 2/3; partial render recovery followed by restart -> 2/4 then 6/0; repeated render failure with broken status -> controlled close; recovered finish -> successful restart. 18,910 guarded Tcl calls had zero foreign-thread access, maximum normal poll callbacks=1. Maximum heartbeat gaps were 57.1–132.6 ms (diagnostic threshold 250 ms). Recovery/finish each persisted 1 UI diagnostic; fatal persisted 2. Source/consumed order, audit identities, terminals, metrics and healthy/recovered widgets matched; fatal views stayed explicitly failed. Normal cleanup discarded no terminals. Engine/transport/audit listener stopped without forced termination; a daemon QueueFeederThread remained until runner exit, then observed process/resource-tracker PIDs were absent. Parent repeated late Stop/restart/backlog close: passed, 2/4 then 6/0 then 2/4, maximum heartbeat 138.4 ms, zero widget-thread violations. All diagnostic scratch is removed after final checks.
- L8 — RDD is on; read-only assessment escalated item 4 and returned high/review_due. The available workspace candidate includes pre-existing closed FIFO/logging/controller changes. No START, consent, reviewer, approval, index manipulation or commit was invoked to force a mixed review. Independent technical proof is complete; isolated native review remains separate administrative pending. No next phase or direct-controller cleanup change was started.
