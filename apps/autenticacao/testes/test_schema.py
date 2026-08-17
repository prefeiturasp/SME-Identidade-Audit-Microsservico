"""Testes da integração da autenticação com o schema OpenAPI."""

from django.test import SimpleTestCase, override_settings

from apps.autenticacao.schema import AutenticacaoApiKeyScheme


@override_settings(API_KEY_HEADER="X-API-Key")
class TestAutenticacaoApiKeyScheme(SimpleTestCase):
    """Testes de AutenticacaoApiKeyScheme."""

    def test_deve_retornar_definicao_de_seguranca(self) -> None:
        """Deve montar a definição OpenAPI para autenticação por API Key."""
        schema = AutenticacaoApiKeyScheme.__new__(AutenticacaoApiKeyScheme)

        resultado = schema.get_security_definition(auto_schema=None)

        assert resultado == {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
        }
