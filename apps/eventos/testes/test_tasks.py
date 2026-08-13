"""Testes da tarefa de captura de eventos."""

from typing import Any
from unittest.mock import patch

import pytest

from apps.auditoria.models import CheckpointCaptura
from apps.eventos.clientes.keycloak_admin import KeycloakAdminError
from apps.eventos.tasks import (
    task_auditoria_consultar_admin_events,
    task_auditoria_consultar_eventos,
)

_CAPTURAR = "apps.eventos.tasks.capturar_eventos"
_CAPTURAR_ADMIN = "apps.eventos.tasks.capturar_admin_events"


@pytest.mark.django_db
class TestTaskConsultarEventos:
    """Testes de ``task_auditoria_consultar_eventos``."""

    def test_captura_o_realm_informado(self) -> None:
        """Deve capturar o realm pedido no aviso."""
        with patch(_CAPTURAR, return_value={"novos": 1}) as capturar:
            task_auditoria_consultar_eventos("OUTRO")

        capturar.assert_called_once_with("OUTRO")

    def test_usa_o_realm_configurado_por_padrao(self, settings: Any) -> None:
        """Deve cair no realm configurado quando nenhum é informado."""
        settings.KEYCLOAK_REALM = "COTIC"

        with patch(_CAPTURAR, return_value={"novos": 0}) as capturar:
            task_auditoria_consultar_eventos()

        capturar.assert_called_once_with("COTIC")

    def test_falha_de_leitura_nao_derruba_a_execucao(self) -> None:
        """Deve reportar o erro sem interromper o ciclo agendado.

        Uma leitura frustrada não é perda de evento: o marcador segue
        onde está e a execução seguinte cobre a mesma janela.
        """
        with patch(_CAPTURAR, side_effect=KeycloakAdminError("fora do ar")):
            resultado = task_auditoria_consultar_eventos("COTIC")

        assert resultado["situacao"] == "erro"
        assert resultado["realm"] == "COTIC"

    def test_falha_de_leitura_nao_avanca_o_marcador(self) -> None:
        """Deve deixar o marcador intacto quando a leitura falha."""
        CheckpointCaptura.objects.create(realm="COTIC", ultimo_timestamp=1000)

        with patch(_CAPTURAR, side_effect=KeycloakAdminError("fora do ar")):
            task_auditoria_consultar_eventos("COTIC")

        checkpoint = CheckpointCaptura.objects.get(realm="COTIC")
        assert checkpoint.ultimo_timestamp == 1000

    def test_devolve_o_resultado_da_captura(self) -> None:
        """Deve repassar o que a captura apurou."""
        esperado = {"lidos": 5, "novos": 2, "checkpoint": 3000}

        with patch(_CAPTURAR, return_value=esperado):
            assert task_auditoria_consultar_eventos("COTIC") == esperado


@pytest.mark.django_db
class TestTaskConsultarAdminEvents:
    """Testes de ``task_auditoria_consultar_admin_events``."""

    def test_captura_o_realm_informado(self) -> None:
        """Deve capturar o realm pedido."""
        with patch(_CAPTURAR_ADMIN, return_value={"novos": 1}) as capturar:
            task_auditoria_consultar_admin_events("OUTRO")

        capturar.assert_called_once_with("OUTRO")

    def test_usa_o_realm_configurado_por_padrao(self, settings: Any) -> None:
        """Deve cair no realm configurado quando nenhum é informado."""
        settings.KEYCLOAK_REALM = "COTIC"

        with patch(_CAPTURAR_ADMIN, return_value={"novos": 0}) as capturar:
            task_auditoria_consultar_admin_events()

        capturar.assert_called_once_with("COTIC")

    def test_falha_de_leitura_nao_derruba_a_execucao(self) -> None:
        """Deve reportar o erro sem interromper o ciclo agendado."""
        with patch(
            _CAPTURAR_ADMIN, side_effect=KeycloakAdminError("fora do ar")
        ):
            resultado = task_auditoria_consultar_admin_events("COTIC")

        assert resultado["situacao"] == "erro"
        assert resultado["realm"] == "COTIC"

    def test_devolve_o_resultado_da_captura(self) -> None:
        """Deve repassar o que a captura apurou."""
        esperado = {"lidos": 3, "novos": 1, "checkpoint": 1500}

        with patch(_CAPTURAR_ADMIN, return_value=esperado):
            assert task_auditoria_consultar_admin_events("COTIC") == esperado
