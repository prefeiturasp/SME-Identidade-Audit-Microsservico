"""Views da API da aplicação auditoria."""

from __future__ import annotations

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response

from apps.auditoria.api.paginacao import PaginacaoEventoAuditoria
from apps.auditoria.api.serializers import (
    EventoAuditoriaFiltroSerializer,
    EventoAuditoriaSerializer,
)
from apps.auditoria.models import EventoAuditoria
from apps.auditoria.servicos import consultar_eventos
from apps.autenticacao.api_key import AutenticacaoApiKey

_TAG = ["Auditoria"]


class EventoAuditoriaListView(ListAPIView):
    """Consulta eventos de auditoria já persistidos, com filtros.

    Não expõe escrita: a única forma de um evento chegar à base é via
    captura a partir do Keycloak (``apps.eventos``), nunca por este
    endpoint.
    """

    authentication_classes = [AutenticacaoApiKey]
    serializer_class = EventoAuditoriaSerializer
    pagination_class = PaginacaoEventoAuditoria

    @extend_schema(
        tags=_TAG,
        summary="Consultar eventos de auditoria",
        description=(
            "Lista eventos de auditoria já persistidos, filtráveis "
            "por usuário, sistema, tipo de evento e período. "
            "Paginado, 100 registros por página por padrão "
            "(configurável via `page_size`, teto de 1000)."
        ),
        parameters=[
            OpenApiParameter(
                "usuario_id",
                str,
                description="Identificador do usuário no Keycloak.",
            ),
            OpenApiParameter(
                "client_id",
                str,
                description="Sistema de origem do evento.",
            ),
            OpenApiParameter(
                "tipo_evento",
                str,
                description="Tipo do evento (LOGIN, LOGOUT etc.).",
            ),
            OpenApiParameter(
                "data_inicio",
                str,
                description="Data/hora mínima do evento (ISO 8601).",
            ),
            OpenApiParameter(
                "data_fim",
                str,
                description="Data/hora máxima do evento (ISO 8601).",
            ),
            OpenApiParameter(
                "page_size",
                int,
                description="Registros por página (padrão 100, teto 1000).",
            ),
        ],
        responses=EventoAuditoriaSerializer,
    )
    def get(
        self, request: Request, *args: object, **kwargs: object
    ) -> Response:
        """Delega a listagem paginada ao comportamento padrão do DRF.

        Sobrescrito apenas para carregar o ``@extend_schema`` — sem um
        método explícito, o drf-spectacular não documenta os
        parâmetros de querystring de uma ``ListAPIView`` genérica.
        """
        return super().get(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[EventoAuditoria]:
        """Monta o queryset filtrado a partir da querystring.

        A validação por ``EventoAuditoriaFiltroSerializer`` garante
        que ``data_inicio``/``data_fim`` cheguem a
        ``consultar_eventos`` já convertidos para ``datetime`` — uma
        data malformada na querystring vira ``400`` aqui, em vez de
        um erro de banco mais adiante.

        Returns:
            Eventos de auditoria filtrados pelos parâmetros
            informados, do mais recente para o mais antigo.
        """
        filtro = EventoAuditoriaFiltroSerializer(
            data=self.request.query_params
        )
        filtro.is_valid(raise_exception=True)
        dados = filtro.validated_data

        return consultar_eventos(
            usuario_id=dados.get("usuario_id"),
            client_id=dados.get("client_id"),
            tipo_evento=dados.get("tipo_evento"),
            data_inicio=dados.get("data_inicio"),
            data_fim=dados.get("data_fim"),
        )
