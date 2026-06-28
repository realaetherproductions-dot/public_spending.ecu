import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from shutil import which
from tkinter import (
    BOTH, END, LEFT, RIGHT, W,
    Button, Entry, Frame, Label, Scrollbar, StringVar, Text, Tk, Y,
)


ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
PYTHON = str(VENV_PYTHON) if VENV_PYTHON.exists() else (which("python") or sys.executable)
API_URL = "http://127.0.0.1:8000"

BG = "#f5f7fb"
DARK = "#0f172a"
FG_WHITE = "#ffffff"


def _btn(parent, text, command, bg="#2563eb", active_bg="#1d4ed8"):
    return Button(
        parent, text=text, command=command,
        bg=bg, fg=FG_WHITE, activebackground=active_bg, activeforeground=FG_WHITE,
        relief="flat", padx=14, pady=8, font=("Segoe UI", 9, "bold"), cursor="hand2",
    )


class MonitorLauncher:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.api_process: subprocess.Popen | None = None

        root.title("Ecuador Public Spending Monitor")
        root.geometry("980x640")
        root.minsize(820, 520)
        root.configure(bg=BG)

        self._build_header()
        self._build_data_row()
        self._build_sercop_form()
        self._build_api_row()
        self._build_log()

        self.log("Panel listo.")
        self.log(f"Python: {PYTHON}")
        self.log("Sugerencia: carga 'Demo' primero para verificar la base, luego usa SERCOP para datos reales.")

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_header(self) -> None:
        h = Frame(self.root, bg=DARK, padx=22, pady=14)
        h.pack(fill="x")
        Label(h, text="Ecuador Public Spending Monitor",
              bg=DARK, fg="#ffffff", font=("Segoe UI", 18, "bold")).pack(anchor=W)
        Label(h, text="Plataforma de vigilancia de gasto publico — API SERCOP OCDS, sin IA, trazable.",
              bg=DARK, fg="#cbd5e1", font=("Segoe UI", 9)).pack(anchor=W, pady=(4, 0))

    def _build_data_row(self) -> None:
        s = Frame(self.root, bg=BG, padx=22, pady=10)
        s.pack(fill="x")
        Label(s, text="Datos rapidos", bg=BG, fg="#111827",
              font=("Segoe UI", 10, "bold")).pack(anchor=W, pady=(0, 6))
        row = Frame(s, bg=BG)
        row.pack(anchor=W)
        _btn(row, "Cargar demo", self.load_demo_data,
             bg="#475569", active_bg="#334155").pack(side=LEFT, padx=(0, 8))
        _btn(row, "SERCOP basico  (2020 · agua · 10)",
             self.load_sercop_sample).pack(side=LEFT, padx=(0, 8))
        _btn(row, "Exportar XLSX",
             self.export_xlsx,
             bg="#7c3aed", active_bg="#6d28d9").pack(side=LEFT, padx=(0, 8))

    def _build_sercop_form(self) -> None:
        s = Frame(self.root, bg=BG, padx=22, pady=4)
        s.pack(fill="x")
        Label(s, text="SERCOP ampliado", bg=BG, fg="#111827",
              font=("Segoe UI", 10, "bold")).pack(anchor=W, pady=(4, 6))

        form = Frame(s, bg=BG)
        form.pack(anchor=W)

        self._v_years = StringVar(value="2020 2021 2022")
        self._v_terms = StringVar(value="agua salud vialidad")
        self._v_limit = StringVar(value="50")
        self._v_pages = StringVar(value="")

        for label, var, width in [
            ("Años  (ej: 2020 2021)", self._v_years, 20),
            ("Términos  (ej: agua salud)", self._v_terms, 22),
            ("Límite  (-1 = todos)", self._v_limit, 8),
            ("Máx páginas  (vacío = todas)", self._v_pages, 8),
        ]:
            col = Frame(form, bg=BG)
            col.pack(side=LEFT, padx=(0, 14))
            Label(col, text=label, bg=BG, fg="#374151", font=("Segoe UI", 8)).pack(anchor=W)
            Entry(col, textvariable=var, width=width, font=("Segoe UI", 9),
                  relief="solid", bd=1).pack(anchor=W, pady=(2, 0))

        btn_row = Frame(s, bg=BG)
        btn_row.pack(anchor=W, pady=(8, 0))
        _btn(btn_row, "Buscar  (sin montos)",
             self.load_sercop_expanded).pack(side=LEFT, padx=(0, 8))
        _btn(btn_row, "Buscar + montos reales  (mas lento)",
             self.load_sercop_with_detail,
             bg="#16a34a", active_bg="#15803d").pack(side=LEFT, padx=(0, 8))

        Label(s,
              text="'+ montos reales' llama record?ocid=... por contrato (tarda mas). Usa limite pequeno al probar.",
              bg=BG, fg="#6b7280", font=("Segoe UI", 8)).pack(anchor=W, pady=(4, 0))

    def _build_api_row(self) -> None:
        s = Frame(self.root, bg=BG, padx=22, pady=10)
        s.pack(fill="x")
        Label(s, text="API local", bg=BG, fg="#111827",
              font=("Segoe UI", 10, "bold")).pack(anchor=W, pady=(0, 6))
        row = Frame(s, bg=BG)
        row.pack(anchor=W)
        _btn(row, "Iniciar API", self.start_api,
             bg="#16a34a", active_bg="#15803d").pack(side=LEFT, padx=(0, 6))
        _btn(row, "Detener API", self.stop_api,
             bg="#dc2626", active_bg="#b91c1c").pack(side=LEFT, padx=(0, 18))
        for label, path in [
            ("Contratos", "/contracts"),
            ("Solo reales", "/contracts?include_demo=false"),
            ("Anomalias", "/anomalies"),
            ("Health", "/health"),
        ]:
            _btn(row, label, lambda p=path: self.open_url(f"{API_URL}{p}"),
                 bg="#475569", active_bg="#334155").pack(side=LEFT, padx=(0, 6))

    def _build_log(self) -> None:
        c = Frame(self.root, bg=BG, padx=22, pady=8)
        c.pack(fill=BOTH, expand=True)
        Label(c, text="Actividad", bg=BG, fg="#111827",
              font=("Segoe UI", 10, "bold")).pack(anchor=W, pady=(0, 6))
        frame = Frame(c, bg="#111827")
        frame.pack(fill=BOTH, expand=True)
        sb = Scrollbar(frame)
        sb.pack(side=RIGHT, fill=Y)
        self.log_area = Text(
            frame, bg="#111827", fg="#e5e7eb", insertbackground="#e5e7eb",
            relief="flat", padx=12, pady=12, font=("Consolas", 9),
            yscrollcommand=sb.set,
        )
        self.log_area.pack(side=LEFT, fill=BOTH, expand=True)
        sb.config(command=self.log_area.yview)

    # ------------------------------------------------------------------
    # Acciones
    # ------------------------------------------------------------------
    def log(self, message: str) -> None:
        self.log_area.insert(END, f"{message}\n")
        self.log_area.see(END)

    def run_command(self, args: list[str], label: str) -> None:
        def worker() -> None:
            self.root.after(0, self.log, f"\n> {label}")
            proc = subprocess.Popen(
                args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                self.root.after(0, self.log, line.rstrip())
            self.root.after(0, self.log, f"Finalizo con codigo {proc.wait()}.")
        threading.Thread(target=worker, daemon=True).start()

    def load_demo_data(self) -> None:
        self.run_command([PYTHON, "scripts/test_single_institution.py"], "Carga demo")

    def load_sercop_sample(self) -> None:
        self.run_command(
            [PYTHON, "scripts/ingest_sercop_search.py",
             "--year", "2020", "--search", "agua", "--limit", "10"],
            "SERCOP basico",
        )

    def export_xlsx(self) -> None:
        self.run_command(
            [PYTHON, "scripts/export_xlsx.py"],
            "Exportar XLSX",
        )

    def _sercop_args(self, detail: bool = False) -> list[str]:
        args = [PYTHON, "scripts/ingest_sercop_search.py"]
        years = self._v_years.get().split()
        if years:
            args += ["--year"] + years
        terms = self._v_terms.get().split()
        if terms:
            args += ["--search"] + terms
        limit = self._v_limit.get().strip()
        if limit:
            args += ["--limit", limit]
        pages = self._v_pages.get().strip()
        if pages:
            args += ["--max-pages", pages]
        if detail:
            args.append("--detail")
        return args

    def load_sercop_expanded(self) -> None:
        self.run_command(
            self._sercop_args(),
            f"SERCOP ampliado | años={self._v_years.get()} | términos={self._v_terms.get()}",
        )

    def load_sercop_with_detail(self) -> None:
        self.run_command(
            self._sercop_args(detail=True),
            f"SERCOP + montos | años={self._v_years.get()} | términos={self._v_terms.get()}",
        )

    def start_api(self) -> None:
        if self.api_process and self.api_process.poll() is None:
            self.log("La API ya esta ejecutandose.")
            return
        self.log(f"> Iniciando API en {API_URL}")
        self.api_process = subprocess.Popen(
            [PYTHON, "-m", "uvicorn", "app.main:app", "--reload"],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        threading.Thread(target=self._stream_api_logs, daemon=True).start()

    def _stream_api_logs(self) -> None:
        if not self.api_process or not self.api_process.stdout:
            return
        for line in self.api_process.stdout:
            self.root.after(0, self.log, line.rstrip())

    def stop_api(self) -> None:
        if not self.api_process or self.api_process.poll() is not None:
            self.log("No hay una API activa para detener.")
            return
        self.api_process.terminate()
        self.log("API detenida.")

    def open_url(self, url: str) -> None:
        self.log(f"Abriendo {url}")
        webbrowser.open(url)

    def close(self) -> None:
        self.stop_api()
        self.root.destroy()


def main() -> None:
    root = Tk()
    launcher = MonitorLauncher(root)
    root.protocol("WM_DELETE_WINDOW", launcher.close)
    root.mainloop()


if __name__ == "__main__":
    main()
