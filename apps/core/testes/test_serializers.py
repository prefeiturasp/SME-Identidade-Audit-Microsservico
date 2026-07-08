"""Testes dos serializers do módulo core."""

from django.test import SimpleTestCase

from apps.core.api.serializers import HealthStatusSerializer


class TestHealthStatusSerializer(SimpleTestCase):
    """Testes do serializer HealthStatusSerializer."""

    def test_deve_validar_status_permitidos(self) -> None:
        """Deve validar corretamente os status permitidos."""
        for status in ["healthy", "degraded", "unhealthy"]:
            with self.subTest(status=status):
                serializer = HealthStatusSerializer(
                    data={"status": status},
                )

                self.assertTrue(serializer.is_valid())
                self.assertEqual(
                    serializer.validated_data["status"],
                    status,
                )

    def test_deve_rejeitar_status_invalido(self) -> None:
        """Deve retornar erro quando o status for inválido."""
        serializer = HealthStatusSerializer(
            data={"status": "offline"},
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("status", serializer.errors)

    def test_deve_exigir_campo_status(self) -> None:
        """Deve retornar erro quando o campo status não for enviado."""
        serializer = HealthStatusSerializer(data={})

        self.assertFalse(serializer.is_valid())
        self.assertIn("status", serializer.errors)

    def test_deve_serializar_dados_corretamente(self) -> None:
        """Deve serializar os dados corretamente."""
        serializer = HealthStatusSerializer(
            instance={"status": "healthy"},
        )

        self.assertEqual(
            serializer.data,
            {
                "status": "healthy",
            },
        )
