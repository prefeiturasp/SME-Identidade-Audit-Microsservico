"""Configuração de rotas da API da aplicação eventos."""

from django.urls import path

from apps.eventos.api.views import GatilhoPollView

urlpatterns = [
    path(
        "gatilho-poll/",
        GatilhoPollView.as_view(),
        name="gatilho-poll",
    ),
]
