"""Testes de escrita, consulta e retenção dos eventos de auditoria."""

import datetime as dt
from typing import Any

import pytest
from django.utils import timezone

from apps.auditoria import servicos
from apps.auditoria.models import (
    EventoAuditoria,
    IdentificadorUsuarioAuditoria,
)
from apps.auditoria.servicos import (
    consultar_eventos,
    expurgar_eventos_antigos,
    persistir_lote,
    registrar_identificadores_usuario,
)

_INSTANTE_MS = 1786000000000
_IP_ORIGEM_TESTE = "203.0.113.10"
_REALM_ID_TESTE = "realm-id-cotic"


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
        "realm": _REALM_ID_TESTE,
        "client_id": "auto-servico-qa",
        "ip_origem": _IP_ORIGEM_TESTE,
        "timestamp_evento": timestamp_ms,
        "detalhes": {"username": "1234567"},
    }


@pytest.mark.django_db
class TestPersistirLote:
    """Testes de ``persistir_lote``."""

    def test_grava_lote_completo(self) -> None:
        """Deve gravar todos os eventos inéditos do lote."""
        resultado = persistir_lote(
            [
                _dados("a"),
                _dados("b"),
                _dados("c"),
            ]
        )

        assert resultado == {
            "recebidos": 3,
            "gravados": 3,
        }
        assert EventoAuditoria.objects.count() == 3

    def test_lote_vazio_nao_toca_o_banco(self) -> None:
        """Deve encerrar sem escrita quando não há o que gravar."""
        resultado = persistir_lote([])

        assert resultado == {
            "recebidos": 0,
            "gravados": 0,
        }
        assert EventoAuditoria.objects.count() == 0

    def test_converte_instante_para_data_com_fuso(self) -> None:
        """Deve traduzir o instante em milissegundos para data com fuso."""
        persistir_lote(
            [
                _dados(
                    "a",
                    timestamp_ms=_INSTANTE_MS,
                )
            ]
        )

        gravado = EventoAuditoria.objects.get(
            evento_id_origem="a",
        )

        esperado = dt.datetime.fromtimestamp(
            _INSTANTE_MS / 1000,
            tz=dt.UTC,
        )

        assert gravado.timestamp_evento == esperado

    def test_preserva_o_payload_bruto_em_detalhes(self) -> None:
        """Deve guardar o payload completo, não só os campos promovidos."""
        dados = _dados("a")
        dados["detalhes"] = {
            "username": "1234567",
            "campo_novo": "valor",
        }

        persistir_lote([dados])

        gravado = EventoAuditoria.objects.get(
            evento_id_origem="a",
        )

        assert gravado.detalhes["campo_novo"] == "valor"

    def test_normaliza_campos_ausentes_para_nulo(self) -> None:
        """Deve gravar como nulo o que veio vazio na origem."""
        dados = _dados("a")
        dados["usuario_id"] = ""
        dados["client_id"] = None
        dados["ip_origem"] = ""

        persistir_lote([dados])

        gravado = EventoAuditoria.objects.get(
            evento_id_origem="a",
        )

        assert gravado.usuario_id is None
        assert gravado.client_id is None
        assert gravado.ip_origem is None

    def test_reenvio_do_mesmo_evento_nao_duplica(self) -> None:
        """Deve descartar a repetição sem falhar a escrita."""
        persistir_lote([_dados("a")])

        resultado = persistir_lote([_dados("a")])

        assert resultado == {
            "recebidos": 1,
            "gravados": 0,
        }
        assert EventoAuditoria.objects.count() == 1

    def test_leituras_sobrepostas_geram_uma_unica_linha(
        self,
    ) -> None:
        """Deve manter uma linha só quando leituras trazem o mesmo evento."""
        lote_leitura_antecipada = [
            _dados("compartilhado"),
            _dados("so-do-1"),
        ]
        lote_ciclo_agendado = [
            _dados("compartilhado"),
            _dados("so-do-2"),
        ]

        primeiro = persistir_lote(lote_leitura_antecipada)
        segundo = persistir_lote(lote_ciclo_agendado)

        compartilhados = EventoAuditoria.objects.filter(
            evento_id_origem="compartilhado"
        ).count()

        assert compartilhados == 1
        assert EventoAuditoria.objects.count() == 3
        assert primeiro["gravados"] == 2
        assert segundo["gravados"] == 1

    def test_lote_com_repeticao_interna_grava_uma_vez(
        self,
    ) -> None:
        """Deve absorver a repetição dentro de um mesmo lote."""
        persistir_lote(
            [
                _dados("a"),
                _dados("a"),
                _dados("b"),
            ]
        )

        total = EventoAuditoria.objects.filter(evento_id_origem="a").count()

        assert total == 1
        assert EventoAuditoria.objects.count() == 2


@pytest.mark.django_db
class TestRegistrarIdentificadoresUsuario:
    """Testes de ``registrar_identificadores_usuario``."""

    def test_registra_email_cpf_e_rf_normalizados(self) -> None:
        """Deve persistir os identificadores conforme suas regras."""
        registrar_identificadores_usuario(
            realm=_REALM_ID_TESTE,
            identificadores={
                "usuario_id": "usuario-a",
                "email": "Teste.Usuario@TESTE.COM",
                "cpf": "123.456.789-01",
                "rf": "1234567",
            },
        )

        registros = {
            item.tipo: item.valor
            for item in IdentificadorUsuarioAuditoria.objects.filter(
                usuario_id="usuario-a"
            )
        }

        assert registros == {
            IdentificadorUsuarioAuditoria.Tipo.EMAIL: (
                "teste.usuario@teste.com"
            ),
            IdentificadorUsuarioAuditoria.Tipo.CPF: "12345678901",
            IdentificadorUsuarioAuditoria.Tipo.RF: "1234567",
        }

    def test_nao_registra_sem_usuario_id(self) -> None:
        """Deve ignorar identificadores sem usuário associado."""
        registrar_identificadores_usuario(
            realm=_REALM_ID_TESTE,
            identificadores={
                "usuario_id": None,
                "email": "teste@teste.com",
                "cpf": "12345678901",
                "rf": "1234567",
            },
        )

        assert IdentificadorUsuarioAuditoria.objects.count() == 0

    def test_nao_registra_identificadores_vazios(self) -> None:
        """Deve ignorar identificadores nulos ou vazios."""
        registrar_identificadores_usuario(
            realm=_REALM_ID_TESTE,
            identificadores={
                "usuario_id": "usuario-a",
                "email": "",
                "cpf": None,
                "rf": "",
            },
        )

        assert IdentificadorUsuarioAuditoria.objects.count() == 0

    def test_nao_duplica_identificadores_ja_registrados(
        self,
    ) -> None:
        """Deve absorver nova observação dos mesmos identificadores."""
        identificadores: dict[str, str | None] = {
            "usuario_id": "usuario-a",
            "email": "teste@teste.com",
            "cpf": "12345678901",
            "rf": "1234567",
        }

        registrar_identificadores_usuario(
            realm=_REALM_ID_TESTE,
            identificadores=identificadores,
        )
        registrar_identificadores_usuario(
            realm=_REALM_ID_TESTE,
            identificadores=identificadores,
        )

        assert IdentificadorUsuarioAuditoria.objects.count() == 3

    def test_preserva_email_antigo_quando_valor_muda(
        self,
    ) -> None:
        """Deve manter o histórico quando um identificador for alterado."""
        registrar_identificadores_usuario(
            realm=_REALM_ID_TESTE,
            identificadores={
                "usuario_id": "usuario-a",
                "email": "antigo@teste.com",
                "cpf": None,
                "rf": None,
            },
        )

        registrar_identificadores_usuario(
            realm=_REALM_ID_TESTE,
            identificadores={
                "usuario_id": "usuario-a",
                "email": "novo@teste.com",
                "cpf": None,
                "rf": None,
            },
        )

        emails = set(
            IdentificadorUsuarioAuditoria.objects.filter(
                usuario_id="usuario-a",
                tipo=IdentificadorUsuarioAuditoria.Tipo.EMAIL,
            ).values_list(
                "valor",
                flat=True,
            )
        )

        assert emails == {
            "antigo@teste.com",
            "novo@teste.com",
        }

    def test_normalizador_preserva_tipo_desconhecido(
        self,
    ) -> None:
        """Deve preservar o valor para tipos sem regra específica."""
        resultado = servicos._normalizar_valor_identificador(  # noqa: SLF001
            "OUTRO",
            " valor ",
        )

        assert resultado == " valor "


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
        realm: str = _REALM_ID_TESTE,
    ) -> EventoAuditoria:
        """Grava um evento com os atributos informados."""
        return EventoAuditoria.objects.create(
            evento_id_origem=chave,
            tipo_evento=tipo_evento,
            usuario_id=usuario_id,
            client_id=client_id,
            realm=realm,
            timestamp_evento=(
                timezone.now()
                - dt.timedelta(
                    days=dias_atras,
                )
            ),
            detalhes={},
        )

    def _registrar_identificador(
        self,
        *,
        usuario_id: str = "usuario-a",
        tipo: str,
        valor: str,
        realm: str = _REALM_ID_TESTE,
    ) -> None:
        """Registra um identificador utilizado nos testes de consulta."""
        IdentificadorUsuarioAuditoria.objects.create(
            realm=realm,
            usuario_id=usuario_id,
            tipo=tipo,
            valor=valor,
        )

    def test_sem_filtro_retorna_tudo_do_mais_recente(
        self,
    ) -> None:
        """Deve devolver todos os eventos, do mais recente ao mais antigo."""
        self._gravar(
            "antigo",
            dias_atras=5,
        )
        self._gravar(
            "recente",
            dias_atras=0,
        )

        resultado = list(consultar_eventos())

        assert [evento.evento_id_origem for evento in resultado] == [
            "recente",
            "antigo",
        ]

    def test_filtra_por_usuario(self) -> None:
        """Deve restringir aos eventos do usuário informado."""
        self._gravar(
            "do-usuario-a",
            usuario_id="usuario-a",
        )
        self._gravar(
            "do-usuario-b",
            usuario_id="usuario-b",
        )

        resultado = consultar_eventos(usuario_id="usuario-a")

        assert [evento.evento_id_origem for evento in resultado] == [
            "do-usuario-a"
        ]

    def test_filtra_por_email(self) -> None:
        """Deve resolver o e-mail para o usuário correspondente."""
        self._gravar(
            "evento-a",
            usuario_id="usuario-a",
        )
        self._gravar(
            "evento-b",
            usuario_id="usuario-b",
        )

        self._registrar_identificador(
            usuario_id="usuario-a",
            tipo=IdentificadorUsuarioAuditoria.Tipo.EMAIL,
            valor="teste@teste.com",
        )

        resultado = consultar_eventos(usuario_id="TESTE@TESTE.COM")

        assert [evento.evento_id_origem for evento in resultado] == [
            "evento-a"
        ]

    def test_filtra_por_email_historico(self) -> None:
        """Deve localizar os eventos usando também um e-mail antigo."""
        self._gravar(
            "evento-a",
            usuario_id="usuario-a",
        )

        self._registrar_identificador(
            usuario_id="usuario-a",
            tipo=IdentificadorUsuarioAuditoria.Tipo.EMAIL,
            valor="antigo@teste.com",
        )
        self._registrar_identificador(
            usuario_id="usuario-a",
            tipo=IdentificadorUsuarioAuditoria.Tipo.EMAIL,
            valor="novo@teste.com",
        )

        antigo = consultar_eventos(usuario_id="antigo@teste.com")
        novo = consultar_eventos(usuario_id="novo@teste.com")

        assert [evento.evento_id_origem for evento in antigo] == ["evento-a"]

        assert [evento.evento_id_origem for evento in novo] == ["evento-a"]

    def test_filtra_por_cpf_formatado(self) -> None:
        """Deve normalizar o CPF antes de resolver o usuário."""
        self._gravar(
            "evento-a",
            usuario_id="usuario-a",
        )

        self._registrar_identificador(
            usuario_id="usuario-a",
            tipo=IdentificadorUsuarioAuditoria.Tipo.CPF,
            valor="12345678901",
        )

        resultado = consultar_eventos(usuario_id="123.456.789-01")

        assert [evento.evento_id_origem for evento in resultado] == [
            "evento-a"
        ]

    def test_filtra_por_rf(self) -> None:
        """Deve resolver o RF para o usuário correspondente."""
        self._gravar(
            "evento-a",
            usuario_id="usuario-a",
        )

        self._registrar_identificador(
            usuario_id="usuario-a",
            tipo=IdentificadorUsuarioAuditoria.Tipo.RF,
            valor="1234567",
        )

        resultado = consultar_eventos(usuario_id="1234567")

        assert [evento.evento_id_origem for evento in resultado] == [
            "evento-a"
        ]

    def test_respeita_realm_ao_resolver_identificador(
        self,
    ) -> None:
        """Deve evitar eventos de outro realm com o mesmo usuario_id."""
        self._gravar(
            "realm-correto",
            usuario_id="usuario-a",
            realm="realm-a",
        )
        self._gravar(
            "outro-realm",
            usuario_id="usuario-a",
            realm="realm-b",
        )

        self._registrar_identificador(
            usuario_id="usuario-a",
            tipo=IdentificadorUsuarioAuditoria.Tipo.EMAIL,
            valor="teste@teste.com",
            realm="realm-a",
        )

        resultado = consultar_eventos(usuario_id="teste@teste.com")

        assert [evento.evento_id_origem for evento in resultado] == [
            "realm-correto"
        ]

    def test_identificador_pode_resolver_multiplos_usuarios(
        self,
    ) -> None:
        """Deve retornar todos os usuários historicamente associados."""
        self._gravar(
            "usuario-a",
            usuario_id="usuario-a",
        )
        self._gravar(
            "usuario-b",
            usuario_id="usuario-b",
        )

        self._registrar_identificador(
            usuario_id="usuario-a",
            tipo=IdentificadorUsuarioAuditoria.Tipo.EMAIL,
            valor="compartilhado@teste.com",
        )
        self._registrar_identificador(
            usuario_id="usuario-b",
            tipo=IdentificadorUsuarioAuditoria.Tipo.EMAIL,
            valor="compartilhado@teste.com",
        )

        resultado = consultar_eventos(usuario_id="compartilhado@teste.com")

        chaves = {evento.evento_id_origem for evento in resultado}

        assert chaves == {
            "usuario-a",
            "usuario-b",
        }

    def test_identificador_em_branco_nao_encontra_eventos(
        self,
    ) -> None:
        """Deve tratar um identificador formado apenas por espaços."""
        self._gravar(
            "evento-a",
            usuario_id="usuario-a",
        )

        resultado = consultar_eventos(usuario_id="   ")

        assert list(resultado) == []

    def test_filtra_por_sistema(self) -> None:
        """Deve restringir aos eventos do sistema informado."""
        self._gravar(
            "do-sistema-a",
            client_id="sistema-a",
        )
        self._gravar(
            "do-sistema-b",
            client_id="sistema-b",
        )

        resultado = consultar_eventos(client_id="sistema-a")

        assert [evento.evento_id_origem for evento in resultado] == [
            "do-sistema-a"
        ]

    def test_filtra_por_tipo_evento(self) -> None:
        """Deve restringir aos eventos do tipo informado."""
        self._gravar(
            "login",
            tipo_evento="LOGIN",
        )
        self._gravar(
            "logout",
            tipo_evento="LOGOUT",
        )

        resultado = consultar_eventos(tipo_evento="LOGOUT")

        assert [evento.evento_id_origem for evento in resultado] == ["logout"]

    def test_filtra_por_periodo(self) -> None:
        """Deve restringir ao intervalo de datas informado, inclusive."""
        self._gravar(
            "fora-antes",
            dias_atras=10,
        )
        self._gravar(
            "dentro",
            dias_atras=5,
        )
        self._gravar(
            "fora-depois",
            dias_atras=0,
        )

        agora = timezone.now()

        resultado = consultar_eventos(
            data_inicio=(
                agora
                - dt.timedelta(
                    days=7,
                )
            ),
            data_fim=(
                agora
                - dt.timedelta(
                    days=3,
                )
            ),
        )

        assert [evento.evento_id_origem for evento in resultado] == ["dentro"]

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

        assert [evento.evento_id_origem for evento in resultado] == ["combina"]


@pytest.mark.django_db
class TestExpurgarEventosAntigos:
    """Testes de ``expurgar_eventos_antigos``."""

    def _gravar(
        self,
        chave: str,
        dias_atras: int,
    ) -> None:
        """Grava um evento com a idade informada."""
        EventoAuditoria.objects.create(
            evento_id_origem=chave,
            tipo_evento="LOGIN",
            realm=_REALM_ID_TESTE,
            timestamp_evento=(
                timezone.now()
                - dt.timedelta(
                    days=dias_atras,
                )
            ),
            detalhes={},
        )

    def test_nao_remove_nada_com_a_rotina_desligada(
        self,
        settings: Any,
    ) -> None:
        """Deve preservar tudo enquanto a remoção não estiver autorizada."""
        settings.AUDITORIA_EXPURGO_ATIVO = False
        settings.AUDITORIA_RETENCAO_DIAS = 30

        self._gravar(
            "antigo",
            dias_atras=400,
        )

        resultado = expurgar_eventos_antigos()

        assert resultado["situacao"] == "desativado"
        assert resultado["removidos"] == 0
        assert EventoAuditoria.objects.count() == 1

    def test_executa_sem_remover_quando_nao_ha_eventos_expirados(
        self,
        settings: Any,
    ) -> None:
        """Deve encerrar normalmente quando nenhum evento passou do corte."""
        settings.AUDITORIA_EXPURGO_ATIVO = True
        settings.AUDITORIA_RETENCAO_DIAS = 30
        settings.AUDITORIA_EXPURGO_TAMANHO_LOTE = 1000

        self._gravar(
            "recente",
            dias_atras=1,
        )

        resultado = expurgar_eventos_antigos()

        assert resultado["situacao"] == "executado"
        assert resultado["removidos"] == 0
        assert EventoAuditoria.objects.count() == 1

    def test_remove_apenas_fora_do_periodo_de_retencao(
        self,
        settings: Any,
    ) -> None:
        """Deve remover só o que já passou do período configurado."""
        settings.AUDITORIA_EXPURGO_ATIVO = False
        settings.AUDITORIA_RETENCAO_DIAS = 30
        settings.AUDITORIA_EXPURGO_TAMANHO_LOTE = 1000

        self._gravar(
            "dentro-recente",
            dias_atras=1,
        )
        self._gravar(
            "dentro-limite",
            dias_atras=29,
        )
        self._gravar(
            "fora-limite",
            dias_atras=31,
        )
        self._gravar(
            "fora-antigo",
            dias_atras=400,
        )

        resultado = expurgar_eventos_antigos(forcar=True)

        assert resultado["situacao"] == "executado"
        assert resultado["removidos"] == 2

        restantes = set(
            EventoAuditoria.objects.values_list(
                "evento_id_origem",
                flat=True,
            )
        )

        assert restantes == {
            "dentro-recente",
            "dentro-limite",
        }

    def test_respeita_a_configuracao_quando_autorizado(
        self,
        settings: Any,
    ) -> None:
        """Deve executar sem forçar quando a rotina está autorizada."""
        settings.AUDITORIA_EXPURGO_ATIVO = True
        settings.AUDITORIA_RETENCAO_DIAS = 30
        settings.AUDITORIA_EXPURGO_TAMANHO_LOTE = 1000

        self._gravar(
            "fora-limite",
            dias_atras=90,
        )

        resultado = expurgar_eventos_antigos()

        assert resultado["situacao"] == "executado"
        assert resultado["removidos"] == 1
        assert EventoAuditoria.objects.count() == 0

    def test_remove_em_lotes_sucessivos(
        self,
        settings: Any,
    ) -> None:
        """Deve concluir a remoção mesmo com lote menor que o volume."""
        settings.AUDITORIA_EXPURGO_ATIVO = True
        settings.AUDITORIA_RETENCAO_DIAS = 30
        settings.AUDITORIA_EXPURGO_TAMANHO_LOTE = 2

        for indice in range(5):
            self._gravar(
                f"antigo-{indice}",
                dias_atras=90,
            )

        resultado = expurgar_eventos_antigos()

        assert resultado["removidos"] == 5
        assert EventoAuditoria.objects.count() == 0
