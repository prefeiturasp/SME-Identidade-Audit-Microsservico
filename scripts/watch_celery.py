"""Inicia o Celery worker com auto-restart em dev.

Observa ``/app/apps`` e ``/app/config`` e reinicia o worker sempre que um
arquivo ``.py`` é criado ou modificado. Usa ``PollingObserver`` (watchdog)
em vez de ``watchmedo auto-restart``/inotify porque o volume montado do
Docker Desktop (macOS/Windows) não propaga eventos inotify do host.
"""

import os
import subprocess
import sys
import time

from watchdog.events import FileSystemEventHandler  # type: ignore
from watchdog.observers.polling import PollingObserver  # type: ignore

# Mesmo prefixo usado na configuração das filas — isola este worker
# das filas reais quando aponta pra um broker compartilhado (ex.:
# KeyDB de QA), sem afetar o comportamento padrão (prefixo vazio).
_PREFIXO_FILA = os.getenv("AUDITORIA_PREFIXO_FILA", "")

# AUDITORIA_WORKER_FILAS permite subir workers dedicados por fila
# (réplica local dos 3 deployments separados do Rancher: captura de
# usuário, captura de admin e persistência) — sem isso, a escrita em
# lote no Postgres bloqueia atrás dela a captura no mesmo processo, e
# os dois canais de captura competem entre si por I/O do Keycloak.
_NOMES_FILA = os.getenv(
    "AUDITORIA_WORKER_FILAS",
    "auditoria_captura_usuario,auditoria_captura_admin,"
    "auditoria_persistencia",
).split(",")

_CELERY_CMD = [
    "celery",
    "-A",
    "config.celery:app",
    "worker",
    "--loglevel=INFO",
    "--concurrency=1",
    "-Q",
    ",".join(f"{_PREFIXO_FILA}{nome}" for nome in _NOMES_FILA),
]

_WATCH_DIRS = ["/app/apps", "/app/config"]


class _RestartHandler(FileSystemEventHandler):
    def __init__(self) -> None:
        self._proc = subprocess.Popen(_CELERY_CMD)

    def _restart(self) -> None:
        print(
            "[watch_celery] Alteração detectada — reiniciando worker...",
            flush=True,
        )
        self._proc.terminate()
        self._proc.wait()
        self._proc = subprocess.Popen(_CELERY_CMD)

    def _trigger_restart_if_python_file(self, event: object) -> None:
        """Reinicia o worker se o arquivo alterado/criado for .py."""
        if not getattr(event, "is_directory", True) and str(
            getattr(event, "src_path", "")
        ).endswith(".py"):
            self._restart()

    def on_modified(self, event: object) -> None:  # type: ignore[override]
        self._trigger_restart_if_python_file(event)

    def on_created(self, event: object) -> None:  # type: ignore[override]
        self._trigger_restart_if_python_file(event)


def main() -> None:
    """Inicia o observer de polling e mantém o worker Celery em execução."""
    handler = _RestartHandler()
    observer = PollingObserver()
    for d in _WATCH_DIRS:
        observer.schedule(handler, d, recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(1)
            rc = handler._proc.poll()
            if rc is not None:
                observer.stop()
                sys.exit(rc)
    except KeyboardInterrupt:
        observer.stop()
        handler._proc.terminate()
        handler._proc.wait()
    observer.join()


if __name__ == "__main__":
    main()
