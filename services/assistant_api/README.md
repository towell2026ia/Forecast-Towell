# PRD 08B — Asistente local

La API consulta los resultados normalizados ya guardados en `app/data`. No abre Excel, no entrena modelos al responder y no usa OpenAI, Supabase ni búsquedas externas. Los archivos bajo `fixtures` son pruebas y no se presentan como decisiones o vintages reales.

## Arranque local

Desde la raíz del sitio:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r services\assistant_api\requirements.txt
.\.venv\Scripts\python.exe -m uvicorn services.assistant_api.api:app --host 127.0.0.1 --port 8000
```

En otra terminal, iniciar el sitio con `npm run dev`. En desarrollo, `/api/assistant/message` del sitio consulta esta API local y usa el actor `local-manager`; el backend verifica esa identidad en loopback. `GET http://127.0.0.1:8000/api/health` comprueba datos y versiones.

El sitio público actual no hospeda Python y aún no tiene una identidad de usuario verificable por el servidor. Por seguridad, la ruta web del asistente permanece deshabilitada en producción aunque se configure una URL Python. Para habilitarla en una fase posterior hacen falta ambos componentes: una API Python accesible desde el servidor web y una integración de autenticación que establezca la identidad del gerente en el servidor, sin confiar en encabezados enviados por el navegador. El panel público muestra servicio no disponible y nunca devuelve respuestas simuladas.

Las consultas son de sólo lectura. `MonthlyForecastRunner` no tiene endpoint ni se invoca desde preguntas libres. Su estado local queda en `services/assistant_api/state`, fuera de Git.

La corrida de julio de 2026 puede reproducirse con los datos normalizados actuales. Para meses anteriores, el runner exige `available_at` por registro antes de ejecutar: el archivo normalizado actual no conserva cuándo estuvo disponible cada dato histórico, así que no sería válido reconstruir un backtest retrospectivo con cifras revisadas sin esa prueba temporal. Si falla ML se usa el estadístico; si falla el ensamble se conserva el Champion publicado solamente cuando coincide el mismo corte.

## Ejemplos

- `¿Cuál es el Champion?`
- `Dame el WAPE de Azul`
- `¿Cómo está el Fill Rate?`
- `Dame el forecast de 12 meses`
- `Muéstrame P90`

La API exige un actor autorizado para las consultas. El campo `role` enviado por el navegador no confiere permisos.
