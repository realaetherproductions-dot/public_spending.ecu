# Descubrimiento de fuentes reales

## Fuente inicial recomendada: SERCOP OCDS

SERCOP publica Contrataciones Abiertas Ecuador en formato OCDS/EDCA. Para el MVP
conviene empezar aqui porque hay JSON y trazabilidad, sin depender todavia de
scraping visual ni OCR.

Endpoints identificados:

```text
https://datosabiertos.compraspublicas.gob.ec/PLATAFORMA/api/search_ocds
https://datosabiertos.compraspublicas.gob.ec/PLATAFORMA/api/record
```

Uso inicial:

```text
search_ocds?year=2020&search=agua&page=1
record?ocid=<OCID>
```

Campos utiles en `search_ocds`:

```text
ocid
date
buyerId
buyerName
title
description
year
internal_type
single_provider
```

Decision de MVP:

1. Usar `search_ocds` para descubrimiento.
2. Guardar cada `ocid` como `external_id`.
3. Guardar `record?ocid=...` como `source_url` verificable.
4. Marcar estos registros como `data_origin=sercop_ocds` e `is_demo=false`.
5. En una siguiente iteracion, llamar `record` por cada `ocid` para extraer
   montos, awards, items, documentos y fechas con mas detalle.

