"""Configuração da app autenticacao."""

from django.apps import AppConfig


class AutenticacaoConfig(AppConfig):
    """Configura o app autenticacao."""

    name = "apps.autenticacao"
    label = "autenticacao"

    def ready(self) -> None:
        """Registra a extensão de schema OpenAPI da AutenticacaoApiKey."""
        from apps.autenticacao import schema  # noqa: F401
