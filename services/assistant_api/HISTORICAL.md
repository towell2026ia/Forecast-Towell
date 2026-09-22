# PRD 08C — Reconstrucción histórica local

El runner histórico es independiente del asistente y del Champion publicado. No tiene endpoint web; se opera mediante CLI local. `LocalResearchProvider` lee, si existen, archivos JSON `YYYY-MM.json` de un directorio indicado por el operador. Cada `source` o `signal` necesita `published_at` (fecha ISO) para entrar al snapshot. Elementos posteriores al cutoff o sin fecha se excluyen y se cuentan. La ausencia de archivo produce un snapshot vacío válido. Research no modifica los números.

Cada mes guarda, en este orden, Research congelado, DataSnapshot congelado, motores, vintage y evaluación separada. Los snapshots llevan hash de contenido; una repetición equivalente reutiliza la corrida, y `--force-rerun` crea una versión nueva sin sobrescribir la anterior. La cancelación se observa entre etapas y no cambia vintages ya cerrados. Las salidas técnicas están bajo `services/assistant_api/state/historical` (ignorado por Git).

## Evidencia temporal necesaria

`fendi-engine-series.csv` puede venir de un directorio alternativo mediante `--data-dir`. Para que una fila entre en un corte histórico necesita:

- `period`: mes del hecho, `YYYY-MM`;
- `available_at`: fecha ISO en que ese valor estuvo disponible para pronosticar;
- `objective`: Venta, Pedido u otra medida identificada;
- `chain`, `pilot_scope`, `canonical_product_id`, `value`, `is_missing` y `close_status`.

La regla por defecto para `available_at` ausente es **excluir la fila**. Venta/Pedido posteriores al mes emitido también se excluyen, aunque su `available_at` sea anterior por error. Sólo un Fcst Cliente futuro con fecha de entrega previa puede quedar en `known_future`; nunca se introduce como Venta Real en los motores. Los valores de evaluación requieren Venta con `close_status` explícitamente cerrado/validado y `available_at` comprobable; si falta, el horizonte permanece `pending`, no cero.

El piloto FENDI empezó en 2024 (confirmación del usuario). El libro `CADENAS FINAL 2023 (B).xlsx` contiene historia real de otras líneas, pero no FENDI ni sus UPC/artículos; por eso 2023 se marca como pre-lanzamiento del piloto y no se crea Venta FENDI ficticia. El CSV normalizado disponible hoy comienza en 2024 y **carece de `available_at`**. Por ello el rango histórico real puede ejecutarse para auditar cobertura y generar estados/snapshots, pero no puede producir vintages históricos verificables hasta aportar registros normalizados con fechas de disponibilidad. Los cierres consolidados de diciembre 2024 y julio 2026, por sí solos, no prueban que cada cifra se conocía al cierre de cada mes previo.

## CLI

Desde la raíz del proyecto, con las dependencias Python instaladas:

```powershell
.\.venv\Scripts\python.exe -m services.assistant_api historical --start 2023-01 --end 2026-08
.\.venv\Scripts\python.exe -m services.assistant_api month --period 2024-07
.\.venv\Scripts\python.exe -m services.assistant_api status --run-id HRUN-FENDI-001
.\.venv\Scripts\python.exe -m services.assistant_api resume --run-id HRUN-FENDI-001 --resume-from 2025-07
.\.venv\Scripts\python.exe -m services.assistant_api cancel --run-id HRUN-FENDI-001
```

Los argumentos globales `--data-dir`, `--research-dir` y `--state-dir` van antes del subcomando. `historical` acepta `--continue-on-error` y `--force-rerun`; `month` acepta `--force-rerun`. Una corrida equivalente completa se reutiliza. Los estados y resúmenes quedan en `jobs/`, hijos en `runs/`, Research en `research/`, DataSnapshots en `data/`, vintages en `vintages/`, estados del sistema en `system/` y evaluaciones en `evaluations/`.

El mínimo estadístico de siete meses consecutivos tras la primera Venta positiva deriva del backtest existente: origen 6 más un Real posterior. ML exige al menos 18 muestras de entrenamiento por ventana, y el motor determina su elegibilidad real en el corte. Si ML no puede entrenarse, se usa el estadístico; si el ensamble no tiene evidencia suficiente, el vintage queda estadístico con bandas derivadas exclusivamente de residuos anteriores. La simulación histórica puede promover un Challenger que cumpla la regla de no degradación, pero nunca modifica el Champion publicado.
