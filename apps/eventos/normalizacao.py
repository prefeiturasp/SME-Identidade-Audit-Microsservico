"""Tradução do evento bruto do Keycloak para o formato de auditoria."""

from __future__ import annotations

import contextlib
import hashlib
import json
from typing import Any

# Tamanho da chave de deduplicação em caracteres hexadecimais. O hash
# completo de SHA-256 tem 64; truncar em 32 mantém a colisão fora de
# qualquer ordem de grandeza plausível de eventos e ainda cabe no
# campo indexado.
_TAMANHO_CHAVE = 32


def calcular_evento_id_origem(evento: dict[str, Any]) -> str:
    """Deriva a chave de deduplicação do evento.

    A Admin REST API não expõe um identificador único e estável do
    evento de forma padronizada entre versões do Keycloak, então a
    chave é derivada dos campos que, juntos, identificam a ocorrência:
    realm, tipo, usuário, instante e sessão. Campos ausentes entram
    como string vazia, para que o mesmo evento sempre produza a mesma
    chave, independentemente de qual leitura o trouxe.

    Assumido enquanto não há como inspecionar a resposta de um
    Keycloak real: se a versão em uso expuser um identificador nativo
    confiável, ele é preferível a este hash.

    Args:
        evento: Evento bruto, no formato devolvido pelo Keycloak.

    Returns:
        A chave de deduplicação, em hexadecimal.
    """
    detalhes = evento.get("details") or {}

    componentes = [
        str(evento.get("realmId") or ""),
        str(evento.get("type") or ""),
        str(evento.get("userId") or ""),
        str(evento.get("time") or ""),
        str(evento.get("sessionId") or detalhes.get("sessionId") or ""),
    ]

    bruto = "|".join(componentes).encode("utf-8")

    return hashlib.sha256(bruto).hexdigest()[:_TAMANHO_CHAVE]


def normalizar_evento(
    evento: dict[str, Any],
    realm_padrao: str,
) -> dict[str, Any]:
    """Converta o evento bruto do Keycloak no formato de persistência.

    O payload bruto é preservado por inteiro em ``detalhes``: os
    campos promovidos a colunas atendem as consultas previstas, e o
    que sobra pode ser justamente o que uma apuração futura precisa.

    Args:
        evento: Evento bruto, no formato devolvido pelo Keycloak.
        realm_padrao: Realm a assumir quando o evento não traz
            ``realmId`` — algumas versões omitem o campo na resposta
            da Admin API, já que a consulta é feita por realm.

    Returns:
        O evento normalizado, com a chave de deduplicação calculada.
    """
    realm = str(evento.get("realmId") or realm_padrao)

    # A chave é sempre derivada do payload de origem, com o realm já
    # resolvido — assim, duas leituras do mesmo evento coincidem
    # mesmo quando uma delas veio sem o campo preenchido.
    evento_para_chave = {**evento, "realmId": realm}

    return {
        "evento_id_origem": calcular_evento_id_origem(evento_para_chave),
        "tipo_evento": str(evento.get("type") or ""),
        "usuario_id": evento.get("userId") or None,
        "realm": realm,
        "client_id": evento.get("clientId") or None,
        "ip_origem": evento.get("ipAddress") or None,
        "timestamp_evento": int(evento.get("time") or 0),
        "detalhes": evento,
    }


def calcular_admin_event_id_origem(evento: dict[str, Any]) -> str:
    """Deriva a chave de deduplicação de um admin event.

    O admin event real do Keycloak traz um ``id`` próprio — diferente
    do canal de eventos de usuário, onde a ausência de identificador
    nativo era a premissa (não confirmada) que levou ao hash composto.
    Aqui, o ``id`` é usado diretamente quando presente; o hash fica
    como retaguarda, composto por ``operationType``/``resourceType``/
    ``resourcePath``/``time`` — os campos que juntos identificam a
    operação administrativa.

    Args:
        evento: Admin event bruto, no formato devolvido pelo Keycloak.

    Returns:
        A chave de deduplicação, em hexadecimal.
    """
    id_nativo = evento.get("id")
    if id_nativo:
        return str(id_nativo)

    componentes = [
        str(evento.get("realmId") or ""),
        str(evento.get("operationType") or ""),
        str(evento.get("resourceType") or ""),
        str(evento.get("resourcePath") or ""),
        str(evento.get("time") or ""),
    ]

    bruto = "|".join(componentes).encode("utf-8")

    return hashlib.sha256(bruto).hexdigest()[:_TAMANHO_CHAVE]


def normalizar_admin_event(
    evento: dict[str, Any],
    realm_padrao: str,
) -> dict[str, Any]:
    """Converta o admin event bruto do Keycloak no formato de persistência.

    O formato de admin event não é compatível com o de evento de
    usuário: não há ``type`` único, e sim ``operationType`` (o que foi
    feito: ``CREATE``/``UPDATE``/``DELETE``/``ACTION``) combinado com
    ``resourceType`` (o que foi afetado: ``USER``/``CLIENT``/``REALM``
    etc.) — ``tipo_evento`` combina os dois para ficar consultável
    junto dos tipos do outro canal, sem colidir com eles (``LOGIN`` de
    usuário nunca é igual a ``ADMIN_USER_CREATE``).

    O sujeito do evento também é diferente: em evento de usuário,
    ``userId`` é quem protagonizou a ação (quem logou); aqui, o
    usuário afetado pela operação (ex. o usuário criado) não aparece
    como um campo direto — só quem *executou* a ação
    (``authDetails.userId``). ``usuario_id`` aqui registra quem
    executou, não quem foi afetado; ``detalhes.representation`` traz o
    payload da operação para quem precisar identificar o usuário
    afetado.

    ``representation`` chega como string JSON serializada, não objeto
    aninhado — decodificada aqui para não obrigar quem consulta
    ``detalhes`` a fazer um segundo parse.

    Args:
        evento: Admin event bruto, no formato devolvido pelo Keycloak.
        realm_padrao: Realm a assumir quando o evento não traz
            ``realmId``.

    Returns:
        O evento normalizado, com a chave de deduplicação calculada.
    """
    realm = str(evento.get("realmId") or realm_padrao)
    evento_para_chave = {**evento, "realmId": realm}

    auth_details = evento.get("authDetails") or {}
    operacao = evento.get("operationType") or ""
    recurso = evento.get("resourceType") or ""
    tipo_evento = f"ADMIN_{recurso}_{operacao}".strip("_") or "ADMIN_EVENT"

    representacao = evento.get("representation")
    detalhes = dict(evento)
    if isinstance(representacao, str) and representacao:
        with contextlib.suppress(ValueError):
            detalhes["representation"] = json.loads(representacao)

    return {
        "evento_id_origem": calcular_admin_event_id_origem(evento_para_chave),
        "tipo_evento": tipo_evento,
        "usuario_id": auth_details.get("userId") or None,
        "realm": realm,
        "client_id": auth_details.get("clientId") or None,
        "ip_origem": auth_details.get("ipAddress") or None,
        "timestamp_evento": int(evento.get("time") or 0),
        "detalhes": detalhes,
    }
