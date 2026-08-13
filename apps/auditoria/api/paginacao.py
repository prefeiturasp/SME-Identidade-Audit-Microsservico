"""Paginação da consulta de eventos de auditoria."""

from rest_framework.pagination import PageNumberPagination


class PaginacaoEventoAuditoria(PageNumberPagination):
    """Pagina a listagem de eventos, 100 por página por padrão.

    O tamanho é configurável por requisição via ``page_size``, com
    teto de 1000 — sem teto, uma consulta sem filtro de período
    devolveria a tabela inteira numa única página.
    """

    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 1000
