# Persistência de auditoria

Definido em `apps/auditoria/`. Não expõe rotas: recebe os eventos já
normalizados pela captura, por fila, e concentra a escrita no Postgres.

---

## Modelo `EventoAuditoria`

| Campo | Papel |
|---|---|
| `id` | UUID |
| `evento_id_origem` | Chave de deduplicação (única) |
| `tipo_evento` | `LOGIN`, `LOGIN_ERROR`, `LOGOUT`, … |
| `usuario_id` | Usuário no Keycloak |
| `realm` | Realm de origem |
| `client_id` | Sistema pelo qual a atividade passou |
| `ip_origem` | Endereço de origem |
| `timestamp_evento` | Quando o Keycloak registrou |
| `timestamp_recebimento` | Quando esta base gravou |
| `detalhes` | Payload bruto completo |

`detalhes` guarda o evento inteiro, não só os campos promovidos a colunas: o
que hoje parece irrelevante pode ser exatamente o que uma apuração futura
precisa, e o dado descartado na escrita não tem como ser recuperado depois.

### Índices

Três índices compostos cobrem as consultas previstas de apuração, sempre
recortadas por período:

- `(usuario_id, timestamp_evento)` — atividade de um usuário
- `(client_id, timestamp_evento)` — atividade em um sistema
- `(tipo_evento, timestamp_evento)` — ocorrências de um tipo

---

## Garantia de não duplicação

Duas camadas, independentes:

1. **Marcador da captura.** Corte estrito (`time > checkpoint`), avançado só
   após a entrega confirmada. Evita, na maioria dos casos, que o aviso sob
   demanda e o ciclo agendado processem a mesma janela.
2. **Restrição de unicidade + `bulk_create(ignore_conflicts=True)`.** Cobre a
   corrida que a primeira camada não resolve: quando as duas leituras
   acontecem ao mesmo tempo, ambas chegam ao banco com a mesma chave e o
   Postgres rejeita a segunda — sem lock explícito, sem consulta prévia por
   linha e sem coordenação entre os processos.

A tabela nunca fica com o evento fisicamente duplicado, independentemente de a
primeira camada acertar ou não.

---

## Escrita em lote

`task_auditoria_persistir_lote` roda em fila própria
(`auditoria_persistencia`), separada da recepção: a escrita é a etapa lenta e,
num único worker, seguraria atrás de si os avisos, que precisam ser aceitos de
imediato. O tamanho do lote é configurável por `AUDITORIA_TAMANHO_LOTE`,
recalibrável conforme o volume observado, sem redeploy.

---

## Retenção e expurgo

`task_auditoria_expurgar_eventos` remove os eventos anteriores a
`AUDITORIA_RETENCAO_DIAS`, em lotes sucessivos.

**Desligado por padrão** (`AUDITORIA_EXPURGO_ATIVO=0`). O período mínimo de
guarda ainda depende de definição jurídica (LGPD/normas SME), e a remoção é
irreversível. A tarefa fica agendada mesmo desligada e verifica a própria
autorização a cada execução — liberar a remoção é uma mudança de configuração,
sem mexer no agendamento.
