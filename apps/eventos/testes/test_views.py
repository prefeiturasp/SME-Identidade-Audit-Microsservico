"""Testes do endpoint que recebe o aviso de atividade."""

from typing import Any
from unittest.mock import patch

import pytest
from django.urls import reverse
from kombu.exceptions import OperationalError
from rest_framework import status
from rest_framework.test import APIClient

_TASK = "apps.eventos.api.views.task_auditoria_consultar_eventos"

_USUARIO_ID = "5c29cc47-0000-0000-0000-000000000000"


class TestGatilhoPollView:
    """Testes de ``GatilhoPollView``."""

    @pytest.fixture(autouse=True)
    def _configura_api_key(self, settings: Any) -> None:
        """Define API_KEY/API_KEY_HEADER para o escopo de cada teste."""
        settings.API_KEY = "chave-secreta"
        settings.API_KEY_HEADER = "X-API-Key"

    def _enviar(self, dados: dict, chave: str | None = "chave-secreta") -> Any:
        """Envia o aviso ao endpoint, com ou sem credencial."""
        cliente = APIClient()
        if chave:
            cliente.credentials(HTTP_X_API_KEY=chave)

        return cliente.post(
            reverse("gatilho-poll"),
            data=dados,
            format="json",
        )

    def test_aceita_aviso_valido_e_enfileira_consulta(self) -> None:
        """Deve aceitar o aviso e pedir a consulta antecipada."""
        with patch(_TASK) as task:
            resposta = self._enviar(
                {"realm": "COTIC", "usuario_id": _USUARIO_ID}
            )

        assert resposta.status_code == status.HTTP_202_ACCEPTED
        assert resposta.json() == {
            "situacao": "consulta_enfileirada",
            "realm": "COTIC",
        }
        task.delay.assert_called_once_with("COTIC")

    def test_rejeita_sem_api_key(self) -> None:
        """Deve bloquear o aviso sem credencial."""
        with patch(_TASK) as task:
            resposta = self._enviar(
                {"realm": "COTIC", "usuario_id": _USUARIO_ID}, chave=None
            )

        assert resposta.status_code == status.HTTP_401_UNAUTHORIZED
        task.delay.assert_not_called()

    def test_rejeita_api_key_invalida(self) -> None:
        """Deve bloquear o aviso com credencial errada."""
        with patch(_TASK) as task:
            resposta = self._enviar(
                {"realm": "COTIC", "usuario_id": _USUARIO_ID}, chave="errada"
            )

        assert resposta.status_code == status.HTTP_401_UNAUTHORIZED
        task.delay.assert_not_called()

    def test_rejeita_aviso_sem_realm(self) -> None:
        """Deve recusar o aviso que não diz qual realm consultar."""
        with patch(_TASK) as task:
            resposta = self._enviar({"usuario_id": _USUARIO_ID})

        assert resposta.status_code == status.HTTP_400_BAD_REQUEST
        task.delay.assert_not_called()

    def test_rejeita_aviso_sem_usuario(self) -> None:
        """Deve recusar o aviso que não identifica o usuário."""
        with patch(_TASK) as task:
            resposta = self._enviar({"realm": "COTIC"})

        assert resposta.status_code == status.HTTP_400_BAD_REQUEST
        task.delay.assert_not_called()

    def test_rejeita_aviso_vazio(self) -> None:
        """Deve recusar o aviso sem nenhum dado."""
        with patch(_TASK) as task:
            resposta = self._enviar({})

        assert resposta.status_code == status.HTTP_400_BAD_REQUEST
        task.delay.assert_not_called()

    def test_rejeita_campos_em_branco(self) -> None:
        """Deve recusar campos presentes mas vazios."""
        with patch(_TASK) as task:
            resposta = self._enviar({"realm": "   ", "usuario_id": "   "})

        assert resposta.status_code == status.HTTP_400_BAD_REQUEST
        task.delay.assert_not_called()

    def test_responde_503_com_a_fila_indisponivel(self) -> None:
        """Deve avisar que a consulta não foi enfileirada.

        O ciclo agendado ainda captura a atividade depois, então a
        recusa é informativa e não representa perda de evento.
        """
        with patch(_TASK) as task:
            task.delay.side_effect = OperationalError("keydb fora do ar")

            resposta = self._enviar(
                {"realm": "COTIC", "usuario_id": _USUARIO_ID}
            )

        assert resposta.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert resposta.json() == {"erro": "fila indisponível"}

    def test_nao_aceita_evento_pronto(self) -> None:
        """Deve ignorar qualquer dado de evento enviado junto do aviso.

        Aceitar um evento pronto criaria uma segunda origem do mesmo
        dado, com timestamp próprio, e a deduplicação passaria a
        depender de reconciliar formatos divergentes.
        """
        with patch(_TASK) as task:
            resposta = self._enviar(
                {
                    "realm": "COTIC",
                    "usuario_id": _USUARIO_ID,
                    "type": "LOGIN",
                    "time": 1786000000000,
                    "details": {"username": "1234567"},
                }
            )

        assert resposta.status_code == status.HTTP_202_ACCEPTED
        task.delay.assert_called_once_with("COTIC")
