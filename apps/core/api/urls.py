"""Configuração de rotas da API da aplicação core."""

from django.urls import path

from .views import HealthCheckView

urlpatterns = [
    path(
        "health/",
        HealthCheckView.as_view(),
        name="health-check",
    ),
]
