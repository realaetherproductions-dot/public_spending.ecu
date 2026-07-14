# Plan obligatorio de validación — cuña salud

Este documento define las condiciones mínimas para presentar el monitor como
una herramienta operativa. Una función implementada no cuenta como evidencia
hasta que el indicador correspondiente tenga datos reales.

## Alcance elegido

- **Sector:** contratación pública de salud.
- **Piloto institucional inicial:** Hospital Pediátrico Baca Ortiz.
- **Población de revisión:** hospitales, entidades IESS y direcciones de salud.
- **Regla de inclusión:** la institución contratante debe pertenecer al sector;
  una coincidencia casual de palabras en el título no es suficiente.
- **Usuarios piloto:** un medio u organización cívica, un profesional de
  cumplimiento/legal y un actor institucional.

## Puertas de salida

| Puerta | Indicador obligatorio | Estado inicial |
|---|---|---|
| Identidad | RUC extraído y normalizado para la muestra prioritaria | En ejecución |
| Reglas | Cada alerta de umbral referencia año, procedimiento, norma y URL oficial | Catálogo SERCOP 2015–2025 cargado |
| Revisión | 100 decisiones humanas terminales | Cola exportada; 0 revisadas |
| Precisión | Publicada por tipo como `confirmadas / (confirmadas + descartadas)` | Bloqueada hasta revisar |
| Historial | Al menos un cambio real conservado con valor anterior, nuevo y fuente | Demostrado en muestra OCDS |
| Operación | Auth administrativa, auditoría, backup verificado y rectificación | Implementado; requiere configurar secretos |
| Alertas | RSS y despacho email/webhook solo para casos confirmados | Implementado; email/webhook requieren credenciales |

## Flujo de revisión de 100 alertas

1. Generar la cola:

   ```powershell
   python scripts/export_health_review_queue.py
   ```

2. Completar `decision`, `reviewer`, `review_evidence_url` y `editorial_note`.
   Las decisiones permitidas son `confirmed`, `discarded` e `indeterminate`.

3. Validar sin escribir:

   ```powershell
   python scripts/import_review_decisions.py --input data/review/health_alerts_first_100.csv
   ```

4. Importar solo después de resolver todos los errores:

   ```powershell
   python scripts/import_review_decisions.py --input data/review/health_alerts_first_100.csv --apply
   ```

5. Consultar avance y precisión en `GET /review-metrics`.

No se permite convertir decisiones por heurística ni usar el mismo detector
como “revisor”. Los casos indeterminados no entran en el denominador de
precisión.

## RUC e historial

Para recuperar identificadores desde detalles OCDS ya almacenados:

```powershell
python scripts/backfill_supplier_tax_ids.py
python scripts/backfill_supplier_tax_ids.py --apply
```

Para consultar detalles faltantes de la cuña salud:

```powershell
python scripts/backfill_supplier_tax_ids.py --fetch-missing --health-only --limit 100
```

Cada detalle se conserva como registro crudo y cualquier diferencia crea un
`ContractEvent`. La evidencia agregada está disponible en `GET /history/metrics`.

## Reglas legales

No existe un umbral global de respaldo. Si falta una regla verificada, el
detector omite la alerta dependiente del umbral. Las reglas se cargan mediante
`POST /procurement-rules` con:

- año;
- tipo de procedimiento normalizado;
- monto y moneda;
- referencia legal;
- URL HTTPS oficial.

La carga requiere `X-Admin-Token` y queda en el registro de auditoría.
El script `scripts/seed_official_procurement_rules.py` reproduce el catálogo
verificado de ínfima cuantía para 2015–2025 y conserva el operador publicado
(`lt` o `lte`). El año 2026 permanece sin regla hasta que la tabla oficial sea
legible y verificable.

## Operación segura

- Configurar `ADMIN_TOKEN`, `PREMIUM_TOKEN` y `CORS_ORIGINS` fuera del código.
- Ejecutar diariamente:

  ```powershell
  python scripts/backup_database.py
  ```

- Probar restauración verificando una copia:

  ```powershell
  python scripts/backup_database.py --verify data/backups/monitor-FECHA.db
  ```

- Recibir rectificaciones en `POST /correction-requests` y resolverlas mediante
  endpoints administrativos auditados.
- Publicar solo alertas confirmadas en `/alerts.rss`, correo o webhook.
- Ejecutar despachos con `python scripts/dispatch_alerts.py` o
  `POST /alerts/dispatch`.
- Nunca guardar tokens en URLs, logs o capturas.

## Regla editorial

Una alerta es una señal para investigar, no prueba de corrupción. Ninguna vista,
exportación o notificación debe presentar una alerta abierta o indeterminada
como hecho confirmado.
