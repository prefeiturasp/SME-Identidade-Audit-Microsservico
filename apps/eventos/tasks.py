"""Tarefas de captura de eventos no Keycloak."""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from django.conf import settings

from apps.eventos.clientes.keycloak_admin import KeycloakAdminError
from apps.eventos.servicos import capturar_admin_events, capturar_eventos

logger = logging.getLogger(__name__)


@shared_task(name="task_auditoria_consultar_eventos", ignore_result=True)
def task_auditoria_consultar_eventos(
    realm: str | None = None,
) -> dict[str, Any]:
    """Lê os eventos de usuário novos de um realm e os entrega para escrita.

    A mesma tarefa atende o ciclo agendado e a leitura antecipada
    disparada por um aviso: em ambos os casos o dado vem do Keycloak,
    então não há dois formatos de evento a reconciliar — só a mesma
    leitura possivelmente repetida, que a restrição de unicidade
    resolve na escrita.

    Args:
        realm: Realm a capturar. Sem valor, usa o realm configurado.

    Returns:
        Quantos eventos foram lidos, quantos passaram do corte e qual
        marcador ficou registrado. Em caso de falha na consulta,
        devolve a situação de erro sem avançar o marcador.
    """
    alvo = realm or settings.KEYCLOAK_REALM

    try:
        return capturar_eventos(alvo)
    except KeycloakAdminError as exc:
        # Sem leitura confirmada não há como saber até onde avançar; o
        # marcador fica onde está e a execução seguinte cobre a mesma
        # janela.
        logger.warning("Captura do realm %s não concluída: %s", alvo, exc)
        return {"situacao": "erro", "realm": alvo, "detalhe": str(exc)}


@shared_task(name="task_auditoria_consultar_admin_events", ignore_result=True)
def task_auditoria_consultar_admin_events(
    realm: str | None = None,
) -> dict[str, Any]:
    """Lê os admin events novos de um realm e os entrega para escrita.

    Canal separado de ``task_auditoria_consultar_eventos`` — cobre
    ações administrativas (criação de usuário, entre outras), que não
    aparecem no canal de eventos de usuário.

    Args:
        realm: Realm a capturar. Sem valor, usa o realm configurado.

    Returns:
        Quantos eventos foram lidos, quantos passaram do corte e qual
        marcador ficou registrado. Em caso de falha na consulta,
        devolve a situação de erro sem avançar o marcador.
    """
    alvo = realm or settings.KEYCLOAK_REALM

    try:
        return capturar_admin_events(alvo)
    except KeycloakAdminError as exc:
        logger.warning(
            "Captura de admin events do realm %s não concluída: %s",
            alvo,
            exc,
        )
        return {"situacao": "erro", "realm": alvo, "detalhe": str(exc)}
