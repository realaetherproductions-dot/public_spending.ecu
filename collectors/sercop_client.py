import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx


@dataclass(frozen=True)
class SercopClient:
    """Cliente de la API de datos abiertos de SERCOP (OCDS/EDCA).

    Solo usa HTTP + JSON publico: nada de IA ni scraping visual. Pensado para
    recorrer paginas, anios y terminos de busqueda de forma resistente a fallos
    transitorios y sin saturar el servicio publico.
    """

    base_url: str = "https://datosabiertos.compraspublicas.gob.ec/PLATAFORMA/api"
    timeout_seconds: float = 30.0
    request_delay_seconds: float = 1.0
    max_retries: int = 3
    retry_backoff_seconds: float = 2.0

    # ------------------------------------------------------------------
    # Busqueda (search_ocds)
    # ------------------------------------------------------------------
    def search_ocds(
        self,
        year: int,
        search: str,
        page: int = 1,
        buyer: str | None = None,
        supplier: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"year": year, "search": search, "page": page}
        if buyer:
            params["buyer"] = buyer
        if supplier:
            params["supplier"] = supplier
        return self.get_json("/search_ocds", params=params)

    def iter_search_pages(
        self,
        year: int,
        search: str,
        buyer: str | None = None,
        supplier: str | None = None,
        max_pages: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Recorre paginas de search_ocds entregando cada fila cruda.

        Se detiene cuando una pagina llega vacia, cuando la API reporta que ya
        no hay mas paginas (si expone ese metadato), o al llegar a
        ``max_pages``. Esto evita asumir un tamano de pagina fijo.
        """
        page = 1
        while True:
            if max_pages is not None and page > max_pages:
                return

            response = self.search_ocds(year=year, search=search, page=page, buyer=buyer, supplier=supplier)
            rows = response.get("data") or []
            if not rows:
                return

            yield from rows

            if self._is_last_page(response, page):
                return

            page += 1
            if self.request_delay_seconds:
                time.sleep(self.request_delay_seconds)

    @staticmethod
    def _is_last_page(response: dict[str, Any], current_page: int) -> bool:
        """Detecta el fin de la paginacion usando metadatos comunes.

        La API publica no documenta un esquema fijo de paginacion, asi que se
        revisan varias claves usuales (``pages``, ``total_pages``, etc.) y, si
        ninguna esta presente, se sigue avanzando hasta que una pagina llegue
        vacia (lo maneja ``iter_search_pages``).
        """
        for key in ("pages", "total_pages", "totalPages", "page_count", "pageCount"):
            value = response.get(key)
            if value is not None:
                try:
                    return current_page >= int(value)
                except (TypeError, ValueError):
                    continue
        return False

    # ------------------------------------------------------------------
    # Cobertura ampliada: multiples anios y terminos, con deduplicacion
    # ------------------------------------------------------------------
    def fetch_contracts_by_keyword(
        self,
        years: int | Iterable[int],
        search: str | Iterable[str],
        limit: int | None = 25,
        buyer: str | None = None,
        supplier: str | None = None,
        max_pages: int | None = None,
    ) -> list[dict[str, Any]]:
        """Trae contratos recorriendo todas las combinaciones anio x termino.

        Deduplica por ``ocid`` para que el mismo contrato no se cuente dos
        veces si aparece en mas de una busqueda. ``limit=None`` trae todo lo
        disponible (respetando ``max_pages`` si se define).
        """
        year_list = self._as_list(years)
        term_list = self._as_list(search)

        seen_ocids: set[str] = set()
        records: list[dict[str, Any]] = []

        for year in year_list:
            for term in term_list:
                try:
                    for row in self.iter_search_pages(
                        year=year,
                        search=term,
                        buyer=buyer,
                        supplier=supplier,
                        max_pages=max_pages,
                    ):
                        ocid = str(row.get("ocid") or "").strip()
                        if not ocid or ocid in seen_ocids:
                            continue
                        seen_ocids.add(ocid)
                        records.append(self._normalize_row(row))

                        if limit is not None and len(records) >= limit:
                            return records
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        print(f"  Rate limit (429) en {term}/{year} — guardando {len(records)} contratos recolectados")
                        return records
                    raise

        return records

    def fetch_contracts_for_institution(
        self,
        institution_name: str,
        year: int | Iterable[int] = 2020,
        search: str | Iterable[str] = "agua",
        limit: int | None = 25,
        max_pages: int | None = None,
    ) -> list[dict[str, Any]]:
        return self.fetch_contracts_by_keyword(
            years=year,
            search=search,
            buyer=institution_name,
            limit=limit,
            max_pages=max_pages,
        )

    @staticmethod
    def _as_list(value: Any) -> list[Any]:
        if isinstance(value, (list, tuple, set)):
            return list(value)
        return [value]

    def normalize_search_results(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for row in rows:
            ocid = str(row.get("ocid") or "").strip()
            if not ocid:
                continue
            records.append(self._normalize_row(row))
        return records

    def _normalize_row(self, row: dict[str, Any]) -> dict[str, Any]:
        ocid = str(row.get("ocid") or "").strip()
        source_url = f"{self.base_url}/record?{urlencode({'ocid': ocid})}"
        return {
            "external_id": ocid,
            "data_origin": "sercop_ocds",
            "is_demo": False,
            "title": row.get("description") or row.get("title") or ocid,
            "institution": row.get("buyer") or row.get("buyerName") or "Institucion desconocida",
            "supplier": row.get("suppliers") or row.get("single_provider") or "Proveedor no identificado",
            "amount": row.get("amount"),
            "procedure_type": row.get("internal_type"),
            "award_date": row.get("date"),
            "source_url": source_url,
            "locality": row.get("locality"),
            "region": row.get("region"),
        }

    # ------------------------------------------------------------------
    # Detalle por contrato (record?ocid=...)
    # ------------------------------------------------------------------
    def fetch_record_detail(self, ocid: str) -> dict[str, Any]:
        """Llama a record?ocid=<OCID> para obtener montos, adjudicaciones,
        items, partes y documentos del contrato: el detalle real detras de la
        ``source_url`` que ya guardamos en cada registro."""
        return self.get_json("/record", params={"ocid": ocid})

    def enrich_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Combina un registro normalizado de busqueda con el detalle real
        de ``record``: monto, moneda, institucion y proveedor verificados.
        Si el detalle no trae un dato, se conserva el original y nunca se
        sobreescribe con un valor vacio."""
        ocid = record.get("external_id")
        if not ocid:
            return record

        try:
            detail = self.fetch_record_detail(str(ocid))
        except httpx.HTTPError:
            return record

        extracted = self._extract_award_details(detail)
        enriched = dict(record)
        for key, value in extracted.items():
            if value not in (None, "", "Institucion desconocida", "Proveedor no identificado"):
                enriched[key] = value
        enriched["raw_detail"] = detail
        return enriched

    @staticmethod
    def _extract_award_details(detail: dict[str, Any]) -> dict[str, Any]:
        """Extrae monto/moneda/institucion/proveedor de la respuesta de
        ``record`` probando las rutas mas comunes del esquema OCDS.

        El esquema exacto de esta API publica no esta documentado de forma
        estable, asi que se navega de forma defensiva: si una ruta no existe
        simplemente se ignora y se prueba la siguiente.
        """
        result: dict[str, Any] = {
            "amount": None,
            "currency": None,
            "institution": None,
            "supplier": None,
            "supplier_tax_id": None,
            "procedure_type": None,
            "award_date": None,
        }

        release = SercopClient._find_release(detail)
        if not release:
            return result

        buyer = release.get("buyer") or {}
        if isinstance(buyer, dict) and buyer.get("name"):
            result["institution"] = buyer["name"]

        tender = release.get("tender") or {}
        if isinstance(tender, dict):
            if tender.get("procurementMethodDetails") or tender.get("procurementMethod"):
                result["procedure_type"] = tender.get("procurementMethodDetails") or tender.get("procurementMethod")
            tender_value = tender.get("value") or {}
            if isinstance(tender_value, dict) and tender_value.get("amount") is not None:
                result["amount"] = tender_value.get("amount")
                result["currency"] = tender_value.get("currency")

        awards = release.get("awards") or []
        if isinstance(awards, list):
            for award in awards:
                if not isinstance(award, dict):
                    continue
                value = award.get("value") or {}
                if isinstance(value, dict) and value.get("amount") is not None:
                    result["amount"] = value.get("amount")
                    result["currency"] = value.get("currency")
                if award.get("date"):
                    result["award_date"] = award.get("date")
                suppliers = award.get("suppliers") or []
                if isinstance(suppliers, list) and suppliers:
                    first_supplier = suppliers[0]
                    if isinstance(first_supplier, dict):
                        if first_supplier.get("name"):
                            result["supplier"] = first_supplier["name"]
                        identifier = first_supplier.get("identifier") or {}
                        if isinstance(identifier, dict) and identifier.get("id"):
                            result["supplier_tax_id"] = identifier["id"]
                if result["amount"] is not None and result["supplier"]:
                    break

        for party in release.get("parties") or []:
            if not isinstance(party, dict):
                continue
            roles = party.get("roles") or []
            same_supplier = (
                "supplier" in roles
                or (result["supplier"] and party.get("name") == result["supplier"])
            )
            if not same_supplier:
                continue
            if not result["supplier"] and party.get("name"):
                result["supplier"] = party["name"]
            identifier = party.get("identifier") or {}
            if (
                not result["supplier_tax_id"]
                and isinstance(identifier, dict)
                and identifier.get("id")
            ):
                result["supplier_tax_id"] = identifier["id"]
            if result["supplier"] and result["supplier_tax_id"]:
                break

        return result

    @staticmethod
    def _find_release(detail: dict[str, Any]) -> dict[str, Any] | None:
        """Localiza el objeto 'release' dentro de las formas usuales en que
        la API puede envolver la respuesta (compiledRelease, releases[], o el
        propio objeto raiz)."""
        if not isinstance(detail, dict):
            return None

        candidate = detail.get("compiledRelease")
        if isinstance(candidate, dict):
            return candidate

        record = detail.get("record")
        if isinstance(record, dict):
            nested = record.get("compiledRelease")
            if isinstance(nested, dict):
                return nested
            releases = record.get("releases")
            if isinstance(releases, list) and releases and isinstance(releases[-1], dict):
                return releases[-1]

        releases = detail.get("releases")
        if isinstance(releases, list) and releases and isinstance(releases[-1], dict):
            return releases[-1]

        if any(key in detail for key in ("buyer", "tender", "awards", "parties")):
            return detail

        return None

    # ------------------------------------------------------------------
    # Transporte HTTP con reintentos (sin IA, solo HTTP/JSON publico)
    # ------------------------------------------------------------------
    def get_json(self, path_or_url: str, params: dict[str, Any] | None = None) -> Any:
        url = path_or_url if path_or_url.startswith("http") else f"{self.base_url}{path_or_url}"

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.get(url, params=params)
                    response.raise_for_status()
                    return response.json()
            except (httpx.TransportError, httpx.HTTPStatusError) as error:
                last_error = error
                if attempt >= self.max_retries:
                    break
                time.sleep(self.retry_backoff_seconds * attempt)

        assert last_error is not None
        raise last_error
