# SME Identidade Audit Microsserviço

Documentação técnica do serviço responsável pela captura e auditoria de eventos do Keycloak, garantindo rastreabilidade de acessos e suporte à conformidade com a LGPD.

O microsserviço lê os eventos diretamente da Admin REST API do Keycloak, que é a única origem do dado de auditoria. A leitura acontece em ciclo agendado e pode ser antecipada por um aviso enviado pelo Gateway quando há atividade de um usuário — o aviso não carrega o evento, apenas pede a consulta mais cedo.

```{toctree}
:maxdepth: 2
:caption: Conteúdo

eventos
auditoria
api
```
