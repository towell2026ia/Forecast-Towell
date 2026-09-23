# PRD 08C — Reconstrucción histórica local

El runner histórico es independiente del asistente y del Champion publicado. No tiene endpoint web; se opera mediante CLI local. `LocalResearchProvider` lee, si existen, archivos JSON `YYYY-MM.json` de un directorio indicado por el operador. Cada `source` o `signal` necesita `published_at` (fecha ISO) para entrar al snapshot. Elementos posteriores al cutoff o sin fecha se excluyen y se cuentan. La ausencia de archivo produce un snapshot vacío válido. Research no modifica los números.

Cada mes guarda, en este orden, Research congelado, DataSnapshot congelado, motores, vintage y evaluación separada. Los snapshots llevan hash de contenido; una repetición equivalente reutiliza la corrida, y `--force-rerun` crea una versión nueva sin sobrescribir la anterior. La cancelación se observa entre etapas y no cambia vintages ya cerrados. Las salidas técnicas están bajo `services/assistant_api/state/historical` (ignorado por Git).

## Evidencia temporal necesaria

`fendi-engine-series.csv` puede venir de un directorio alternativo mediante `--data-dir`. Para que una fila entre en un corte histórico necesita:

- `period`: mes del hecho, `YYYY-MM`;
- `available_at`: fecha ISO en que ese valor estuvo disponible para pronosticar, con fuente, confianza y regla identificada;
- `objective`: Venta, Pedido u otra medida identificada;
- `chain`, `pilot_scope`, `canonical_product_id`, `value`, `is_missing` y `close_status`.

La regla por defecto para disponibilidad ausente o sin procedencia suficiente es **excluir la fila**. El `TemporalAvailabilityAuditor` aplica un gate antes de los motores; rechaza `inferred` y `unknown`, conserva versiones corregidas por cutoff y genera un `InputManifest` con IDs y razones de exclusión. Venta/Pedido posteriores al mes emitido también se excluyen, aunque su fecha de disponibilidad sea anterior. Sólo un Fcst Cliente futuro realmente recibido antes del cutoff puede quedar en `known_future`; nunca se introduce como Venta Real en los motores. Los valores de evaluación requieren Venta cerrada y disponibilidad comprobable; si falta, el horizonte permanece `pending`, no cero.

El piloto FENDI empezó en 2024 (confirmación del usuario). El libro `CADENAS FINAL 2023 (B).xlsx` contiene historia real de otras líneas, pero no FENDI ni sus UPC/artículos; por eso 2023 se marca como pre-lanzamiento del piloto y no se crea Venta FENDI ficticia. El CSV normalizado comienza en 2024 y **sigue sin `available_at`**. Las asignaciones auditadas se guardan en un overlay local separado: no se reescribe la fuente. Los cierres consolidados de diciembre 2024 y julio 2026, por sí solos, no prueban que cada cifra se conocía al cierre de cada mes previo.

PRD 08C.1 incorpora la evidencia versionada de `availability_evidence.json`. La única regla activa actualmente usa la copia local de **Cierre de Julio 2026**: SHA-256 del XLSX, metadatos internos y fecha local posterior a su escritura completa (12-ago-2026). El backfill comprueba primero el hash del libro y después **cada celda normalizada**; sólo entonces asigna a las 346 filas verificadas esa fecha conservadora. No interpreta el título como una fecha de cierre específica para cada mes, ni atribuye al archivo de 2024 una recepción previa a su fecha local. La fecha del sistema de archivos es evidencia local, no un log corporativo inmutable de recepción; si el equipo de negocio no la acepta como prueba histórica, se debe deshabilitar esta regla y el vintage deja de ser válido.

El primer vintage verificable con la política actual es el emitido el **12-ago-2026** para el periodo 2026-08: el último Real utilizable es julio 2026 y el primer horizonte pronosticado es agosto 2026. Las 192 filas de 2024 permanecen bloqueadas. La ejecución histórica nunca cambia el Champion publicado.

## CLI

Desde la raíz del proyecto, con las dependencias Python instaladas:

```powershell
.\.venv\Scripts\python.exe -m services.assistant_api historical --start 2023-01 --end 2026-08
.\.venv\Scripts\python.exe -m services.assistant_api month --period 2024-07
.\.venv\Scripts\python.exe -m services.assistant_api status --run-id HRUN-FENDI-001
.\.venv\Scripts\python.exe -m services.assistant_api resume --run-id HRUN-FENDI-001 --resume-from 2025-07
.\.venv\Scripts\python.exe -m services.assistant_api cancel --run-id HRUN-FENDI-001
.\.venv\Scripts\python.exe -m services.assistant_api availability-backfill --source-dir C:\ruta\a\fuentes --dry-run
.\.venv\Scripts\python.exe -m services.assistant_api availability-backfill --source-dir C:\ruta\a\fuentes --apply
.\.venv\Scripts\python.exe -m services.assistant_api availability-audit --start 2023-01 --end 2026-08 --dry-run
.\.venv\Scripts\python.exe -m services.assistant_api availability-first-valid --start 2023-01 --end 2026-08
.\.venv\Scripts\python.exe -m services.assistant_api availability-first-vintage --start 2023-01 --end 2026-08
```

Los argumentos globales `--data-dir`, `--research-dir` y `--state-dir` van antes del subcomando. `historical` acepta `--continue-on-error` y `--force-rerun`; `month` acepta `--force-rerun`. Una corrida equivalente completa se reutiliza. Los estados y resúmenes quedan en `jobs/`, hijos en `runs/`, Research en `research/`, DataSnapshots en `data/`, vintages en `vintages/`, estados del sistema en `system/` y evaluaciones en `evaluations/`.

Los endpoints locales protegidos son `GET /api/historical/availability/audit`, `GET /api/historical/readiness/{period}`, `GET /api/historical/first-valid-period` y `POST /api/historical/first-vintage`. El backfill no se expone por HTTP. El estado generado (`availability/`, `manifests/`, `vintages/` y demás) permanece ignorado por Git: para reproducirlo en otro entorno se necesita el XLSX original con la misma huella o una copia de seguridad segura del estado. No se requiere OpenAI, Internet, Supabase ni hosting de FastAPI.

El mínimo estadístico de siete meses consecutivos tras la primera Venta positiva deriva del backtest existente: origen 6 más un Real posterior. ML exige al menos 18 muestras de entrenamiento por ventana, y el motor determina su elegibilidad real en el corte. Si ML no puede entrenarse, se usa el estadístico; si el ensamble no tiene evidencia suficiente, el vintage queda estadístico con bandas derivadas exclusivamente de residuos anteriores. La simulación histórica puede promover un Challenger que cumpla la regla de no degradación, pero nunca modifica el Champion publicado.
