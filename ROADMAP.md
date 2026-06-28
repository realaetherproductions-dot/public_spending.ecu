# Hoja de Ruta — Monitor de Gasto Público Ecuador

> **Para quien lee esto:** este documento existe para que cualquier programador
> o IA pueda retomar el proyecto sin hablar con nadie. Explica el porqué de
> cada decisión, el estado actual y qué viene después.

---

## 1. El problema que resuelve

El gasto público ecuatoriano está publicado en SERCOP (Sistema de Contratación
Pública) bajo el estándar OCDS. Los datos son accesibles pero ilegibles para
ciudadanos, periodistas y ONGs: no hay historial de cambios, no hay detección
de patrones sospechosos, no hay comparativas entre instituciones.

Esta plataforma hace tres cosas que SERCOP no hace:
1. **Guarda el historial** — detecta cuando un contrato cambia de monto,
   proveedor o fecha entre ingestas y lo registra con fecha.
2. **Detecta anomalías** — ocho algoritmos automáticos (fraccionamiento,
   concentración institucional, escalamiento de monto, etc.) con explicación
   legible en español.
3. **Expone todo por API** — para que periodistas, investigadores y otras
   plataformas puedan consumir los datos limpiamente.

**Audiencia objetivo:** periodistas de datos, ONGs anticorrupción, abogados
tributaristas, ciudadanos con RUC para buscar proveedores específicos.

---

## 2. Estado actual (28 junio 2026)

### Qué funciona completamente

| Componente | Estado | Archivo clave |
|---|---|---|
| Ingestión SERCOP OCDS | ✅ Producción | `collectors/sercop_client.py` |
| Deduplicación por hash | ✅ Producción | `pipelines/hashing.py` |
| Normalización nombres/fechas/montos | ✅ Producción | `pipelines/normalize_data.py` |
| Detección de 8 tipos de anomalía | ✅ Producción | `pipelines/detect_anomalies.py` |
| Historial de cambios por contrato | ✅ Producción | `pipelines/ingest_contracts.py` |
| API FastAPI (contratos, anomalías, stats) | ✅ Producción | `app/main.py` |
| Scheduler 3 franjas diarias | ✅ Producción | `scripts/scheduler.py` |
| Dashboard HTML de prueba local | 🔶 Prototipo | `frontend/dashboard/index.html` |
| Export CSV/Excel | 🔶 Solo CLI | `scripts/export_xlsx.py` |
| OCR para PDFs escaneados | ❌ Pendiente | `collectors/ocr_processor.py` |
| Frontend de producción | ❌ Pendiente | — |

### Base de datos

SQLite local en `data/processed/monitor.db` para desarrollo.
Para producción: cambiar `DATABASE_URL` en `.env` a PostgreSQL.

### Fuentes de datos activas

- **SERCOP OCDS** — API pública `datosabiertos.compraspublicas.gob.ec/PLATAFORMA/api`
  - Endpoint `search_ocds` para búsqueda por año + término
  - Endpoint `record?ocid=` para detalle de contrato
  - No requiere API key, límite de cortesía: 1 req/seg
- **SOCE** — scraping HTML (cliente implementado pero no integrado al scheduler)
- **PDFs** — downloader implementado, OCR pendiente

---

## 3. Arquitectura de datos

```
Fuente pública (SERCOP API)
        │
        ▼
  SercopClient                    collectors/sercop_client.py
  (HTTP + retry + paginación)
        │
        ▼
  ingest_contract_records         pipelines/ingest_contracts.py
  ┌─────────────────────────────────────────────────────────┐
  │  1. Calcular payload_hash                               │
  │  2. Si hash ya existe en raw_records → skip             │
  │  3. Guardar RawRecord (JSON crudo + hash + URL fuente)  │
  │  4. Si contrato nuevo → Contract + ContractEvent(created)│
  │  5. Si contrato existente → detectar cambios de campos  │
  │     → ContractEvent(field_changed) por cada campo       │
  └─────────────────────────────────────────────────────────┘
        │
        ▼
  detect_contract_anomalies       pipelines/detect_anomalies.py
  (8 algoritmos, idempotente)
        │
        ▼
  FastAPI endpoints               app/main.py
  GET /contracts  GET /anomalies  GET /stats
  GET /contracts/{id}             ← (añadir en Sprint 1)
  PATCH /anomalies/{id}
  POST /ingest   (token premium)
```

### Tablas de la base de datos

| Tabla | Propósito |
|---|---|
| `ingestion_runs` | Registro de cada corrida del scheduler (start, end, status, conteos) |
| `raw_records` | JSON crudo de cada objeto descargado, con hash SHA-256 para deduplicación |
| `institutions` | Entidades contratantes, normalizadas |
| `suppliers` | Proveedores, normalizados, con RUC (tax_id) si disponible |
| `contracts` | Contrato normalizado, FK a institution + supplier + last_raw_record |
| `contract_events` | Historial: "created" al crear, "field_changed" cuando cambia un campo |
| `anomalies` | Anomalías detectadas: tipo, severidad, score, razón legible, estado editorial |

---

## 4. Algoritmos de detección de anomalías

Todos son **idempotentes**: si la anomalía ya existe, actualiza score/reason
pero no crea duplicados. Un periodista puede editar el `status` y `editorial_note`
via `PATCH /anomalies/{id}` sin que la próxima detección lo borre.

| Tipo | Lógica | Severidad |
|---|---|---|
| `high_amount` | Monto ≥ 3× el promedio del dataset | medium |
| `missing_traceability` | Sin URL de fuente verificable | high |
| `fraccionamiento` | Mismo proveedor + institución, 3+ contratos bajo umbral cuya suma lo supera | high |
| `proveedor_recurrente` | Un proveedor en 5+ instituciones distintas | medium |
| `concentracion_institucional` | Una institución asigna ≥40% de contratos al mismo proveedor (mín. 4 contratos) | high |
| `fecha_sospechosa` | Adjudicado entre dic 27-31 (fin de año fiscal) | low |
| `monto_bajo_umbral` | Monto entre 85-100% del umbral de contratación directa ($7,105.88) | low |
| `escalamiento_monto` | El monto aumentó 2+ veces entre ingestas | high (ver nota) |

> **Nota:** `escalamiento_monto` está asignado como `"critical"` en el código
> pero el frontend no tiene estilo CSS para ese nivel. Sprint 1 lo corrige.

El umbral de contratación directa en Ecuador es **$7,105.88** (verificar
periódicamente en la Ley del Sistema Nacional de Contratación Pública).

---

## 5. Scheduler — 3 franjas diarias

```bash
python scripts/scheduler.py --daemon    # correr en producción
python scripts/scheduler.py --franja 2  # ejecutar manualmente franja 2
python scripts/scheduler.py --estado    # ver progreso del barrido histórico
python scripts/scheduler.py --reporte   # reporte últimas 24h
```

| Franja | Hora | Qué hace |
|---|---|---|
| 1 - Histórico | 02:00 | Barre sector×año en rotación. 12 sectores × 11 años = 132 combinaciones. Con una por noche: ~4 meses para cubrir 2015-2025 completo. |
| 2 - Recientes | 10:00 | Términos genéricos en el año en curso y el anterior. Captura adjudicaciones nuevas. |
| 3 - Emblematicos | 18:00 | Proyectos de alto interés periodístico (Metro de Quito, Coca Codo, etc.) desde 2008. |

Estado del barrido persiste en `data/processed/scheduler_state.json`.

---

## 6. Cómo correr el proyecto

```bash
# Primera vez
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux/Mac
pip install -r requirements.txt
copy .env.example .env          # editar si hace falta

# Servidor API
uvicorn app.main:app --reload
# → http://127.0.0.1:8000/health
# → http://127.0.0.1:8000/contracts
# → http://127.0.0.1:8000/docs   (Swagger UI)

# Traer datos reales
python scripts/ingest_sercop_search.py --year 2024 --search agua --limit 20

# Scheduler manual
python scripts/scheduler.py --franja 2
python scripts/scheduler.py --daemon

# Reporte de salud
python scripts/scheduler.py --reporte 48
```

Variables de entorno (`.env`):
```
DATABASE_URL=sqlite:///./data/processed/monitor.db
ENVIRONMENT=development
PREMIUM_TOKEN=tu-token-secreto-aqui
LOG_LEVEL=INFO
```

Para PostgreSQL en producción:
```
DATABASE_URL=postgresql://user:pass@host:5432/ecuador_monitor
```

---

## 7. Sprints pendientes

### Sprint 1 — Corrección de bugs críticos ✅ (objetivo inmediato)

Bugs identificados en auditoría del 28 Jun 2026:

- [x] **BUG-1**: `showContractDetail` descarga todos los contratos para encontrar uno.
      → Crear `GET /contracts/{id}` y actualizar el frontend.
- [x] **BUG-2**: Severidad `"critical"` no tiene estilo CSS → añadir `.badge-critical`.
- [x] **BUG-3**: Contratos demo generan anomalías falsas de `missing_traceability`.
      → Filtrar `is_demo=True` en `detect_contract_anomalies`.
- [x] **BUG-4**: Múltiples `POST /ingest` concurrentes escriben a SQLite sin mutex.
      → Agregar `threading.Lock()` global.
- [x] **BUG-5**: `GET /stats` muestra instituciones/proveedores incluyendo demo.
      → Filtrar por contratos no-demo con JOIN.
- [x] **BUG-6**: Token premium viaja en query string → expuesto en logs.
      → Cambiar a header `X-Premium-Token`.

### Sprint 2 — Utilidad para periodistas

Objetivo: que un periodista pueda llegar al sitio, encontrar un contrato y
compartir el link en 60 segundos.

- [ ] **URLs compartibles (deep links):** el hash de la URL (`#contract/123`)
      debe cambiar al abrir un detalle para que sea enlazable.
- [ ] **Paginación:** agregar `offset` + `limit` en `GET /contracts` y controles
      en el frontend. El cap actual de 200 es bloqueante.
- [ ] **Exportar desde UI:** botón "Descargar CSV" en la vista de contratos que
      llame a `GET /contracts/export.csv` (nuevo endpoint).
- [ ] **Conteo de resultados:** mostrar "N contratos encontrados" sobre la tabla.
- [ ] **Indicador de frescura:** `last_ingestion_at` en `GET /stats` y mostrarlo
      en el header como "Actualizado hace X horas".
- [ ] **Página de metodología:** ruta `/metodologia` que explique qué es cada
      tipo de anomalía, cómo se calcula y qué significa para un lector no técnico.
- [ ] **Documentación API pública:** FastAPI genera `/docs` automáticamente,
      pero añadir descripciones en cada endpoint y publicar la URL.

### Sprint 3 — Plataforma de referencia

Objetivo: que Ecuador Público sea citado por medios y académicos como fuente.

- [ ] **Perfil de proveedor:** `GET /suppliers/{id}` → página con todos sus
      contratos, monto acumulado, instituciones con las que trabaja, anomalías.
- [ ] **Perfil de institución:** ídem para instituciones.
- [ ] **Top rankings:**
      - Top 20 proveedores por monto adjudicado
      - Top 20 instituciones por número de contratos
      - Top 20 contratos por monto
- [ ] **Gráficas interactivas** (implementar en el frontend de producción):
      - Gasto mensual por año (línea de tendencia)
      - Distribución por tipo de proceso (barras)
      - Top instituciones (barras horizontales)
      - Mapa de calor por provincia
- [ ] **Comparativa año a año:** `GET /stats?year=2024` para comparar.
- [ ] **Alertas:** endpoint o sistema para suscribirse a nuevas anomalías de
      un proveedor o institución específica (email / RSS / webhook).
- [ ] **Cobertura de fuentes adicionales:**
      - SOCE (compras por catálogo) — cliente ya implementado, integrar al pipeline
      - PDFs de resoluciones — OCR con Tesseract (stub en `ocr_processor.py`)
      - Portal de Transparencia Fiscal (Ministerio de Finanzas)

### Sprint 4 — Frontend de producción

El `frontend/dashboard/index.html` actual es **solo para desarrollo local**.
El frontend de producción será una aplicación separada que consume la API.

Decisiones de diseño a respetar:
- **Dark editorial theme** (Bloomberg density): ya documentado en `index.html`
- **Mobile-first** con grilla responsive
- **Vanilla HTML/CSS/JS** o framework ligero (sin dependencias pesadas)
- La API es pública y documentada: el frontend puede ser cualquier tecnología

Pantallas prioritarias para producción:
1. Dashboard con KPIs + gráfica de gasto mensual
2. Explorador de contratos con filtros + paginación + export
3. Detector de anomalías con filtros
4. Perfil de contrato (con historial de cambios)
5. Perfil de proveedor
6. Perfil de institución
7. Rankings
8. Metodología / Acerca de

---

## 8. Decisiones de arquitectura ya tomadas (no cambiar sin razón)

| Decisión | Razón |
|---|---|
| **SQLite en dev, PostgreSQL en prod** | SQLite permite correr sin configuración. La misma capa SQLAlchemy funciona en ambos sin cambiar código. |
| **Raw records con hash SHA-256** | Garantiza idempotencia. Si SERCOP baja la misma API dos veces, no se duplica nada. El historial de cambios solo se activa cuando el payload realmente cambia. |
| **Anomalías idempotentes** | `_get_or_create_anomaly` nunca crea duplicados. Un periodista puede editar el status sin miedo a que la próxima detección lo sobreescriba. |
| **is_demo flag en contratos** | Permite tener datos de prueba en la misma BD sin contaminar estadísticas reales. Los demos se filtran en `/stats` y no deberían aparecer en detección de anomalías. |
| **Scheduler externo, no dentro del servidor** | El scheduler corre como proceso independiente. El servidor FastAPI no bloquea. En producción, usar systemd o cron, no threading dentro de uvicorn. |
| **Normalized names para deduplicación de entidades** | Dos registros con "MINISTERIO DE SALUD PÚBLICA" y "Ministerio de Salud Publica" se resuelven a la misma entidad via normalize_name(). |
| **Premium token para ingestas manuales** | El endpoint `/ingest` puede disparar cientos de llamadas a SERCOP. El token evita abuso. En producción, mover a header (BUG-6). |

---

## 9. Tests y validación

Los scripts en `scripts/test_phase*.py` son pruebas de integración manuales,
no tests automáticos con pytest. Correrlos antes de deploy:

```bash
python scripts/test_phase1.py   # ingestión básica
python scripts/test_phase2.py   # normalización y hashing
python scripts/test_phase3.py   # detección de anomalías
```

**Pendiente:** agregar pytest con fixtures de BD en memoria y cobertura mínima
de las funciones de detección de anomalías.

---

## 10. Qué NO hacer

- **No cambiar el esquema de BD sin agregar una migración** (o al menos
  actualizar `_ensure_contract_columns` en `app/database.py`).
- **No usar `datetime.utcnow()`** — deprecado desde Python 3.12. Usar
  `datetime.now(UTC)` de `datetime import timezone`.
- **No poner el premium_token en logs ni en URLs** — siempre en headers.
- **No detectar anomalías sobre contratos demo** — generan falsos positivos
  que confunden a los usuarios reales.
- **No agregar dependencias pesadas al backend** — el objetivo es que corra
  en un VPS de $5/mes. FastAPI + SQLAlchemy + httpx es suficiente.
- **No romper la idempotencia del pipeline** — si se corre dos veces el mismo
  ingesta, el resultado debe ser idéntico.
