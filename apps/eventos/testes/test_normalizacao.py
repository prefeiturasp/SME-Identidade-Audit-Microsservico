"""Testes da tradução do evento bruto do Keycloak."""

import json
from typing import Any

from apps.eventos.normalizacao import (
    calcular_admin_event_id_origem,
    calcular_evento_id_origem,
    normalizar_admin_event,
    normalizar_evento,
)


def _bruto(**sobrescritas: Any) -> dict[str, Any]:
    """Monta um evento no formato devolvido pelo Keycloak."""
    evento = {
        "time": 1786000000000,
        "type": "LOGIN",
        "realmId": "COTIC",
        "clientId": "auto-servico-qa",
        "userId": "5c29cc47-0000-0000-0000-000000000000",
        "sessionId": "sessao-1",
        "ipAddress": "203.0.113.10",
        "details": {"username": "1234567", "auth_method": "openid-connect"},
    }
    evento.update(sobrescritas)
    return evento


class TestCalcularEventoIdOrigem:
    """Testes de ``calcular_evento_id_origem``."""

    def test_mesma_entrada_produz_a_mesma_chave(self) -> None:
        """Deve derivar a mesma chave para o mesmo evento real."""
        assert calcular_evento_id_origem(_bruto()) == (
            calcular_evento_id_origem(_bruto())
        )

    def test_chave_tem_tamanho_estavel(self) -> None:
        """Deve caber no campo indexado, com tamanho previsível."""
        chave = calcular_evento_id_origem(_bruto())

        assert len(chave) == 32
        assert chave.isalnum()

    def test_instantes_distintos_produzem_chaves_distintas(self) -> None:
        """Deve separar duas ocorrências em instantes diferentes."""
        primeira = calcular_evento_id_origem(_bruto())
        segunda = calcular_evento_id_origem(_bruto(time=1786000000001))

        assert primeira != segunda

    def test_tipos_distintos_produzem_chaves_distintas(self) -> None:
        """Deve separar atividades diferentes no mesmo instante."""
        primeira = calcular_evento_id_origem(_bruto())
        segunda = calcular_evento_id_origem(_bruto(type="LOGOUT"))

        assert primeira != segunda

    def test_usuarios_distintos_produzem_chaves_distintas(self) -> None:
        """Deve separar a atividade de usuários diferentes."""
        primeira = calcular_evento_id_origem(_bruto())
        segunda = calcular_evento_id_origem(_bruto(userId="outro-usuario"))

        assert primeira != segunda

    def test_sessoes_distintas_produzem_chaves_distintas(self) -> None:
        """Deve separar ocorrências que só diferem pela sessão."""
        primeira = calcular_evento_id_origem(_bruto())
        segunda = calcular_evento_id_origem(_bruto(sessionId="sessao-2"))

        assert primeira != segunda

    def test_campos_ausentes_nao_impedem_o_calculo(self) -> None:
        """Deve derivar a chave mesmo com campos faltando na origem."""
        chave = calcular_evento_id_origem({"type": "LOGIN"})

        assert len(chave) == 32

    def test_ausencia_e_valor_nulo_produzem_a_mesma_chave(self) -> None:
        """Deve tratar campo ausente e campo nulo do mesmo jeito."""
        sem_campo = calcular_evento_id_origem(
            {"type": "LOGIN", "realmId": "COTIC"}
        )
        com_nulo = calcular_evento_id_origem(
            {
                "type": "LOGIN",
                "realmId": "COTIC",
                "userId": None,
                "sessionId": None,
                "time": None,
            }
        )

        assert sem_campo == com_nulo

    def test_usa_a_sessao_aninhada_em_detalhes(self) -> None:
        """Deve aceitar a sessão vinda dentro do detalhamento."""
        aninhada = _bruto(details={"sessionId": "sessao-1"})
        del aninhada["sessionId"]

        assert calcular_evento_id_origem(aninhada) == (
            calcular_evento_id_origem(_bruto(details={}))
        )


class TestNormalizarEvento:
    """Testes de ``normalizar_evento``."""

    def test_promove_os_campos_previstos(self) -> None:
        """Deve mapear o payload do Keycloak para o formato de escrita."""
        normalizado = normalizar_evento(_bruto(), realm_padrao="COTIC")

        assert normalizado["tipo_evento"] == "LOGIN"
        assert normalizado["realm"] == "COTIC"
        assert normalizado["client_id"] == "auto-servico-qa"
        assert normalizado["ip_origem"] == "203.0.113.10"
        assert normalizado["timestamp_evento"] == 1786000000000
        assert normalizado["usuario_id"] == (
            "5c29cc47-0000-0000-0000-000000000000"
        )

    def test_preserva_o_payload_bruto_completo(self) -> None:
        """Deve guardar o evento inteiro, não só os campos promovidos."""
        bruto = _bruto(campo_desconhecido="valor")

        normalizado = normalizar_evento(bruto, realm_padrao="COTIC")

        assert normalizado["detalhes"] == bruto
        assert normalizado["detalhes"]["campo_desconhecido"] == "valor"

    def test_assume_o_realm_da_consulta_quando_ausente(self) -> None:
        """Deve completar o realm que a resposta não trouxe."""
        bruto = _bruto()
        del bruto["realmId"]

        normalizado = normalizar_evento(bruto, realm_padrao="COTIC")

        assert normalizado["realm"] == "COTIC"

    def test_chave_coincide_com_e_sem_realm_na_origem(self) -> None:
        """Deve derivar a mesma chave venha ou não o realm na resposta.

        As duas leituras do mesmo evento precisam coincidir na chave,
        senão a deduplicação deixa passar uma duplicata.
        """
        sem_realm = _bruto()
        del sem_realm["realmId"]

        com_realm = normalizar_evento(_bruto(), realm_padrao="COTIC")
        sem = normalizar_evento(sem_realm, realm_padrao="COTIC")

        assert com_realm["evento_id_origem"] == sem["evento_id_origem"]

    def test_campos_vazios_viram_nulo(self) -> None:
        """Deve converter ausência na origem em nulo no destino."""
        normalizado = normalizar_evento(
            {"type": "LOGIN", "time": 1786000000000},
            realm_padrao="COTIC",
        )

        assert normalizado["usuario_id"] is None
        assert normalizado["client_id"] is None
        assert normalizado["ip_origem"] is None


def _admin_bruto(**sobrescritas: Any) -> dict[str, Any]:
    """Monta um admin event no formato real devolvido pelo Keycloak.

    Baseado no evento observado em QA ao criar um usuário via Admin
    API (ver Memorias/plano_teste_audit/config_keycloak.md).
    """
    evento = {
        "id": "354c785c-b24a-42d2-92de-d9cd77afe4f7",
        "time": 1786496262500,
        "realmId": "COTIC",
        "authDetails": {
            "realmId": "933c2e91-9a7e-408a-9dd3-97c9aa1c5336",
            "clientId": "0d06cf29-d522-4fb9-ad68-e8079dbb468c",
            "userId": "eced19ec-2b8a-4d8f-84fb-f2d586e14f74",
            "ipAddress": "203.0.113.20",
        },
        "operationType": "CREATE",
        "resourceType": "USER",
        "resourcePath": "users/b63a36e7-61fd-449b-8d2c-8f684249ac1f",
        "representation": json.dumps(
            {"username": "teste-audit-adminevents", "enabled": True}
        ),
    }
    evento.update(sobrescritas)
    return evento


class TestCalcularAdminEventIdOrigem:
    """Testes de ``calcular_admin_event_id_origem``."""

    def test_usa_o_id_nativo_quando_presente(self) -> None:
        """Deve usar o id do Keycloak diretamente, sem calcular hash."""
        chave = calcular_admin_event_id_origem(_admin_bruto())

        assert chave == "354c785c-b24a-42d2-92de-d9cd77afe4f7"

    def test_calcula_hash_quando_sem_id_nativo(self) -> None:
        """Deve cair para o hash composto se o id não vier na resposta."""
        sem_id = _admin_bruto()
        del sem_id["id"]

        chave = calcular_admin_event_id_origem(sem_id)

        assert chave != ""
        assert len(chave) == 32

    def test_mesma_entrada_sem_id_produz_a_mesma_chave(self) -> None:
        """Deve derivar a mesma chave de hash para o mesmo evento real."""
        sem_id_a = _admin_bruto()
        del sem_id_a["id"]
        sem_id_b = _admin_bruto()
        del sem_id_b["id"]

        assert calcular_admin_event_id_origem(
            sem_id_a
        ) == calcular_admin_event_id_origem(sem_id_b)

    def test_operacoes_distintas_sem_id_produzem_chaves_distintas(
        self,
    ) -> None:
        """Deve separar operações diferentes quando cai no hash."""
        primeira = _admin_bruto(operationType="CREATE")
        segunda = _admin_bruto(operationType="DELETE")
        del primeira["id"]
        del segunda["id"]

        assert calcular_admin_event_id_origem(
            primeira
        ) != calcular_admin_event_id_origem(segunda)


class TestNormalizarAdminEvent:
    """Testes de ``normalizar_admin_event``."""

    def test_combina_operacao_e_recurso_no_tipo_evento(self) -> None:
        """Deve compor um tipo de evento consultável junto do outro canal."""
        normalizado = normalizar_admin_event(
            _admin_bruto(), realm_padrao="COTIC"
        )

        assert normalizado["tipo_evento"] == "ADMIN_USER_CREATE"

    def test_usa_o_id_nativo_como_evento_id_origem(self) -> None:
        """Deve usar o id nativo como chave de deduplicação."""
        normalizado = normalizar_admin_event(
            _admin_bruto(), realm_padrao="COTIC"
        )

        assert normalizado["evento_id_origem"] == (
            "354c785c-b24a-42d2-92de-d9cd77afe4f7"
        )

    def test_usuario_id_vem_de_quem_executou_a_acao(self) -> None:
        """Deve registrar quem executou a operação, não quem foi afetado.

        O usuário afetado (ex. o usuário criado) não aparece como
        campo direto no admin event — só quem executou a ação
        (``authDetails.userId``). Quem foi afetado fica em
        ``detalhes.representation``.
        """
        normalizado = normalizar_admin_event(
            _admin_bruto(), realm_padrao="COTIC"
        )

        assert normalizado["usuario_id"] == (
            "eced19ec-2b8a-4d8f-84fb-f2d586e14f74"
        )

    def test_client_id_e_ip_vem_de_auth_details(self) -> None:
        """Deve extrair client_id/ip_origem de dentro de authDetails."""
        normalizado = normalizar_admin_event(
            _admin_bruto(), realm_padrao="COTIC"
        )

        assert normalizado["client_id"] == (
            "0d06cf29-d522-4fb9-ad68-e8079dbb468c"
        )
        assert normalizado["ip_origem"] == "203.0.113.20"

    def test_decodifica_representation_para_objeto(self) -> None:
        """Deve converter o representation (string JSON) em objeto.

        Evita que quem consultar ``detalhes`` precise fazer um
        segundo parse manual do payload da operação.
        """
        normalizado = normalizar_admin_event(
            _admin_bruto(), realm_padrao="COTIC"
        )

        assert normalizado["detalhes"]["representation"] == {
            "username": "teste-audit-adminevents",
            "enabled": True,
        }

    def test_representation_malformado_nao_impede_a_normalizacao(
        self,
    ) -> None:
        """Deve manter o representation cru se não for um JSON válido."""
        bruto = _admin_bruto(representation="nao-e-json-valido")

        normalizado = normalizar_admin_event(bruto, realm_padrao="COTIC")

        assert normalizado["detalhes"]["representation"] == (
            "nao-e-json-valido"
        )

    def test_sem_representation_nao_falha(self) -> None:
        """Deve normalizar sem erro quando não há representation.

        Acontece com adminEventsDetailsEnabled desligado, ou em
        operações que não carregam payload (ex. DELETE).
        """
        bruto = _admin_bruto()
        del bruto["representation"]

        normalizado = normalizar_admin_event(bruto, realm_padrao="COTIC")

        assert "representation" not in normalizado["detalhes"]

    def test_assume_o_realm_da_consulta_quando_ausente(self) -> None:
        """Deve completar o realm que a resposta não trouxe."""
        bruto = _admin_bruto()
        del bruto["realmId"]

        normalizado = normalizar_admin_event(bruto, realm_padrao="COTIC")

        assert normalizado["realm"] == "COTIC"

    def test_preserva_o_payload_bruto_completo(self) -> None:
        """Deve guardar o evento inteiro em detalhes, campos promovidos.

        A representation decodificada substitui a versão em string,
        mas o restante do payload (operationType, resourceType etc.)
        segue presente.
        """
        normalizado = normalizar_admin_event(
            _admin_bruto(), realm_padrao="COTIC"
        )

        assert normalizado["detalhes"]["operationType"] == "CREATE"
        assert normalizado["detalhes"]["resourceType"] == "USER"
