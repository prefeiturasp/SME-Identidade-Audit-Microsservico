"""Serializers de entrada e saída do aviso de atividade."""

from rest_framework import serializers


class GatilhoPollRequestSerializer(serializers.Serializer):
    """Representa o aviso de que houve atividade de um usuário.

    Deliberadamente mínimo: o que chega aqui não é um evento de
    auditoria, é só um pedido para consultar o Keycloak antes do
    próximo ciclo agendado. O evento em si é sempre lido da origem,
    nunca aceito pronto de quem avisa.

    Os dois campos são exigidos preenchidos: a consulta antecipada é
    feita por realm, e o usuário é o que permite relacionar o aviso à
    atividade correspondente.
    """

    realm = serializers.CharField(max_length=100)
    usuario_id = serializers.CharField(max_length=64)


class GatilhoPollResponseSerializer(serializers.Serializer):
    """Representa a confirmação de que o aviso foi aceito."""

    situacao = serializers.CharField()
    realm = serializers.CharField()
