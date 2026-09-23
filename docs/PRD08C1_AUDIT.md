# PRD 08C.1 — Auditoría de disponibilidad temporal

Piloto: FENDI BD en Walmart. Auditoría local realizada el 23-sep-2026. No se modificaron Dashboard, Assistant, Lottie ni el Champion productivo.

| Resultado | Valor |
| --- | ---: |
| Cortes auditados, 2023-01 a 2026-08 | 44 |
| READY | 0 |
| READY_WITH_WARNINGS | 1 |
| BLOCKED_AVAILABILITY | 31 |
| NO_DATA | 12 |
| Registros auditados | 538 |
| Registros elegibles al último corte | 346 |
| Registros sin fecha demostrada al último corte | 192 |
| Cobertura temporal | 64.31% |
| Primer periodo válido | 2026-08 |
| Primer cutoff válido | 2026-08-12 |
| Último Real usado para entrenar | 2026-07 |
| Primer vintage | PASS |
| Fugas de datos / Research | 0 / 0 |

La regla `SOURCE_SNAPSHOT_RECEIPT_2026_07_V1` utiliza el archivo `Estadistica Todas las Cadenas Cierre de Julio 2026.xlsx`, SHA-256 `fc11daae57969e293d305c5df673368463e3aea2b69e264c9832a17d07c001fb`. Sus propiedades internas registran modificación el 6-ago-2026 y la copia local registra escritura completa el 12-ago-2026 a las 18:26:01 UTC. El backfill verificó la huella y las 346 celdas contra el CSV normalizado. No se asignó una fecha de disponibilidad por simple coincidencia con el mes de Venta/Pedido.

Primer vintage congelado: `V-RUN-FENDI-2026-08-003`, hash `94656300368c85c67ad5dd8ec9b060685ddff58403e502b1f7f98a174bed8e81`. Research Snapshot: `RS-FENDI-2026-08-a768efab8edd` (sin señales ni fuentes). Data Snapshot: `DS-FENDI-2026-08-afd3537cd1a6`. Input Manifest: `IM-FENDI-2026-08-372e08e9a6af`; incluye 346 registros y excluye 192 con razón `availability_unknown`. Los motores estadístico, ML y ensamble se ejecutaron; el Champion histórico de ese vintage fue ML. Se guardaron 12 horizontes, agosto 2026 a julio 2027, con P10/P50/P90/P95. El Champion productivo no se alteró.

La fecha del sistema de archivos es una evidencia local observada, no un recibo corporativo inmutable. Si se descubre que los metadatos fueron copiados o alterados, la regla debe deshabilitarse y este vintage se reclasifica como no validado. Los archivos Excel originales no se publican en este repositorio; para reproducir el backfill en otro entorno es necesaria la copia exacta cuya huella consta arriba. El estado técnico completo del vintage se conserva localmente bajo `services/assistant_api/state/historical` y no se sube a Git porque incluye resultados operativos.
