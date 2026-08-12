"""Testes da leitura de eventos e do marcador de captura."""

from typing import Any
from unittest.mock import patch

import pytest

from apps.auditoria.models import CheckpointCaptura
from apps.eventos.clientes.keycloak_admin import KeycloakAdminError
from apps.eventos.servicos import (
    _avancar_checkpoint,
    capturar_admin_events,
    capturar_eventos,
    obter_checkpoint,
)

_CONSULTAR = "apps.eventos.servicos.keycloak_admin.consultar_eventos"
_CONSULTAR_ADMIN = (
    "apps.eventos.servicos.keycloak_admin.consultar_admin_events"
)
_PERSISTIR = "apps.eventos.servicos.task_auditoria_persistir_lote"


def _bruto(instante: int, tipo: str = "LOGIN") -> dict[str, Any]:
    """Monta um evento no formato devolvido pelo Keycloak."""
    return {
        "time": instante,
        "type": tipo,
        "realmId": "COTIC",
        "clientId": "auto-servico-qa",
        "userId": "5c29cc47",
        "sessionId": f"sessao-{instante}",
        "ipAddress": "200.10.0.1",
        "details": {},
    }


def _admin_bruto(instante: int) -> dict[str, Any]:
    """Monta um admin event no formato devolvido pelo Keycloak."""
    return {
        "id": f"evento-{instante}",
        "time": instante,
        "realmId": "COTIC",
        "authDetails": {
            "userId": "quem-executou",
            "clientId": "sme-identidade-admin",
            "ipAddress": "200.10.0.1",
        },
        "operationType": "CREATE",
        "resourceType": "USER",
        "resourcePath": "users/algum-id",
    }


@pytest.mark.django_db
class TestCapturarEventos:
    """Testes de ``capturar_eventos``."""

    def test_primeira_captura_leva_tudo(self) -> None:
        """Deve levar todos os eventos quando ainda não há marcador."""
        eventos = [_bruto(1000), _bruto(2000)]

        with (
            patch(_CONSULTAR, return_value=eventos),
            patch(_PERSISTIR) as persistir,
        ):
            resultado = capturar_eventos("COTIC")

        assert resultado["lidos"] == 2
        assert resultado["novos"] == 2
        assert persistir.delay.call_count == 1

    def test_corte_por_instante_e_estrito(self) -> None:
        """Deve descartar o evento que está exatamente no marcador.

        O evento no marcador já foi levado na leitura anterior;
        incluí-lo de novo geraria trabalho garantido de duplicata a
        cada ciclo.
        """
        CheckpointCaptura.objects.create(realm="COTIC", ultimo_timestamp=2000)
        eventos = [_bruto(1000), _bruto(2000), _bruto(3000)]

        with (
            patch(_CONSULTAR, return_value=eventos),
            patch(_PERSISTIR) as persistir,
        ):
            resultado = capturar_eventos("COTIC")

        assert resultado["novos"] == 1

        enviados = persistir.delay.call_args.args[0]
        assert [e["timestamp_evento"] for e in enviados] == [3000]

    def test_marcador_avanca_para_o_evento_mais_recente(self) -> None:
        """Deve registrar o instante do evento mais novo já entregue."""
        eventos = [_bruto(1000), _bruto(3000), _bruto(2000)]

        with patch(_CONSULTAR, return_value=eventos), patch(_PERSISTIR):
            capturar_eventos("COTIC")

        assert obter_checkpoint("COTIC") == 3000

    def test_marcador_nao_avanca_sem_eventos_novos(self) -> None:
        """Deve manter o marcador quando nada passou do corte."""
        CheckpointCaptura.objects.create(realm="COTIC", ultimo_timestamp=5000)

        with (
            patch(_CONSULTAR, return_value=[_bruto(1000)]),
            patch(_PERSISTIR) as persistir,
        ):
            resultado = capturar_eventos("COTIC")

        assert resultado["novos"] == 0
        assert obter_checkpoint("COTIC") == 5000
        persistir.delay.assert_not_called()

    def test_marcador_nao_avanca_quando_a_entrega_falha(self) -> None:
        """Deve deixar o marcador parado se a entrega não for concluída.

        Repetir uma leitura é resolvido pela restrição de unicidade na
        escrita; perder um evento, não.
        """
        CheckpointCaptura.objects.create(realm="COTIC", ultimo_timestamp=1000)

        with (
            patch(_CONSULTAR, return_value=[_bruto(5000)]),
            patch(_PERSISTIR) as persistir,
        ):
            persistir.delay.side_effect = RuntimeError("fila indisponível")

            with pytest.raises(RuntimeError):
                capturar_eventos("COTIC")

        assert obter_checkpoint("COTIC") == 1000

    def test_consulta_parte_do_marcador_registrado(self) -> None:
        """Deve pedir ao Keycloak só a partir de onde parou."""
        CheckpointCaptura.objects.create(realm="COTIC", ultimo_timestamp=7000)

        with (
            patch(_CONSULTAR, return_value=[]) as consultar,
            patch(_PERSISTIR),
        ):
            capturar_eventos("COTIC")

        assert consultar.call_args.kwargs["desde_ms"] == 7000

    def test_falha_na_leitura_nao_e_engolida(self) -> None:
        """Deve propagar a falha, para não simular uma leitura bem-sucedida."""
        with (
            patch(_CONSULTAR, side_effect=KeycloakAdminError("fora do ar")),
            pytest.raises(KeycloakAdminError),
        ):
            capturar_eventos("COTIC")

        assert obter_checkpoint("COTIC") == 0


@pytest.mark.django_db
class TestCapturarAdminEvents:
    """Testes de ``capturar_admin_events``."""

    def test_primeira_captura_leva_tudo(self) -> None:
        """Deve levar todos os admin events quando ainda não há marcador."""
        eventos = [_admin_bruto(1000), _admin_bruto(2000)]

        with (
            patch(_CONSULTAR_ADMIN, return_value=eventos),
            patch(_PERSISTIR) as persistir,
        ):
            resultado = capturar_admin_events("COTIC")

        assert resultado["lidos"] == 2
        assert resultado["novos"] == 2
        assert persistir.delay.call_count == 1

    def test_marcador_avanca_para_o_evento_mais_recente(self) -> None:
        """Deve registrar o instante do admin event mais novo entregue."""
        eventos = [_admin_bruto(1000), _admin_bruto(3000), _admin_bruto(2000)]

        with patch(_CONSULTAR_ADMIN, return_value=eventos), patch(_PERSISTIR):
            capturar_admin_events("COTIC")

        assert (
            obter_checkpoint("COTIC", canal=CheckpointCaptura.CANAL_ADMIN)
            == 3000
        )

    def test_falha_na_leitura_nao_e_engolida(self) -> None:
        """Deve propagar a falha, sem simular uma leitura bem-sucedida."""
        with (
            patch(
                _CONSULTAR_ADMIN, side_effect=KeycloakAdminError("fora do ar")
            ),
            pytest.raises(KeycloakAdminError),
        ):
            capturar_admin_events("COTIC")

    def test_checkpoint_e_independente_do_canal_de_usuario(self) -> None:
        """Deve manter marcadores separados por canal, mesmo realm.

        Os dois canais têm timestamps de origem independentes — um
        avanço no canal de usuário não pode fazer o canal de admin
        pular eventos, e vice-versa.
        """
        with patch(_CONSULTAR, return_value=[_bruto(9000)]), patch(_PERSISTIR):
            capturar_eventos("COTIC")

        with (
            patch(_CONSULTAR_ADMIN, return_value=[_admin_bruto(1000)]),
            patch(_PERSISTIR),
        ):
            resultado = capturar_admin_events("COTIC")

        assert resultado["novos"] == 1
        assert (
            obter_checkpoint("COTIC", canal=CheckpointCaptura.CANAL_USUARIO)
            == 9000
        )
        assert (
            obter_checkpoint("COTIC", canal=CheckpointCaptura.CANAL_ADMIN)
            == 1000
        )


@pytest.mark.django_db
class TestObterCheckpoint:
    """Testes de ``obter_checkpoint``."""

    def test_realm_sem_captura_comeca_do_zero(self) -> None:
        """Deve começar do início quando o realm nunca foi capturado."""
        assert obter_checkpoint("NOVO") == 0

    def test_devolve_o_marcador_registrado(self) -> None:
        """Deve devolver a posição já registrada para o realm."""
        CheckpointCaptura.objects.create(realm="COTIC", ultimo_timestamp=4200)

        assert obter_checkpoint("COTIC") == 4200

    def test_canais_do_mesmo_realm_sao_independentes(self) -> None:
        """Deve manter marcadores separados por canal, mesmo realm."""
        CheckpointCaptura.objects.create(
            realm="COTIC",
            canal=CheckpointCaptura.CANAL_USUARIO,
            ultimo_timestamp=1000,
        )
        CheckpointCaptura.objects.create(
            realm="COTIC",
            canal=CheckpointCaptura.CANAL_ADMIN,
            ultimo_timestamp=2000,
        )

        assert (
            obter_checkpoint("COTIC", canal=CheckpointCaptura.CANAL_USUARIO)
            == 1000
        )
        assert (
            obter_checkpoint("COTIC", canal=CheckpointCaptura.CANAL_ADMIN)
            == 2000
        )


@pytest.mark.django_db
class TestAvancarCheckpoint:
    """Testes do avanço do marcador de captura."""

    def test_cria_o_marcador_na_primeira_captura(self) -> None:
        """Deve registrar a posição de um realm ainda não capturado."""
        _avancar_checkpoint("COTIC", 1000)

        assert obter_checkpoint("COTIC") == 1000

    def test_avanca_para_posicao_mais_recente(self) -> None:
        """Deve mover o marcador para frente."""
        _avancar_checkpoint("COTIC", 1000)
        _avancar_checkpoint("COTIC", 2000)

        assert obter_checkpoint("COTIC") == 2000

    def test_ignora_posicao_mais_antiga(self) -> None:
        """Deve recusar o retrocesso do marcador.

        Leituras sobrepostas terminam fora de ordem por natureza;
        recuar faria a leitura seguinte refazer uma janela pronta.
        """
        _avancar_checkpoint("COTIC", 5000)
        _avancar_checkpoint("COTIC", 3000)

        assert obter_checkpoint("COTIC") == 5000

    def test_marcadores_de_realms_sao_independentes(self) -> None:
        """Deve manter um marcador por realm, sem interferência."""
        _avancar_checkpoint("COTIC", 5000)
        _avancar_checkpoint("OUTRO", 1000)

        assert obter_checkpoint("COTIC") == 5000
        assert obter_checkpoint("OUTRO") == 1000
