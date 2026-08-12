"""Cliente de leitura de eventos na Admin REST API do Keycloak.

Isolado num módulo próprio para que a origem do dado tenha um único
ponto de entrada: o restante da captura conversa com este contrato, e
não com o formato de resposta do Keycloak.

Dois canais independentes, cada um com endpoint, formato e flag de
habilitação própria:

- Eventos de usuário (``consultar_eventos``) — login, logout, falha
  de login. Requer ``eventsEnabled`` no realm.
- Admin events (``consultar_admin_events``) — qualquer ação
  administrativa (criação/edição de usuário, client, role etc.).
  Requer ``adminEventsEnabled`` no realm; com
  ``adminEventsDetailsEnabled`` também ligado, o evento traz o
  payload da operação (``representation``).

Em ambos, o realm desligado responde lista vazia, sem erro, e a
captura fica em silêncio — validado contra Keycloak real (não é mais
suposição de documentação). A credencial é de service account com
permissão de leitura de eventos (role ``view-events`` do client
``realm-management``), autenticada por client credentials.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import httpx
from django.conf import settings


class KeycloakAdminError(Exception):
    """Falha ao consultar a Admin REST API do Keycloak."""


def _url_base() -> str:
    """Retorna a URL do servidor Keycloak sem barra final."""
    return str(settings.KEYCLOAK_URL_SERVIDOR).rstrip("/")


def obter_token_acesso() -> str:
    """Autentica a service account e devolve o token de acesso.

    Returns:
        O ``access_token`` a usar nas chamadas à Admin API.

    Raises:
        KeycloakAdminError: Se a autenticação não for concluída.
    """
    url = (
        f"{_url_base()}/realms/{settings.KEYCLOAK_REALM}"
        "/protocol/openid-connect/token"
    )

    try:
        resposta = httpx.post(
            url,
            data={
                "grant_type": "client_credentials",
                "client_id": settings.KEYCLOAK_CLIENT_ID,
                "client_secret": settings.KEYCLOAK_CLIENT_SECRET,
            },
            timeout=settings.KEYCLOAK_TIMEOUT,
            verify=settings.KEYCLOAK_VERIFICAR_SSL,
        )
    except httpx.HTTPError as exc:
        raise KeycloakAdminError(
            f"Falha ao autenticar no Keycloak: {exc}"
        ) from exc

    if resposta.status_code != 200:
        raise KeycloakAdminError(
            f"Autenticação recusada pelo Keycloak: {resposta.status_code}"
        )

    token = resposta.json().get("access_token")
    if not token:
        raise KeycloakAdminError("Resposta do Keycloak sem access_token.")

    return str(token)


def consultar_eventos(
    realm: str,
    desde_ms: int | None = None,
    limite: int | None = None,
    tipos: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Lê os eventos do realm na Admin REST API.

    O recorte por ``desde_ms`` é aplicado aqui em dia inteiro, que é a
    granularidade aceita pelo parâmetro ``dateFrom`` da Admin API. O
    corte fino, no instante exato, fica a cargo de quem consome — a
    API não oferece filtro por milissegundo.

    Args:
        realm: Realm do Keycloak a consultar.
        desde_ms: Instante mínimo, em milissegundos, usado para
            derivar a data inicial da consulta.
        limite: Máximo de eventos a trazer numa leitura.
        tipos: Tipos de evento a considerar.

    Returns:
        Os eventos brutos, no formato devolvido pelo Keycloak.

    Raises:
        KeycloakAdminError: Se a consulta não for concluída.
    """
    token = obter_token_acesso()

    parametros: dict[str, Any] = {
        "max": limite or settings.AUDITORIA_LIMITE_CONSULTA,
    }

    tipos_consultados = (
        tipos if tipos is not None else settings.AUDITORIA_TIPOS_EVENTO
    )
    if tipos_consultados:
        parametros["type"] = tipos_consultados

    if desde_ms:
        data = dt.datetime.fromtimestamp(desde_ms / 1000, tz=dt.UTC).date()
        parametros["dateFrom"] = data.isoformat()

    url = f"{_url_base()}/admin/realms/{realm}/events"

    try:
        resposta = httpx.get(
            url,
            params=parametros,
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.KEYCLOAK_TIMEOUT,
            verify=settings.KEYCLOAK_VERIFICAR_SSL,
        )
    except httpx.HTTPError as exc:
        raise KeycloakAdminError(
            f"Falha ao consultar eventos no Keycloak: {exc}"
        ) from exc

    if resposta.status_code != 200:
        raise KeycloakAdminError(
            f"Consulta de eventos recusada: {resposta.status_code}"
        )

    corpo = resposta.json()
    if not isinstance(corpo, list):
        raise KeycloakAdminError(
            "Resposta de eventos em formato inesperado (esperada uma lista)."
        )

    return corpo


def consultar_admin_events(
    realm: str,
    desde_ms: int | None = None,
    limite: int | None = None,
) -> list[dict[str, Any]]:
    """Lê os eventos administrativos do realm na Admin REST API.

    Canal separado do consultado por ``consultar_eventos``: eventos de
    usuário (login/logout/falha) e admin events (qualquer ação
    administrativa — criação/edição de usuário, client, role etc.) têm
    endpoints, formato e configuração de habilitação (``eventsEnabled``
    vs. ``adminEventsEnabled``) independentes no Keycloak. Criação de
    usuário, em particular, só aparece aqui — a plataforma cria contas
    via Admin API, não via auto-cadastro (que geraria ``REGISTER`` no
    canal de usuário).

    Args:
        realm: Realm do Keycloak a consultar.
        desde_ms: Instante mínimo, em milissegundos, usado para
            derivar a data inicial da consulta.
        limite: Máximo de eventos a trazer numa leitura.

    Returns:
        Os admin events brutos, no formato devolvido pelo Keycloak
        (``operationType``, ``resourceType``, ``resourcePath``,
        ``authDetails``, ``representation`` como string JSON).

    Raises:
        KeycloakAdminError: Se a consulta não for concluída.
    """
    token = obter_token_acesso()

    parametros: dict[str, Any] = {
        "max": limite or settings.AUDITORIA_LIMITE_CONSULTA,
    }

    if desde_ms:
        data = dt.datetime.fromtimestamp(desde_ms / 1000, tz=dt.UTC).date()
        parametros["dateFrom"] = data.isoformat()

    url = f"{_url_base()}/admin/realms/{realm}/admin-events"

    try:
        resposta = httpx.get(
            url,
            params=parametros,
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.KEYCLOAK_TIMEOUT,
            verify=settings.KEYCLOAK_VERIFICAR_SSL,
        )
    except httpx.HTTPError as exc:
        raise KeycloakAdminError(
            f"Falha ao consultar admin events no Keycloak: {exc}"
        ) from exc

    if resposta.status_code != 200:
        raise KeycloakAdminError(
            f"Consulta de admin events recusada: {resposta.status_code}"
        )

    corpo = resposta.json()
    if not isinstance(corpo, list):
        raise KeycloakAdminError(
            "Resposta de admin events em formato inesperado"
            " (esperada uma lista)."
        )

    return corpo
