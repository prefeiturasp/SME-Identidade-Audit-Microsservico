"""Testes das tarefas de escrita e de retenção."""

from typing import Any

import pytest

from apps.auditoria.models import EventoAuditoria
from apps.auditoria.tasks import (
    task_auditoria_expurgar_eventos,
    task_auditoria_persistir_lote,
)


@pytest.mark.django_db
class TestTaskPersistirLote:
    """Testes de ``task_auditoria_persistir_lote``."""

    def test_grava_o_lote_recebido(self) -> None:
        """Deve gravar os eventos entregues pela captura."""
        resultado = task_auditoria_persistir_lote(
            [
                {
                    "evento_id_origem": "chave-a",
                    "tipo_evento": "LOGIN",
                    "usuario_id": "5c29cc47",
                    "realm": "COTIC",
                    "client_id": "auto-servico-qa",
                    "ip_origem": "200.10.0.1",
                    "timestamp_evento": 1786000000000,
                    "detalhes": {},
                }
            ]
        )

        assert resultado == {"recebidos": 1, "gravados": 1}
        assert EventoAuditoria.objects.count() == 1


@pytest.mark.django_db
class TestTaskExpurgarEventos:
    """Testes de ``task_auditoria_expurgar_eventos``."""

    def test_nao_remove_com_a_rotina_desligada(self, settings: Any) -> None:
        """Deve respeitar a decisão pendente sobre o período de guarda."""
        settings.AUDITORIA_EXPURGO_ATIVO = False

        resultado = task_auditoria_expurgar_eventos()

        assert resultado["situacao"] == "desativado"
