"""Integração da AutenticacaoApiKey com o schema OpenAPI (drf-spectacular).

Sem esta extensão, o drf-spectacular ignora silenciosamente o
esquema de segurança de ``AutenticacaoApiKey`` e o Swagger UI não
exibe o campo de API Key para os endpoints protegidos.
"""

from typing import Any

from django.conf import settings
from drf_spectacular.extensions import OpenApiAuthenticationExtension

from apps.autenticacao.api_key import AutenticacaoApiKey


class AutenticacaoApiKeyScheme(OpenApiAuthenticationExtension):
    """Declara o esquema de segurança da AutenticacaoApiKey."""

    target_class = AutenticacaoApiKey
    name = "ApiKeyAuth"

    def get_security_definition(self, auto_schema: Any) -> dict[str, str]:
        """Descreve o header de API Key esperado pelo Swagger UI.

        Args:
            auto_schema: Gerador de schema do drf-spectacular.

        Returns:
            Definição OpenAPI do esquema de segurança apiKey.
        """
        return {
            "type": "apiKey",
            "in": "header",
            "name": settings.API_KEY_HEADER,
        }
