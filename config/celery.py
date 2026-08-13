"""Configuração Celery do SME-Identidade-Audit-Microsservico."""

from __future__ import annotations

import os
from typing import Any

from celery import Celery
from celery.schedules import crontab
from django.conf import settings

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("identidade_auditoria")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# O ciclo agendado é o que garante cobertura completa: atividade fora
# do alcance do Gateway (Admin Console, integrações máquina a máquina,
# OIDC direto) só chega por aqui. O aviso sob demanda apenas antecipa
# a leitura do caminho mais usado, nunca a substitui.
app.conf.beat_schedule = {
    "auditoria-consulta-periodica": {
        "task": "task_auditoria_consultar_eventos",
        "schedule": crontab(
            minute=f"*/{settings.AUDITORIA_INTERVALO_POLL_MINUTOS}"
        ),
        "options": {"queue": "auditoria_captura_usuario"},
    },
    # Canal separado do de eventos de usuário: cobre ações
    # administrativas (criação de usuário, entre outras), que só
    # aparecem aqui, nunca no aviso disparado pelo Gateway — a
    # plataforma cria conta via Admin API, não via login/gatilho.
    "auditoria-consulta-admin-events-periodica": {
        "task": "task_auditoria_consultar_admin_events",
        "schedule": crontab(
            minute=f"*/{settings.AUDITORIA_INTERVALO_POLL_MINUTOS}"
        ),
        "options": {"queue": "auditoria_captura_admin"},
    },
    # Agendado mesmo com o expurgo desligado: a task verifica a
    # própria autorização a cada execução, então ligar a remoção não
    # exige mexer no agendamento.
    "auditoria-expurgo-diario": {
        "task": "task_auditoria_expurgar_eventos",
        "schedule": crontab(hour=3, minute=30),
        "options": {"queue": "auditoria_persistencia"},
    },
}


@app.task(bind=True, ignore_result=True)
def tarefa_debug(self: Any) -> None:
    """Tarefa de debug para verificar o worker Celery."""
    print(f"Requisição: {self.request!r}")


app.finalize()
