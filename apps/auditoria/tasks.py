"""Tarefas de escrita e de retenção dos eventos de auditoria."""

from __future__ import annotations

from typing import Any

from celery import shared_task

from apps.auditoria.servicos import expurgar_eventos_antigos, persistir_lote


@shared_task(name="task_auditoria_persistir_lote", ignore_result=True)
def task_auditoria_persistir_lote(
    eventos: list[dict[str, Any]],
) -> dict[str, int]:
    """Grava no banco o lote de eventos já normalizados.

    Roda em fila própria porque a escrita é a etapa lenta do caminho:
    concentrá-la aqui evita que ela segure atrás de si a recepção dos
    avisos, que precisam ser aceitos de imediato.

    Args:
        eventos: Eventos normalizados a gravar.

    Returns:
        Contagem de eventos recebidos e de linhas criadas.
    """
    return persistir_lote(eventos)


@shared_task(name="task_auditoria_expurgar_eventos", ignore_result=True)
def task_auditoria_expurgar_eventos() -> dict[str, Any]:
    """Remove eventos fora do período de retenção, se autorizado.

    A autorização é verificada a cada execução, não no agendamento:
    assim, liberar a remoção depois da definição jurídica é uma
    mudança de configuração, sem mexer no agendamento.

    Returns:
        Situação da execução e quantidade de linhas removidas.
    """
    return expurgar_eventos_antigos()
