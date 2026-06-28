from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup


@dataclass(frozen=True)
class SoceClient:
    timeout_seconds: float = 30.0

    def fetch_html_table(self, url: str) -> list[dict[str, str]]:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(url)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        table = soup.find("table")
        if table is None:
            return []

        headers = [cell.get_text(strip=True) for cell in table.find_all("th")]
        rows: list[dict[str, str]] = []
        for tr in table.find_all("tr"):
            values = [cell.get_text(" ", strip=True) for cell in tr.find_all("td")]
            if values:
                rows.append(dict(zip(headers, values, strict=False)))
        return rows

