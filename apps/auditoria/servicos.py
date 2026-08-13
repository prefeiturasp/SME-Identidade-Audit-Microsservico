"""Regras de escrita, consulta e retenção dos eventos de auditoria."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone

from apps.auditoria.models import EventoAuditoria

logger = logging.getLogger(__name__)


def _para_datetime(timestamp_ms: int) -> dt.datetime:
    """Converta o instante em milissegundos para datetime com fuso.

    Args:
        timestamp_ms: Instante em milissegundos desde a época Unix,
            como o Keycloak o representa.

    Returns:
        O instante equivalente em UTC.
    """
    return dt.datetime.fromtimestamp(timestamp_ms / 1000, tz=dt.UTC)


def _para_evento(dados: dict[str, Any]) -> EventoAuditoria:
    """Monta a linha de auditoria a partir do payload já normalizado.

    Args:
        dados: Evento normalizado, com ``evento_id_origem`` já
            calculado.

    Returns:
        Instância ainda não persistida de ``EventoAuditoria``.
    """
    return EventoAuditoria(
        evento_id_origem=dados["evento_id_origem"],
        tipo_evento=dados["tipo_evento"],
        usuario_id=dados.get("usuario_id") or None,
        realm=dados["realm"],
        client_id=dados.get("client_id") or None,
        ip_origem=dados.get("ip_origem") or None,
        timestamp_evento=_para_datetime(dados["timestamp_evento"]),
        detalhes=dados.get("detalhes") or {},
    )


def persistir_lote(eventos: list[dict[str, Any]]) -> dict[str, int]:
    """Grava um lote de eventos, descartando os que já existem.

    A escrita é feita em lote, e não linha a linha, porque o volume
    esperado em pico de ano letivo torna o custo por INSERT
    individual proibitivo. Conflitos de chave são ignorados no próprio
    banco: quando a leitura antecipada e o ciclo agendado se
    sobrepõem, ambos trazem o mesmo evento, e é a restrição de
    unicidade que decide qual escrita vale — sem coordenação entre os
    processos.

    Args:
        eventos: Eventos já normalizados, cada um com
            ``evento_id_origem``.

    Returns:
        Contagem de eventos recebidos e de linhas efetivamente
        criadas — a diferença entre as duas são as duplicatas
        descartadas.
    """
    if not eventos:
        return {"recebidos": 0, "gravados": 0}

    objetos = [_para_evento(dados) for dados in eventos]

    chaves = {dados["evento_id_origem"] for dados in eventos}
    ja_existentes = set(
        EventoAuditoria.objects.filter(
            evento_id_origem__in=chaves
        ).values_list("evento_id_origem", flat=True)
    )

    EventoAuditoria.objects.bulk_create(
        objetos,
        batch_size=settings.AUDITORIA_TAMANHO_LOTE,
        ignore_conflicts=True,
    )

    gravados = len(chaves - ja_existentes)

    logger.info(
        "Lote de auditoria processado: %s recebidos, %s gravados",
        len(eventos),
        gravados,
    )

    return {"recebidos": len(eventos), "gravados": gravados}


def consultar_eventos(
    usuario_id: str | None = None,
    client_id: str | None = None,
    tipo_evento: str | None = None,
    data_inicio: dt.datetime | None = None,
    data_fim: dt.datetime | None = None,
) -> QuerySet[EventoAuditoria]:
    """Filtra os eventos de auditoria pelos critérios informados.

    Cada combinação de filtro aplicada aqui casa com um dos índices
    compostos do modelo (usuário, sistema ou tipo, sempre com
    período): a apuração típica de auditoria é sempre "eventos de X,
    num período", nunca uma consulta sem nenhum recorte por tempo
    isolado.

    Args:
        usuario_id: Filtra pelo identificador do usuário no Keycloak.
        client_id: Filtra pelo sistema de origem do evento.
        tipo_evento: Filtra pelo tipo de evento (``LOGIN``, ``LOGOUT``
            etc.).
        data_inicio: Data/hora mínima do evento, inclusive.
        data_fim: Data/hora máxima do evento, inclusive.

    Returns:
        Queryset ordenado do mais recente para o mais antigo, ainda
        não avaliado — a paginação é responsabilidade de quem chama.
    """
    eventos = EventoAuditoria.objects.all()

    if usuario_id:
        eventos = eventos.filter(usuario_id=usuario_id)
    if client_id:
        eventos = eventos.filter(client_id=client_id)
    if tipo_evento:
        eventos = eventos.filter(tipo_evento=tipo_evento)
    if data_inicio:
        eventos = eventos.filter(timestamp_evento__gte=data_inicio)
    if data_fim:
        eventos = eventos.filter(timestamp_evento__lte=data_fim)

    return eventos.order_by("-timestamp_evento")


def expurgar_eventos_antigos(
    forcar: bool = False,
) -> dict[str, Any]:
    """Remove eventos fora do período de retenção configurado.

    Desligado por padrão: o período mínimo de guarda ainda depende de
    definição jurídica, e uma remoção feita antes dessa definição não
    tem como ser desfeita. ``forcar`` existe para exercitar a rotina
    em teste sem depender da configuração do ambiente.

    Args:
        forcar: Executa a remoção mesmo com a rotina desligada na
            configuração.

    Returns:
        Situação da execução (``executado`` ou ``desativado``), o
        corte de data aplicado e a quantidade de linhas removidas.
    """
    if not (forcar or settings.AUDITORIA_EXPURGO_ATIVO):
        logger.info("Expurgo de auditoria não executado: rotina desligada")
        return {"situacao": "desativado", "removidos": 0}

    corte = timezone.now() - dt.timedelta(
        days=settings.AUDITORIA_RETENCAO_DIAS
    )

    total = 0
    while True:
        ids = list(
            EventoAuditoria.objects.filter(
                timestamp_evento__lt=corte
            ).values_list("id", flat=True)[
                : settings.AUDITORIA_EXPURGO_TAMANHO_LOTE
            ]
        )
        if not ids:
            break

        removidos, _ = EventoAuditoria.objects.filter(id__in=ids).delete()
        total += removidos

    logger.info(
        "Expurgo de auditoria concluído: %s removidos anteriores a %s",
        total,
        corte.isoformat(),
    )

    return {
        "situacao": "executado",
        "corte": corte.isoformat(),
        "removidos": total,
    }
