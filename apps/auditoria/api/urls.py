"""Configuração de rotas da API da aplicação auditoria."""

from django.urls import path

from apps.auditoria.api.views import EventoAuditoriaListView

urlpatterns = [
    path(
        "eventos/",
        EventoAuditoriaListView.as_view(),
        name="evento-listar",
    ),
]
