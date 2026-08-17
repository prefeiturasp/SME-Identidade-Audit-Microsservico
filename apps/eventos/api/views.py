"""Views da API da aplicação eventos."""

import logging

from drf_spectacular.utils import OpenApiResponse, extend_schema
from kombu.exceptions import OperationalError
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.autenticacao.api_key import AutenticacaoApiKey
from apps.eventos.api.serializers import (
    GatilhoPollRequestSerializer,
    GatilhoPollResponseSerializer,
)
from apps.eventos.tasks import task_auditoria_consultar_eventos

logger = logging.getLogger(__name__)

_TAG = ["Eventos"]


class GatilhoPollView(APIView):
    """Recebe o aviso de que houve atividade de um usuário.

    Não recebe eventos de auditoria: o corpo aceito é apenas o realm e
    o usuário, e o evento continua sendo lido do Keycloak. Aceitar um
    evento pronto criaria uma segunda origem do mesmo dado, com
    timestamp próprio, e a deduplicação passaria a depender de
    reconciliar formatos divergentes.

    Responde de imediato, sem esperar a consulta: quem avisa está no
    meio de um fluxo que o usuário aguarda.
    """

    authentication_classes = [AutenticacaoApiKey]

    @extend_schema(
        tags=_TAG,
        summary="Avisar atividade de usuário",
        description=(
            "Solicita a consulta antecipada dos eventos do realm no "
            "Keycloak, sem esperar o próximo ciclo agendado. O corpo "
            "carrega apenas o realm e o usuário — o evento em si é "
            "sempre lido do Keycloak."
        ),
        request=GatilhoPollRequestSerializer,
        responses={
            status.HTTP_202_ACCEPTED: OpenApiResponse(
                response=GatilhoPollResponseSerializer,
                description="Aviso aceito; consulta enfileirada.",
            ),
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                description="Aviso incompleto.",
            ),
            status.HTTP_503_SERVICE_UNAVAILABLE: OpenApiResponse(
                description="Fila indisponível; consulta não enfileirada.",
            ),
        },
    )
    def post(self, request: Request) -> Response:
        """Enfileira a consulta antecipada dos eventos do realm.

        Args:
            request: Requisição HTTP com ``realm`` e ``usuario_id``.

        Returns:
            ``202`` com a confirmação do enfileiramento; ``400`` se o
            aviso vier incompleto; ``503`` se a fila estiver
            indisponível — nesse caso o ciclo agendado ainda captura
            a atividade depois.
        """
        entrada = GatilhoPollRequestSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)

        realm = entrada.validated_data["realm"]

        try:
            task_auditoria_consultar_eventos.delay(realm)
        except OperationalError:
            logger.warning(
                "Aviso do realm %s não enfileirado: fila indisponível",
                realm,
            )
            return Response(
                {"erro": "fila indisponível"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        saida = GatilhoPollResponseSerializer(
            {"situacao": "consulta_enfileirada", "realm": realm}
        )
        return Response(saida.data, status=status.HTTP_202_ACCEPTED)
