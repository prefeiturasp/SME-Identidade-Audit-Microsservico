"""Testes do endpoint de consulta de eventos de auditoria."""

import datetime as dt
from typing import Any

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.auditoria.models import EventoAuditoria


def _gravar(
    chave: str,
    usuario_id: str = "usuario-a",
    client_id: str = "sistema-a",
    tipo_evento: str = "LOGIN",
    dias_atras: int = 0,
) -> EventoAuditoria:
    """Grava um evento de auditoria com os atributos informados."""
    return EventoAuditoria.objects.create(
        evento_id_origem=chave,
        tipo_evento=tipo_evento,
        usuario_id=usuario_id,
        client_id=client_id,
        realm="COTIC",
        timestamp_evento=(timezone.now() - dt.timedelta(days=dias_atras)),
        detalhes={"username": "1234567"},
    )


@pytest.mark.django_db
class TestEventoAuditoriaListView:
    """Testes de ``EventoAuditoriaListView``."""

    @pytest.fixture(autouse=True)
    def _configura_api_key(self, settings: Any) -> None:
        """Define API_KEY/API_KEY_HEADER para o escopo de cada teste."""
        settings.API_KEY = "chave-secreta"
        settings.API_KEY_HEADER = "X-API-Key"

    def _consultar(
        self,
        parametros: dict | None = None,
        chave: str | None = "chave-secreta",
    ) -> Any:
        """Consulta o endpoint, com ou sem credencial."""
        cliente = APIClient()
        if chave:
            cliente.credentials(HTTP_X_API_KEY=chave)

        return cliente.get(reverse("evento-listar"), data=parametros or {})

    def test_rejeita_sem_api_key(self) -> None:
        """Deve bloquear a consulta sem credencial."""
        resposta = self._consultar(chave=None)

        assert resposta.status_code == status.HTTP_401_UNAUTHORIZED

    def test_rejeita_api_key_invalida(self) -> None:
        """Deve bloquear a consulta com credencial errada."""
        resposta = self._consultar(chave="errada")

        assert resposta.status_code == status.HTTP_401_UNAUTHORIZED

    def test_rejeita_data_malformada(self) -> None:
        """Deve recusar uma data que não está em formato reconhecível."""
        resposta = self._consultar({"data_inicio": "nao-e-uma-data"})

        assert resposta.status_code == status.HTTP_400_BAD_REQUEST

    def test_lista_todos_sem_filtro(self) -> None:
        """Deve devolver todos os eventos quando nenhum filtro é aplicado."""
        _gravar("a")
        _gravar("b")

        resposta = self._consultar()

        assert resposta.status_code == status.HTTP_200_OK
        assert resposta.json()["count"] == 2

    def test_filtra_por_usuario(self) -> None:
        """Deve restringir a resposta ao usuário informado."""
        _gravar("do-usuario-a", usuario_id="usuario-a")
        _gravar("do-usuario-b", usuario_id="usuario-b")

        resposta = self._consultar({"usuario_id": "usuario-a"})

        corpo = resposta.json()
        assert corpo["count"] == 1
        assert corpo["results"][0]["evento_id_origem"] == "do-usuario-a"

    def test_filtra_por_sistema(self) -> None:
        """Deve restringir a resposta ao sistema (client_id) informado."""
        _gravar("do-sistema-a", client_id="sistema-a")
        _gravar("do-sistema-b", client_id="sistema-b")

        resposta = self._consultar({"client_id": "sistema-b"})

        corpo = resposta.json()
        assert corpo["count"] == 1
        assert corpo["results"][0]["evento_id_origem"] == "do-sistema-b"

    def test_filtra_por_tipo_evento(self) -> None:
        """Deve restringir a resposta ao tipo de evento informado."""
        _gravar("login", tipo_evento="LOGIN")
        _gravar("logout", tipo_evento="LOGOUT")

        resposta = self._consultar({"tipo_evento": "LOGOUT"})

        corpo = resposta.json()
        assert corpo["count"] == 1
        assert corpo["results"][0]["evento_id_origem"] == "logout"

    def test_filtra_por_periodo(self) -> None:
        """Deve restringir a resposta ao intervalo de datas informado."""
        _gravar("fora", dias_atras=10)
        _gravar("dentro", dias_atras=1)

        agora = timezone.now()
        resposta = self._consultar(
            {
                "data_inicio": (agora - dt.timedelta(days=3)).isoformat(),
                "data_fim": agora.isoformat(),
            }
        )

        corpo = resposta.json()
        assert corpo["count"] == 1
        assert corpo["results"][0]["evento_id_origem"] == "dentro"

    def test_pagina_com_tamanho_padrao_de_cem(self) -> None:
        """Deve paginar com 100 registros por página quando não informado."""
        for indice in range(105):
            _gravar(f"evento-{indice}")

        resposta = self._consultar()

        corpo = resposta.json()
        assert corpo["count"] == 105
        assert len(corpo["results"]) == 100
        assert corpo["next"] is not None

    def test_pagina_com_tamanho_configurado(self) -> None:
        """Deve respeitar o tamanho de página informado via page_size."""
        for indice in range(10):
            _gravar(f"evento-{indice}")

        resposta = self._consultar({"page_size": 5})

        corpo = resposta.json()
        assert len(corpo["results"]) == 5

    def test_ordena_do_mais_recente_para_o_mais_antigo(self) -> None:
        """Deve devolver os eventos do mais recente para o mais antigo."""
        _gravar("antigo", dias_atras=5)
        _gravar("recente", dias_atras=0)

        resposta = self._consultar()

        resultados = resposta.json()["results"]
        assert [item["evento_id_origem"] for item in resultados] == [
            "recente",
            "antigo",
        ]

    def test_sem_eventos_retorna_lista_vazia(self) -> None:
        """Deve responder 200 com lista vazia quando não há eventos."""
        resposta = self._consultar()

        corpo = resposta.json()
        assert resposta.status_code == status.HTTP_200_OK
        assert corpo["count"] == 0
        assert corpo["results"] == []
