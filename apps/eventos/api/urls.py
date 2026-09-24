"""Configuração de rotas da API da aplicação eventos."""

from django.urls import path

from apps.eventos.api.views import (
    GatilhoPollAdminView,
    GatilhoPollView,
)

urlpatterns = [
    path(
        "gatilho-poll/",
        GatilhoPollView.as_view(),
        name="gatilho-poll",
    ),
    path(
        "gatilho-poll-admin/",
        GatilhoPollAdminView.as_view(),
        name="gatilho-poll-admin",
    ),
]
