"""Testes de escrita e de retenção dos eventos de auditoria."""

import datetime as dt
from typing import Any

import pytest
from django.utils import timezone

from apps.auditoria.models import EventoAuditoria
from apps.auditoria.servicos import (
    consultar_eventos,
    expurgar_eventos_antigos,
    persistir_lote,
)

_INSTANTE_MS = 1786000000000


def _dados(
    evento_id_origem: str = "chave-a",
    tipo_evento: str = "LOGIN",
    timestamp_ms: int = _INSTANTE_MS,
) -> dict[str, Any]:
    """Monta um evento normalizado para os testes."""
    return {
        "evento_id_origem": evento_id_origem,
        "tipo_evento": tipo_evento,
        "usuario_id": "5c29cc47",
        "realm": "COTIC",
        "client_id": "auto-servico-qa",
        "ip_origem": "200.10.0.1",
        "timestamp_evento": timestamp_ms,
        "detalhes": {"username": "1234567"},
    }


@pytest.mark.django_db
class TestPersistirLote:
    """Testes de ``persistir_lote``."""

    def test_grava_lote_completo(self) -> None:
        """Deve gravar todos os eventos inéditos do lote."""
        resultado = persistir_lote([_dados("a"), _dados("b"), _dados("c")])

        assert resultado == {"recebidos": 3, "gravados": 3}
        assert EventoAuditoria.objects.count() == 3

    def test_lote_vazio_nao_toca_o_banco(self) -> None:
        """Deve encerrar sem escrita quando não há o que gravar."""
        resultado = persistir_lote([])

        assert resultado == {"recebidos": 0, "gravados": 0}
        assert EventoAuditoria.objects.count() == 0

    def test_converte_instante_para_data_com_fuso(self) -> None:
        """Deve traduzir o instante em milissegundos para data com fuso."""
        persistir_lote([_dados("a", timestamp_ms=_INSTANTE_MS)])

        gravado = EventoAuditoria.objects.get(evento_id_origem="a")
        esperado = dt.datetime.fromtimestamp(_INSTANTE_MS / 1000, tz=dt.UTC)

        assert gravado.timestamp_evento == esperado

    def test_preserva_o_payload_bruto_em_detalhes(self) -> None:
        """Deve guardar o payload completo, não só os campos promovidos."""
        dados = _dados("a")
        dados["detalhes"] = {"username": "1234567", "campo_novo": "valor"}

        persistir_lote([dados])

        gravado = EventoAuditoria.objects.get(evento_id_origem="a")
        assert gravado.detalhes["campo_novo"] == "valor"

    def test_normaliza_campos_ausentes_para_nulo(self) -> None:
        """Deve gravar como nulo o que veio vazio na origem."""
        dados = _dados("a")
        dados["usuario_id"] = ""
        dados["client_id"] = None
        dados["ip_origem"] = ""

        persistir_lote([dados])

        gravado = EventoAuditoria.objects.get(evento_id_origem="a")
        assert gravado.usuario_id is None
        assert gravado.client_id is None
        assert gravado.ip_origem is None

    def test_reenvio_do_mesmo_evento_nao_duplica(self) -> None:
        """Deve descartar a repetição sem falhar a escrita."""
        persistir_lote([_dados("a")])
        resultado = persistir_lote([_dados("a")])

        assert resultado == {"recebidos": 1, "gravados": 0}
        assert EventoAuditoria.objects.count() == 1

    def test_leituras_sobrepostas_geram_uma_unica_linha(self) -> None:
        """Deve manter uma linha só quando duas leituras trazem o mesmo evento.

        Reproduz a corrida que motiva a restrição de unicidade: a
        leitura antecipada e o ciclo agendado alcançam o mesmo evento
        real e tentam gravá-lo, cada um com o seu lote. É a restrição
        no banco que decide — nenhum dos dois consulta o outro.
        """
        lote_leitura_antecipada = [_dados("compartilhado"), _dados("so-do-1")]
        lote_ciclo_agendado = [_dados("compartilhado"), _dados("so-do-2")]

        primeiro = persistir_lote(lote_leitura_antecipada)
        segundo = persistir_lote(lote_ciclo_agendado)

        assert (
            EventoAuditoria.objects.filter(
                evento_id_origem="compartilhado"
            ).count()
            == 1
        )
        assert EventoAuditoria.objects.count() == 3
        assert primeiro["gravados"] == 2
        assert segundo["gravados"] == 1

    def test_lote_com_repeticao_interna_grava_uma_vez(self) -> None:
        """Deve absorver a repetição dentro de um mesmo lote."""
        persistir_lote([_dados("a"), _dados("a"), _dados("b")])

        assert EventoAuditoria.objects.filter(
            evento_id_origem="a"
        ).count() == (1)
        assert EventoAuditoria.objects.count() == 2


@pytest.mark.django_db
class TestConsultarEventos:
    """Testes de ``consultar_eventos``."""

    def _gravar(
        self,
        chave: str,
        usuario_id: str = "usuario-a",
        client_id: str = "sistema-a",
        tipo_evento: str = "LOGIN",
        dias_atras: int = 0,
    ) -> EventoAuditoria:
        """Grava um evento com os atributos informados."""
        return EventoAuditoria.objects.create(
            evento_id_origem=chave,
            tipo_evento=tipo_evento,
            usuario_id=usuario_id,
            client_id=client_id,
            realm="COTIC",
            timestamp_evento=(timezone.now() - dt.timedelta(days=dias_atras)),
            detalhes={},
        )

    def test_sem_filtro_retorna_tudo_do_mais_recente(self) -> None:
        """Deve devolver todos os eventos, do mais recente ao mais antigo."""
        self._gravar("antigo", dias_atras=5)
        self._gravar("recente", dias_atras=0)

        resultado = list(consultar_eventos())

        assert [e.evento_id_origem for e in resultado] == [
            "recente",
            "antigo",
        ]

    def test_filtra_por_usuario(self) -> None:
        """Deve restringir aos eventos do usuário informado."""
        self._gravar("do-usuario-a", usuario_id="usuario-a")
        self._gravar("do-usuario-b", usuario_id="usuario-b")

        resultado = consultar_eventos(usuario_id="usuario-a")

        assert [e.evento_id_origem for e in resultado] == ["do-usuario-a"]

    def test_filtra_por_sistema(self) -> None:
        """Deve restringir aos eventos do sistema (client_id) informado."""
        self._gravar("do-sistema-a", client_id="sistema-a")
        self._gravar("do-sistema-b", client_id="sistema-b")

        resultado = consultar_eventos(client_id="sistema-a")

        assert [e.evento_id_origem for e in resultado] == ["do-sistema-a"]

    def test_filtra_por_tipo_evento(self) -> None:
        """Deve restringir aos eventos do tipo informado."""
        self._gravar("login", tipo_evento="LOGIN")
        self._gravar("logout", tipo_evento="LOGOUT")

        resultado = consultar_eventos(tipo_evento="LOGOUT")

        assert [e.evento_id_origem for e in resultado] == ["logout"]

    def test_filtra_por_periodo(self) -> None:
        """Deve restringir ao intervalo de datas informado, inclusive."""
        self._gravar("fora-antes", dias_atras=10)
        self._gravar("dentro", dias_atras=5)
        self._gravar("fora-depois", dias_atras=0)

        agora = timezone.now()
        resultado = consultar_eventos(
            data_inicio=agora - dt.timedelta(days=7),
            data_fim=agora - dt.timedelta(days=3),
        )

        assert [e.evento_id_origem for e in resultado] == ["dentro"]

    def test_combina_filtros(self) -> None:
        """Deve aplicar todos os filtros informados em conjunto."""
        self._gravar(
            "combina",
            usuario_id="usuario-a",
            client_id="sistema-a",
            tipo_evento="LOGIN",
        )
        self._gravar(
            "nao-combina-usuario",
            usuario_id="usuario-b",
            client_id="sistema-a",
            tipo_evento="LOGIN",
        )

        resultado = consultar_eventos(
            usuario_id="usuario-a",
            client_id="sistema-a",
            tipo_evento="LOGIN",
        )

        assert [e.evento_id_origem for e in resultado] == ["combina"]


@pytest.mark.django_db
class TestExpurgarEventosAntigos:
    """Testes de ``expurgar_eventos_antigos``."""

    def _gravar(self, chave: str, dias_atras: int) -> None:
        """Grava um evento com a idade informada."""
        EventoAuditoria.objects.create(
            evento_id_origem=chave,
            tipo_evento="LOGIN",
            realm="COTIC",
            timestamp_evento=(timezone.now() - dt.timedelta(days=dias_atras)),
            detalhes={},
        )

    def test_nao_remove_nada_com_a_rotina_desligada(
        self, settings: Any
    ) -> None:
        """Deve preservar tudo enquanto a remoção não estiver autorizada."""
        settings.AUDITORIA_EXPURGO_ATIVO = False
        settings.AUDITORIA_RETENCAO_DIAS = 30
        self._gravar("antigo", dias_atras=400)

        resultado = expurgar_eventos_antigos()

        assert resultado["situacao"] == "desativado"
        assert resultado["removidos"] == 0
        assert EventoAuditoria.objects.count() == 1

    def test_remove_apenas_fora_do_periodo_de_retencao(
        self, settings: Any
    ) -> None:
        """Deve remover só o que já passou do período configurado."""
        settings.AUDITORIA_EXPURGO_ATIVO = False
        settings.AUDITORIA_RETENCAO_DIAS = 30
        settings.AUDITORIA_EXPURGO_TAMANHO_LOTE = 1000

        self._gravar("dentro-recente", dias_atras=1)
        self._gravar("dentro-limite", dias_atras=29)
        self._gravar("fora-limite", dias_atras=31)
        self._gravar("fora-antigo", dias_atras=400)

        resultado = expurgar_eventos_antigos(forcar=True)

        assert resultado["situacao"] == "executado"
        assert resultado["removidos"] == 2

        restantes = set(
            EventoAuditoria.objects.values_list("evento_id_origem", flat=True)
        )
        assert restantes == {"dentro-recente", "dentro-limite"}

    def test_respeita_a_configuracao_quando_autorizado(
        self, settings: Any
    ) -> None:
        """Deve executar sem forçar quando a rotina está autorizada."""
        settings.AUDITORIA_EXPURGO_ATIVO = True
        settings.AUDITORIA_RETENCAO_DIAS = 30
        settings.AUDITORIA_EXPURGO_TAMANHO_LOTE = 1000

        self._gravar("fora-limite", dias_atras=90)

        resultado = expurgar_eventos_antigos()

        assert resultado["situacao"] == "executado"
        assert resultado["removidos"] == 1
        assert EventoAuditoria.objects.count() == 0

    def test_remove_em_lotes_sucessivos(self, settings: Any) -> None:
        """Deve concluir a remoção mesmo com lote menor que o volume."""
        settings.AUDITORIA_EXPURGO_ATIVO = True
        settings.AUDITORIA_RETENCAO_DIAS = 30
        settings.AUDITORIA_EXPURGO_TAMANHO_LOTE = 2

        for indice in range(5):
            self._gravar(f"antigo-{indice}", dias_atras=90)

        resultado = expurgar_eventos_antigos()

        assert resultado["removidos"] == 5
        assert EventoAuditoria.objects.count() == 0
