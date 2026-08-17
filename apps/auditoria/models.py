"""Modelos de persistência dos eventos de auditoria."""

import uuid

from django.db import models


class EventoAuditoria(models.Model):
    """Registra um evento de auditoria lido do Keycloak.

    ``evento_id_origem`` é a chave de deduplicação, e a restrição de
    unicidade sobre ela é o que garante, em definitivo, que o mesmo
    evento real nunca vire duas linhas. A leitura antecipada e o ciclo
    agendado podem se sobrepor — quando isso acontece, os dois
    processos chegam ao banco com a mesma chave e o segundo é
    rejeitado pela própria constraint, sem lock explícito nem consulta
    prévia por linha.

    ``detalhes`` guarda o payload bruto completo, não só os campos
    normalizados: o que hoje parece irrelevante pode ser exatamente o
    que uma apuração futura precisa, e o dado descartado na escrita
    não tem como ser recuperado depois.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    evento_id_origem = models.CharField(max_length=64, db_index=True)
    tipo_evento = models.CharField(max_length=50, db_index=True)
    usuario_id = models.CharField(max_length=64, null=True, blank=True)
    realm = models.CharField(max_length=100)
    client_id = models.CharField(max_length=100, null=True, blank=True)
    ip_origem = models.GenericIPAddressField(null=True, blank=True)
    timestamp_evento = models.DateTimeField(db_index=True)
    timestamp_recebimento = models.DateTimeField(auto_now_add=True)
    detalhes = models.JSONField(default=dict)

    class Meta:
        """Configurações de metadados do modelo."""

        verbose_name = "Evento de auditoria"
        verbose_name_plural = "Eventos de auditoria"
        constraints = [
            models.UniqueConstraint(
                fields=["evento_id_origem"],
                name="uniq_evento_auditoria_origem",
            )
        ]
        # As três combinações cobrem as consultas previstas de
        # apuração — por usuário, por sistema e por tipo de atividade,
        # sempre recortadas por período.
        indexes = [
            models.Index(fields=["usuario_id", "timestamp_evento"]),
            models.Index(fields=["client_id", "timestamp_evento"]),
            models.Index(fields=["tipo_evento", "timestamp_evento"]),
        ]

    def __str__(self) -> str:
        """Retorna o tipo do evento e o instante em que ocorreu."""
        return f"{self.tipo_evento} @ {self.timestamp_evento.isoformat()}"


class CheckpointCaptura(models.Model):
    """Marca até onde a leitura de eventos de um realm já avançou.

    Guardado no banco, e não em memória do worker, porque precisa
    sobreviver a reinício de processo: um checkpoint perdido faria a
    leitura seguinte reprocessar uma janela inteira já capturada.

    O avanço só acontece depois que os eventos da leitura foram
    entregues para escrita — parar no meio deixa o marcador onde
    estava, e a leitura seguinte cobre a mesma janela de novo, sem
    perder evento.

    ``canal`` distingue os dois fluxos de evento do Keycloak — eventos
    de usuário (login/logout/falha) e admin events (criação/edição de
    usuário e demais ações administrativas). Os dois têm timestamps
    e endpoints de consulta independentes; misturar os dois num único
    marcador por realm faria o avanço de um stream mascarar o avanço
    do outro.
    """

    CANAL_USUARIO = "usuario"
    CANAL_ADMIN = "admin"

    realm = models.CharField(max_length=100)
    canal = models.CharField(max_length=20, default=CANAL_USUARIO)
    ultimo_timestamp = models.BigIntegerField(default=0)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        """Configurações de metadados do modelo."""

        verbose_name = "Checkpoint de captura"
        verbose_name_plural = "Checkpoints de captura"
        constraints = [
            models.UniqueConstraint(
                fields=["realm", "canal"],
                name="uniq_checkpoint_captura_realm_canal",
            )
        ]

    def __str__(self) -> str:
        """Retorna o realm, canal e a posição atual do marcador."""
        return f"{self.realm}/{self.canal}: {self.ultimo_timestamp}"
