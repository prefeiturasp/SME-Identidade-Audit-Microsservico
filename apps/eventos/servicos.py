"""Leitura dos eventos do Keycloak e avanço do marcador de captura."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.db import transaction

from apps.auditoria.models import CheckpointCaptura
from apps.auditoria.tasks import task_auditoria_persistir_lote
from apps.eventos.clientes import keycloak_admin
from apps.eventos.normalizacao import normalizar_admin_event, normalizar_evento

logger = logging.getLogger(__name__)


def obter_checkpoint(
    realm: str, canal: str = CheckpointCaptura.CANAL_USUARIO
) -> int:
    """Devolve o instante até onde a captura do realm/canal já avançou.

    Args:
        realm: Realm do Keycloak.
        canal: Qual dos dois fluxos de evento — usuário ou admin. Os
            timestamps dos dois canais são independentes, então cada
            um precisa do próprio marcador.

    Returns:
        O instante em milissegundos, ou zero se a combinação
        realm/canal ainda não foi capturada nenhuma vez.
    """
    checkpoint = CheckpointCaptura.objects.filter(
        realm=realm, canal=canal
    ).first()
    return checkpoint.ultimo_timestamp if checkpoint else 0


def _avancar_checkpoint(
    realm: str, timestamp_ms: int, canal: str = CheckpointCaptura.CANAL_USUARIO
) -> None:
    """Move o marcador do realm/canal para frente, nunca para trás.

    Duas leituras podem terminar fora de ordem — a antecipada e a do
    ciclo agendado se sobrepõem por natureza. Recuar o marcador nesse
    caso faria a leitura seguinte reprocessar uma janela já capturada,
    então só um valor maior é aceito.

    Args:
        realm: Realm do Keycloak.
        timestamp_ms: Instante do evento mais recente já entregue
            para escrita.
        canal: Qual dos dois fluxos de evento — usuário ou admin.
    """
    with transaction.atomic():
        registros = CheckpointCaptura.objects.select_for_update()
        checkpoint, _ = registros.get_or_create(
            realm=realm,
            canal=canal,
            defaults={"ultimo_timestamp": timestamp_ms},
        )
        if timestamp_ms > checkpoint.ultimo_timestamp:
            checkpoint.ultimo_timestamp = timestamp_ms
            checkpoint.save(update_fields=["ultimo_timestamp"])


def _capturar(
    realm: str,
    canal: str,
    consultar: Callable[..., list[dict[str, Any]]],
    normalizar: Callable[[dict[str, Any], str], dict[str, Any]],
) -> dict[str, Any]:
    """Lê os eventos novos de um canal e os entrega para escrita.

    Lógica compartilhada entre ``capturar_eventos`` e
    ``capturar_admin_events`` — os dois canais seguem exatamente o
    mesmo fluxo (checkpoint → consulta → corte → persistência →
    avanço), diferindo só na função de consulta e de normalização.

    O corte por instante é estrito (``time > checkpoint``): o evento
    exatamente no marcador já foi capturado na leitura anterior, e
    incluí-lo de novo geraria trabalho garantido de duplicata a cada
    ciclo. Como a Admin API só filtra por dia, o corte fino é aplicado
    aqui, sobre o que ela devolveu.

    O marcador só avança depois que os eventos foram entregues para
    escrita. Se a entrega falhar, ele fica onde está e a leitura
    seguinte cobre a mesma janela — melhor repetir uma leitura, que a
    restrição de unicidade resolve, do que perder um evento.

    Args:
        realm: Realm do Keycloak a capturar.
        canal: Qual dos dois fluxos de evento — usuário ou admin.
        consultar: Função de consulta à Admin API do canal.
        normalizar: Função de normalização do canal.

    Returns:
        Quantos eventos foram lidos, quantos passaram do corte e qual
        marcador ficou registrado ao final.
    """
    checkpoint = obter_checkpoint(realm, canal=canal)

    brutos = consultar(
        realm=realm,
        desde_ms=checkpoint or None,
        limite=settings.AUDITORIA_LIMITE_CONSULTA,
    )

    novos = [
        normalizar(evento, realm)
        for evento in brutos
        if int(evento.get("time") or 0) > checkpoint
    ]

    if not novos:
        logger.info(
            "Captura do realm %s (%s) sem eventos novos (%s lidos)",
            realm,
            canal,
            len(brutos),
        )
        return {
            "lidos": len(brutos),
            "novos": 0,
            "checkpoint": checkpoint,
        }

    task_auditoria_persistir_lote.delay(novos)

    maior = max(evento["timestamp_evento"] for evento in novos)
    _avancar_checkpoint(realm, maior, canal=canal)

    logger.info(
        "Captura do realm %s (%s): %s lidos, %s novos, marcador em %s",
        realm,
        canal,
        len(brutos),
        len(novos),
        maior,
    )

    return {
        "lidos": len(brutos),
        "novos": len(novos),
        "checkpoint": maior,
    }


def capturar_eventos(realm: str) -> dict[str, Any]:
    """Lê os eventos de usuário novos do realm (login/logout/falha).

    Args:
        realm: Realm do Keycloak a capturar.

    Returns:
        Quantos eventos foram lidos, quantos passaram do corte e qual
        marcador ficou registrado ao final.
    """
    return _capturar(
        realm,
        CheckpointCaptura.CANAL_USUARIO,
        keycloak_admin.consultar_eventos,
        normalizar_evento,
    )


def capturar_admin_events(realm: str) -> dict[str, Any]:
    """Lê os admin events novos do realm (criação/edição de usuário etc.).

    Args:
        realm: Realm do Keycloak a capturar.

    Returns:
        Quantos eventos foram lidos, quantos passaram do corte e qual
        marcador ficou registrado ao final.
    """
    return _capturar(
        realm,
        CheckpointCaptura.CANAL_ADMIN,
        keycloak_admin.consultar_admin_events,
        normalizar_admin_event,
    )
