"""Regras de escrita, consulta e retenção dos eventos de auditoria."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from django.conf import settings
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.auditoria.models import (
    EventoAuditoria,
    IdentificadorUsuarioAuditoria,
)

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


def _normalizar_valor_identificador(
    tipo: str,
    valor: str | None,
) -> str | None:
    """Normaliza um identificador antes de persistir ou consultar.

    Args:
        tipo: Tipo do identificador (EMAIL, CPF ou RF).
        valor: Valor recebido.

    Returns:
        Valor normalizado ou ``None`` quando vazio.
    """
    if not valor:
        return None

    if tipo == IdentificadorUsuarioAuditoria.Tipo.EMAIL:
        return valor.casefold()

    if tipo == IdentificadorUsuarioAuditoria.Tipo.CPF:
        return "".join(caractere for caractere in valor if caractere.isdigit())

    if tipo == IdentificadorUsuarioAuditoria.Tipo.RF:
        return valor

    return valor


def registrar_identificadores_usuario(
    realm: str,
    identificadores: dict[str, str | None],
) -> None:
    """Registra os identificadores conhecidos de um usuário.

    Os identificadores são históricos. Quando e-mail, CPF ou RF
    mudarem, um novo registro será criado para o mesmo ``usuario_id``
    sem remover os valores anteriores.

    A restrição de unicidade do modelo, combinada com
    ``ignore_conflicts=True``, impede a criação de registros
    duplicados quando o mesmo identificador for observado novamente.

    Args:
        realm: Realm ao qual o usuário pertence.
        identificadores: Dicionário contendo ``usuario_id`` e,
            opcionalmente, ``email``, ``cpf`` e ``rf``.
    """
    usuario_id = identificadores.get("usuario_id")

    if not usuario_id:
        return

    valores = [
        (
            IdentificadorUsuarioAuditoria.Tipo.EMAIL,
            identificadores.get("email"),
        ),
        (
            IdentificadorUsuarioAuditoria.Tipo.CPF,
            identificadores.get("cpf"),
        ),
        (
            IdentificadorUsuarioAuditoria.Tipo.RF,
            identificadores.get("rf"),
        ),
    ]

    objetos = []

    for tipo, valor in valores:
        valor_normalizado = _normalizar_valor_identificador(
            tipo,
            valor,
        )

        if not valor_normalizado:
            continue

        objetos.append(
            IdentificadorUsuarioAuditoria(
                realm=realm,
                usuario_id=usuario_id,
                tipo=tipo,
                valor=valor_normalizado,
            )
        )

    if not objetos:
        return

    IdentificadorUsuarioAuditoria.objects.bulk_create(
        objetos,
        ignore_conflicts=True,
    )


def _resolver_identificador_usuario(
    identificador: str,
) -> list[tuple[str, str]]:
    """Resolve e-mail, CPF ou RF para realm e usuario_id.

    A consulta considera todo o histórico armazenado. Dessa forma,
    um e-mail, CPF ou RF antigo continua levando ao mesmo usuário e,
    consequentemente, aos eventos associados ao seu ``usuario_id``.

    Args:
        identificador: E-mail, CPF ou RF informado na consulta.

    Returns:
        Lista de pares ``(realm, usuario_id)`` associados ao valor.
    """
    valor = identificador.strip()

    if not valor:
        return []

    email = _normalizar_valor_identificador(
        IdentificadorUsuarioAuditoria.Tipo.EMAIL,
        valor,
    )

    cpf = _normalizar_valor_identificador(
        IdentificadorUsuarioAuditoria.Tipo.CPF,
        valor,
    )

    rf = _normalizar_valor_identificador(
        IdentificadorUsuarioAuditoria.Tipo.RF,
        valor,
    )

    filtro = Q()

    if email:
        filtro |= Q(
            tipo=IdentificadorUsuarioAuditoria.Tipo.EMAIL,
            valor=email,
        )

    if cpf and len(cpf) == 11:
        filtro |= Q(
            tipo=IdentificadorUsuarioAuditoria.Tipo.CPF,
            valor=cpf,
        )

    if rf:
        filtro |= Q(
            tipo=IdentificadorUsuarioAuditoria.Tipo.RF,
            valor=rf,
        )

    return list(
        IdentificadorUsuarioAuditoria.objects.filter(filtro)
        .values_list(
            "realm",
            "usuario_id",
        )
        .distinct()
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

    ``usuario_id`` funciona como identificador genérico do usuário.
    Pode receber:

    - ID do usuário no Keycloak;
    - e-mail atual ou histórico;
    - CPF atual ou histórico;
    - RF atual ou histórico.

    Quando o valor corresponde a um identificador alternativo, ele é
    resolvido para o ``usuario_id`` armazenado e todos os eventos
    daquele usuário são retornados.

    Args:
        usuario_id: ID do Keycloak, e-mail, CPF ou RF do usuário.
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
        valor = usuario_id.strip()

        filtro_usuario = Q(usuario_id=valor)

        identificadores = _resolver_identificador_usuario(valor)

        for realm, usuario_id_resolvido in identificadores:
            filtro_usuario |= Q(
                realm=realm,
                usuario_id=usuario_id_resolvido,
            )

        eventos = eventos.filter(filtro_usuario)

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
