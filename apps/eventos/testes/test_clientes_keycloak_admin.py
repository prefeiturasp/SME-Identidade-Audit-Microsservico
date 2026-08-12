"""Testes do cliente de leitura de eventos no Keycloak.

Formato de evento de usuário confirmado contra Keycloak real de QA em
11/08/2026; formato de admin event confirmado em 12/08/2026 (ver
Memorias/plano_teste_audit/config_keycloak.md). Os testes aqui usam
mock de HTTP, mas o formato dos payloads simulados reflete o que foi
observado, não mais suposição de documentação.
"""

from typing import Any
from unittest.mock import patch

import httpx
import pytest

from apps.eventos.clientes.keycloak_admin import (
    KeycloakAdminError,
    consultar_admin_events,
    consultar_eventos,
    obter_token_acesso,
)

_POST = "apps.eventos.clientes.keycloak_admin.httpx.post"
_GET = "apps.eventos.clientes.keycloak_admin.httpx.get"

_EVENTO = {
    "time": 1786000000000,
    "type": "LOGIN",
    "realmId": "COTIC",
    "clientId": "auto-servico-qa",
    "userId": "5c29cc47",
    "ipAddress": "200.10.0.1",
    "details": {"username": "1234567"},
}

_ADMIN_EVENT = {
    "id": "354c785c-b24a-42d2-92de-d9cd77afe4f7",
    "time": 1786496262500,
    "realmId": "COTIC",
    "authDetails": {
        "clientId": "0d06cf29-d522-4fb9-ad68-e8079dbb468c",
        "userId": "eced19ec-2b8a-4d8f-84fb-f2d586e14f74",
        "ipAddress": "172.21.2.65",
    },
    "operationType": "CREATE",
    "resourceType": "USER",
    "resourcePath": "users/b63a36e7-61fd-449b-8d2c-8f684249ac1f",
    "representation": '{"username":"teste"}',
}


def _resposta(
    status_code: int,
    corpo: Any = None,
    metodo: str = "GET",
) -> httpx.Response:
    """Resposta simulada do Keycloak."""
    return httpx.Response(
        status_code,
        json=corpo,
        request=httpx.Request(metodo, "https://keycloak/teste"),
    )


@pytest.fixture(autouse=True)
def _configura_keycloak(settings: Any) -> None:
    """Define as configurações de acesso ao Keycloak nos testes."""
    settings.KEYCLOAK_URL_SERVIDOR = "https://keycloak.exemplo/"
    settings.KEYCLOAK_REALM = "COTIC"
    settings.KEYCLOAK_CLIENT_ID = "identidade-auditoria"
    settings.KEYCLOAK_CLIENT_SECRET = "segredo"
    settings.KEYCLOAK_VERIFICAR_SSL = True
    settings.KEYCLOAK_TIMEOUT = 30.0
    settings.AUDITORIA_LIMITE_CONSULTA = 500
    settings.AUDITORIA_TIPOS_EVENTO = ["LOGIN", "LOGOUT"]


class TestObterTokenAcesso:
    """Testes de ``obter_token_acesso``."""

    def test_devolve_o_token_da_service_account(self) -> None:
        """Deve autenticar por client credentials e devolver o token."""
        with patch(
            _POST,
            return_value=_resposta(200, {"access_token": "token-abc"}, "POST"),
        ) as post:
            assert obter_token_acesso() == "token-abc"

        enviado = post.call_args.kwargs["data"]
        assert enviado["grant_type"] == "client_credentials"
        assert enviado["client_id"] == "identidade-auditoria"

    def test_falha_quando_a_autenticacao_e_recusada(self) -> None:
        """Deve sinalizar recusa da credencial."""
        with (
            patch(_POST, return_value=_resposta(401, {}, "POST")),
            pytest.raises(KeycloakAdminError),
        ):
            obter_token_acesso()

    def test_falha_quando_a_resposta_nao_traz_token(self) -> None:
        """Deve sinalizar resposta sem o token esperado."""
        with (
            patch(_POST, return_value=_resposta(200, {}, "POST")),
            pytest.raises(KeycloakAdminError),
        ):
            obter_token_acesso()

    def test_falha_quando_o_servidor_nao_responde(self) -> None:
        """Deve sinalizar indisponibilidade do servidor."""
        with (
            patch(_POST, side_effect=httpx.ConnectError("fora do ar")),
            pytest.raises(KeycloakAdminError),
        ):
            obter_token_acesso()


class TestConsultarEventos:
    """Testes de ``consultar_eventos``."""

    def test_devolve_os_eventos_lidos(self) -> None:
        """Deve devolver o que o Keycloak respondeu, sem alterar."""
        with (
            patch(
                _POST,
                return_value=_resposta(200, {"access_token": "t"}, "POST"),
            ),
            patch(_GET, return_value=_resposta(200, [_EVENTO])),
        ):
            eventos = consultar_eventos("COTIC")

        assert eventos == [_EVENTO]

    def test_envia_o_token_no_cabecalho(self) -> None:
        """Deve autenticar a consulta com o token obtido."""
        with (
            patch(
                _POST,
                return_value=_resposta(
                    200, {"access_token": "token-abc"}, "POST"
                ),
            ),
            patch(_GET, return_value=_resposta(200, [])) as get,
        ):
            consultar_eventos("COTIC")

        cabecalhos = get.call_args.kwargs["headers"]
        assert cabecalhos["Authorization"] == "Bearer token-abc"

    def test_restringe_a_consulta_aos_tipos_configurados(self) -> None:
        """Deve pedir só os tipos de interesse, não o tráfego inteiro."""
        with (
            patch(
                _POST,
                return_value=_resposta(200, {"access_token": "t"}, "POST"),
            ),
            patch(_GET, return_value=_resposta(200, [])) as get,
        ):
            consultar_eventos("COTIC")

        assert get.call_args.kwargs["params"]["type"] == ["LOGIN", "LOGOUT"]

    def test_aplica_o_teto_de_eventos_por_leitura(self) -> None:
        """Deve limitar quanto uma única leitura traz."""
        with (
            patch(
                _POST,
                return_value=_resposta(200, {"access_token": "t"}, "POST"),
            ),
            patch(_GET, return_value=_resposta(200, [])) as get,
        ):
            consultar_eventos("COTIC", limite=50)

        assert get.call_args.kwargs["params"]["max"] == 50

    def test_deriva_a_data_inicial_do_instante_informado(self) -> None:
        """Deve recortar a consulta a partir da data do marcador.

        A Admin API filtra por dia; o corte fino, no instante exato,
        fica a cargo de quem consome.
        """
        with (
            patch(
                _POST,
                return_value=_resposta(200, {"access_token": "t"}, "POST"),
            ),
            patch(_GET, return_value=_resposta(200, [])) as get,
        ):
            consultar_eventos("COTIC", desde_ms=1786000000000)

        assert "dateFrom" in get.call_args.kwargs["params"]

    def test_consulta_o_realm_informado(self) -> None:
        """Deve consultar o realm pedido, não o configurado por padrão."""
        with (
            patch(
                _POST,
                return_value=_resposta(200, {"access_token": "t"}, "POST"),
            ),
            patch(_GET, return_value=_resposta(200, [])) as get,
        ):
            consultar_eventos("OUTRO")

        assert "/admin/realms/OUTRO/events" in get.call_args.args[0]

    def test_falha_quando_a_consulta_e_recusada(self) -> None:
        """Deve sinalizar recusa da consulta."""
        with (
            patch(
                _POST,
                return_value=_resposta(200, {"access_token": "t"}, "POST"),
            ),
            patch(_GET, return_value=_resposta(403, {})),
            pytest.raises(KeycloakAdminError),
        ):
            consultar_eventos("COTIC")

    def test_falha_quando_a_resposta_nao_e_uma_lista(self) -> None:
        """Deve sinalizar formato inesperado em vez de seguir adiante."""
        with (
            patch(
                _POST,
                return_value=_resposta(200, {"access_token": "t"}, "POST"),
            ),
            patch(_GET, return_value=_resposta(200, {"erro": "inesperado"})),
            pytest.raises(KeycloakAdminError),
        ):
            consultar_eventos("COTIC")

    def test_falha_quando_o_servidor_nao_responde(self) -> None:
        """Deve sinalizar indisponibilidade durante a consulta."""
        with (
            patch(
                _POST,
                return_value=_resposta(200, {"access_token": "t"}, "POST"),
            ),
            patch(_GET, side_effect=httpx.ReadTimeout("demorou")),
            pytest.raises(KeycloakAdminError),
        ):
            consultar_eventos("COTIC")


class TestConsultarAdminEvents:
    """Testes de ``consultar_admin_events``."""

    def test_devolve_os_admin_events_lidos(self) -> None:
        """Deve devolver o que o Keycloak respondeu, sem alterar."""
        with (
            patch(
                _POST,
                return_value=_resposta(200, {"access_token": "t"}, "POST"),
            ),
            patch(_GET, return_value=_resposta(200, [_ADMIN_EVENT])),
        ):
            eventos = consultar_admin_events("COTIC")

        assert eventos == [_ADMIN_EVENT]

    def test_consulta_o_endpoint_de_admin_events(self) -> None:
        """Deve consultar /admin-events, não /events."""
        with (
            patch(
                _POST,
                return_value=_resposta(200, {"access_token": "t"}, "POST"),
            ),
            patch(_GET, return_value=_resposta(200, [])) as get,
        ):
            consultar_admin_events("COTIC")

        assert "/admin/realms/COTIC/admin-events" in get.call_args.args[0]

    def test_envia_o_token_no_cabecalho(self) -> None:
        """Deve autenticar a consulta com o token obtido."""
        with (
            patch(
                _POST,
                return_value=_resposta(
                    200, {"access_token": "token-abc"}, "POST"
                ),
            ),
            patch(_GET, return_value=_resposta(200, [])) as get,
        ):
            consultar_admin_events("COTIC")

        cabecalhos = get.call_args.kwargs["headers"]
        assert cabecalhos["Authorization"] == "Bearer token-abc"

    def test_aplica_o_teto_de_eventos_por_leitura(self) -> None:
        """Deve limitar quanto uma única leitura traz."""
        with (
            patch(
                _POST,
                return_value=_resposta(200, {"access_token": "t"}, "POST"),
            ),
            patch(_GET, return_value=_resposta(200, [])) as get,
        ):
            consultar_admin_events("COTIC", limite=50)

        assert get.call_args.kwargs["params"]["max"] == 50

    def test_deriva_a_data_inicial_do_instante_informado(self) -> None:
        """Deve recortar a consulta a partir da data do marcador."""
        with (
            patch(
                _POST,
                return_value=_resposta(200, {"access_token": "t"}, "POST"),
            ),
            patch(_GET, return_value=_resposta(200, [])) as get,
        ):
            consultar_admin_events("COTIC", desde_ms=1786000000000)

        assert "dateFrom" in get.call_args.kwargs["params"]

    def test_falha_quando_a_consulta_e_recusada(self) -> None:
        """Deve sinalizar recusa da consulta."""
        with (
            patch(
                _POST,
                return_value=_resposta(200, {"access_token": "t"}, "POST"),
            ),
            patch(_GET, return_value=_resposta(403, {})),
            pytest.raises(KeycloakAdminError),
        ):
            consultar_admin_events("COTIC")

    def test_falha_quando_a_resposta_nao_e_uma_lista(self) -> None:
        """Deve sinalizar formato inesperado em vez de seguir adiante."""
        with (
            patch(
                _POST,
                return_value=_resposta(200, {"access_token": "t"}, "POST"),
            ),
            patch(_GET, return_value=_resposta(200, {"erro": "inesperado"})),
            pytest.raises(KeycloakAdminError),
        ):
            consultar_admin_events("COTIC")

    def test_falha_quando_o_servidor_nao_responde(self) -> None:
        """Deve sinalizar indisponibilidade durante a consulta."""
        with (
            patch(
                _POST,
                return_value=_resposta(200, {"access_token": "t"}, "POST"),
            ),
            patch(_GET, side_effect=httpx.ReadTimeout("demorou")),
            pytest.raises(KeycloakAdminError),
        ):
            consultar_admin_events("COTIC")
