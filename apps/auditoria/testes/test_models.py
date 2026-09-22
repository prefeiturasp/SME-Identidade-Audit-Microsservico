"""Testes dos modelos de auditoria."""

import datetime as dt

import pytest
from django.db import IntegrityError, transaction

from apps.auditoria.models import (
    CheckpointCaptura,
    EventoAuditoria,
    IdentificadorUsuarioAuditoria,
)


def _evento(
    evento_id_origem: str = "chave-a",
    tipo_evento: str = "LOGIN",
) -> EventoAuditoria:
    """Monta um evento válido para os testes."""
    return EventoAuditoria(
        evento_id_origem=evento_id_origem,
        tipo_evento=tipo_evento,
        usuario_id="5c29cc47",
        realm="COTIC",
        client_id="auto-servico-qa",
        ip_origem="203.0.113.10",
        timestamp_evento=dt.datetime(
            2026,
            8,
            11,
            12,
            0,
            tzinfo=dt.UTC,
        ),
        detalhes={"username": "1234567"},
    )


def _identificador(
    *,
    usuario_id: str = "5c29cc47",
    realm: str = "realm-id-cotic",
    tipo: str = IdentificadorUsuarioAuditoria.Tipo.EMAIL,
    valor: str = "teste@teste.com",
) -> IdentificadorUsuarioAuditoria:
    """Monta um identificador válido para os testes."""
    return IdentificadorUsuarioAuditoria(
        usuario_id=usuario_id,
        realm=realm,
        tipo=tipo,
        valor=valor,
    )


@pytest.mark.django_db
class TestEventoAuditoria:
    """Testes de ``EventoAuditoria``."""

    def test_grava_e_recupera_evento(self) -> None:
        """Deve persistir o evento com os campos informados."""
        _evento().save()

        gravado = EventoAuditoria.objects.get(
            evento_id_origem="chave-a",
        )

        assert gravado.tipo_evento == "LOGIN"
        assert gravado.realm == "COTIC"
        assert gravado.detalhes == {"username": "1234567"}
        assert gravado.timestamp_recebimento is not None

    def test_rejeita_chave_de_origem_repetida(self) -> None:
        """Deve barrar no banco a segunda gravação da mesma chave."""
        _evento().save()

        duplicado = _evento(
            tipo_evento="LOGOUT",
        )

        with pytest.raises(IntegrityError), transaction.atomic():
            duplicado.save()

    def test_aceita_chaves_de_origem_distintas(self) -> None:
        """Deve permitir eventos diferentes lado a lado."""
        _evento("chave-a").save()
        _evento(
            "chave-b",
            tipo_evento="LOGOUT",
        ).save()

        assert EventoAuditoria.objects.count() == 2

    def test_representacao_textual_traz_tipo_e_instante(self) -> None:
        """Deve identificar o evento pelo tipo e pelo instante."""
        evento = _evento()

        assert "LOGIN" in str(evento)
        assert "2026-08-11" in str(evento)

    def test_declara_os_indices_compostos_previstos(self) -> None:
        """Deve manter os índices que sustentam as consultas de apuração."""
        combinacoes = {
            tuple(indice.fields)
            for indice in EventoAuditoria._meta.indexes  # noqa: SLF001
        }

        assert ("usuario_id", "timestamp_evento") in combinacoes
        assert ("client_id", "timestamp_evento") in combinacoes
        assert ("tipo_evento", "timestamp_evento") in combinacoes

    def test_declara_a_restricao_de_unicidade_da_chave(self) -> None:
        """Deve manter a restrição que sustenta a deduplicação."""
        nomes = {
            restricao.name
            for restricao in EventoAuditoria._meta.constraints  # noqa: SLF001
        }

        assert "uniq_evento_auditoria_origem" in nomes


@pytest.mark.django_db
class TestCheckpointCaptura:
    """Testes de ``CheckpointCaptura``."""

    def test_grava_marcador_por_realm(self) -> None:
        """Deve guardar a posição da captura de cada realm."""
        CheckpointCaptura.objects.create(
            realm="COTIC",
            ultimo_timestamp=1000,
        )

        checkpoint = CheckpointCaptura.objects.get(
            realm="COTIC",
        )

        assert checkpoint.ultimo_timestamp == 1000

    def test_canal_padrao_e_usuario(self) -> None:
        """Deve assumir o canal de usuário quando não informado.

        Compatibilidade com marcadores gravados antes do canal de
        admin events existir — uma linha antiga, sem o campo
        preenchido explicitamente, continua representando a captura
        do canal de usuário.
        """
        checkpoint = CheckpointCaptura.objects.create(
            realm="COTIC",
            ultimo_timestamp=1000,
        )

        assert checkpoint.canal == CheckpointCaptura.CANAL_USUARIO

    def test_permite_um_marcador_por_realm_e_canal(self) -> None:
        """Deve aceitar marcadores distintos para o mesmo realm.

        Um por canal — o mesmo realm tem uma captura de eventos de
        usuário e uma de admin events, cada uma com sua posição.
        """
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

        total = CheckpointCaptura.objects.filter(
            realm="COTIC",
        ).count()

        assert total == 2

    def test_rejeita_realm_e_canal_repetidos(self) -> None:
        """Deve barrar no banco um segundo marcador do mesmo realm/canal."""
        CheckpointCaptura.objects.create(
            realm="COTIC",
            canal=CheckpointCaptura.CANAL_USUARIO,
            ultimo_timestamp=1000,
        )

        duplicado = CheckpointCaptura(
            realm="COTIC",
            canal=CheckpointCaptura.CANAL_USUARIO,
            ultimo_timestamp=2000,
        )

        with pytest.raises(IntegrityError), transaction.atomic():
            duplicado.save()

    def test_representacao_textual_traz_realm_canal_e_posicao(self) -> None:
        """Deve identificar o marcador pelo realm, canal e posição."""
        checkpoint = CheckpointCaptura(
            realm="COTIC",
            canal=CheckpointCaptura.CANAL_ADMIN,
            ultimo_timestamp=1000,
        )

        assert str(checkpoint) == "COTIC/admin: 1000"


@pytest.mark.django_db
class TestIdentificadorUsuarioAuditoria:
    """Testes de ``IdentificadorUsuarioAuditoria``."""

    def test_grava_e_recupera_identificador(self) -> None:
        """Deve persistir um identificador associado ao usuário."""
        _identificador().save()

        gravado = IdentificadorUsuarioAuditoria.objects.get(
            usuario_id="5c29cc47",
            tipo=IdentificadorUsuarioAuditoria.Tipo.EMAIL,
        )

        assert gravado.realm == "realm-id-cotic"
        assert gravado.valor == "teste@teste.com"
        assert gravado.criado_em is not None

    def test_permite_historico_do_mesmo_tipo_para_usuario(self) -> None:
        """Deve preservar valores antigos quando o identificador mudar."""
        _identificador(
            valor="antigo@teste.com",
        ).save()

        _identificador(
            valor="novo@teste.com",
        ).save()

        valores = set(
            IdentificadorUsuarioAuditoria.objects.filter(
                usuario_id="5c29cc47",
                tipo=IdentificadorUsuarioAuditoria.Tipo.EMAIL,
            ).values_list(
                "valor",
                flat=True,
            )
        )

        assert valores == {
            "antigo@teste.com",
            "novo@teste.com",
        }

    def test_rejeita_identificador_exatamente_repetido(self) -> None:
        """Deve impedir a duplicação do mesmo identificador do usuário."""
        _identificador().save()

        duplicado = _identificador()

        with pytest.raises(IntegrityError), transaction.atomic():
            duplicado.save()

    def test_permite_mesmo_identificador_para_usuarios_distintos(
        self,
    ) -> None:
        """Deve permitir reutilização histórica por outro usuário."""
        _identificador(
            usuario_id="usuario-a",
            valor="compartilhado@teste.com",
        ).save()

        _identificador(
            usuario_id="usuario-b",
            valor="compartilhado@teste.com",
        ).save()

        total = IdentificadorUsuarioAuditoria.objects.filter(
            valor="compartilhado@teste.com",
        ).count()

        assert total == 2

    def test_representacao_textual_traz_tipo_valor_e_usuario(self) -> None:
        """Deve identificar claramente o vínculo histórico."""
        identificador = _identificador(
            usuario_id="usuario-123",
            tipo=IdentificadorUsuarioAuditoria.Tipo.CPF,
            valor="12345678901",
        )

        assert str(identificador) == ("CPF: 12345678901 -> usuario-123")

    def test_declara_a_restricao_de_unicidade(self) -> None:
        """Deve manter a restrição usada para evitar duplicações."""
        nomes = {
            restricao.name
            for restricao in IdentificadorUsuarioAuditoria._meta.constraints  # noqa: SLF001
        }

        assert "uniq_identificador_usuario_auditoria" in nomes

    def test_declara_os_indices_de_busca(self) -> None:
        """Deve manter os índices usados na resolução dos usuários."""
        indices = {
            indice.name: tuple(indice.fields)
            for indice in IdentificadorUsuarioAuditoria._meta.indexes  # noqa: SLF001
        }

        assert indices["idx_ident_auditoria_busca"] == (
            "realm",
            "tipo",
            "valor",
        )

        assert indices["idx_ident_auditoria_usuario"] == (
            "realm",
            "usuario_id",
        )
