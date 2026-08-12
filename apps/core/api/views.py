"""Views da API da aplicação core."""

from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.serializers import HealthStatusSerializer


class HealthCheckView(APIView):
    """Disponibiliza o endpoint de verificação de saúde da aplicação."""

    # Aberto de propósito: quem consulta a saúde do serviço é o
    # orquestrador, que não carrega credencial de aplicação.
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        """Retorna o estado de saúde da aplicação.

        Args:
            request: Requisição HTTP recebida.

        Returns:
            Resposta HTTP contendo o status da aplicação.
        """
        serializer = HealthStatusSerializer(
            {"status": "healthy"},
        )

        return Response(serializer.data)
