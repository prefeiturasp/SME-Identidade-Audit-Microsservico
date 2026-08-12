"""Serializers da API de consulta de eventos de auditoria."""

from rest_framework import serializers

from apps.auditoria.models import EventoAuditoria


class EventoAuditoriaSerializer(serializers.ModelSerializer):
    """Representa um evento de auditoria na resposta da consulta."""

    class Meta:
        """Configurações de metadados do serializer."""

        model = EventoAuditoria
        fields = [
            "id",
            "evento_id_origem",
            "tipo_evento",
            "usuario_id",
            "realm",
            "client_id",
            "ip_origem",
            "timestamp_evento",
            "timestamp_recebimento",
            "detalhes",
        ]


class EventoAuditoriaFiltroSerializer(serializers.Serializer):
    """Valida os parâmetros de filtro da consulta de eventos.

    Existe só para validação e documentação OpenAPI — a querystring
    já chega validada à view antes de a consulta em si ser montada em
    ``apps.auditoria.servicos.consultar_eventos``.
    """

    usuario_id = serializers.CharField(required=False)
    client_id = serializers.CharField(required=False)
    tipo_evento = serializers.CharField(required=False)
    data_inicio = serializers.DateTimeField(required=False)
    data_fim = serializers.DateTimeField(required=False)
