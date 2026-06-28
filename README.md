# Ecuador Public Spending Monitor

Plataforma de vigilancia y analisis de gasto publico para Ecuador.

El objetivo inicial no es cubrir todo el Estado ecuatoriano. El MVP empieza con
una fuente/institucion, guarda historico, normaliza contratos y detecta
anomalias simples que puedan revisarse por ciudadanos, periodistas, abogados,
ONGs y analistas.

## Enfoque

1. Ingestar datos publicos desde APIs, HTML o PDFs.
2. Preservar trazabilidad hacia la fuente original.
3. Normalizar nombres, fechas, montos e instituciones.
4. Detectar patrones y anomalias explicables.
5. Exponer busqueda y alertas por API/dashboard.

## Estructura

```text
app/              API, configuracion y base de datos
collectors/       Clientes de fuentes publicas y OCR
models/           Modelos de dominio
pipelines/        Ingesta, normalizacion y deteccion de anomalias
services/         Logica de consulta y analisis
scripts/          Comandos operativos
data/             Datos raw, procesados y PDFs
logs/             Logs locales
frontend/         Dashboard web futuro
```

## Inicio local

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python scripts/test_single_institution.py
uvicorn app.main:app --reload
```

Luego abre:

```text
http://127.0.0.1:8000/health
http://127.0.0.1:8000/contracts
http://127.0.0.1:8000/anomalies
```

## Interfaz local

Para operar el MVP desde una ventana:

```bash
launch_gui.bat
```

Desde esa interfaz puedes cargar datos demo, iniciar/detener la API local y abrir
los endpoints principales. Tambien puedes cargar una muestra real desde la API
OCDS de SERCOP.

Endpoints utiles:

```text
http://127.0.0.1:8000/contracts
http://127.0.0.1:8000/contracts?include_demo=false
http://127.0.0.1:8000/contracts?data_origin=sercop_ocds
```

Para traer datos reales desde consola:

```bash
python scripts/ingest_sercop_search.py --year 2020 --search agua --limit 10
```

Para generar un `.exe` en Windows:

```powershell
.\scripts\build_launcher_exe.ps1
```

El ejecutable queda en:

```text
EcuadorPublicSpendingMonitor.exe
```

Debe permanecer en la raiz del proyecto para encontrar `app/`, `scripts/` y
`requirements.txt`.

## MVP recomendado

El primer hito practico:

1. Elegir una institucion.
2. Extraer contratos de una fuente publica.
3. Guardar los datos raw y normalizados.
4. Detectar anomalias simples.
5. Publicar una busqueda basica y un reporte verificable.
