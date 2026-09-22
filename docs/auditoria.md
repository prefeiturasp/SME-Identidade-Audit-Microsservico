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

## Modelo `IdentificadorUsuarioAuditoria`

Mantém o histórico dos identificadores alternativos observados para cada
usuário.

| Campo        | Papel                                                       |
| ------------ | ----------------------------------------------------------- |
| `id`         | UUID                                                        |
| `usuario_id` | ID interno do usuário no Keycloak                           |
| `realm`      | Mesmo identificador de realm utilizado em `EventoAuditoria` |
| `tipo`       | Tipo do identificador: `EMAIL`, `CPF` ou `RF`               |
| `valor`      | Valor normalizado do identificador                          |
| `criado_em`  | Quando o identificador foi observado pela auditoria         |

Os identificadores são históricos. Uma alteração de e-mail, CPF ou RF não
atualiza nem remove o registro anterior: um novo registro é criado para o
mesmo `usuario_id`.

Exemplo:

```text
usuario_id = abc-123
EMAIL = antigo@exemplo.com
EMAIL = novo@exemplo.com
CPF   = 12345678901
RF    = 1234567
```

Tanto `antigo@exemplo.com` quanto `novo@exemplo.com` continuam apontando para
`abc-123` e, portanto, permitem recuperar o mesmo histórico de eventos.

A restrição:

```text
(realm, usuario_id, tipo, valor)
```

impede a gravação repetida da mesma associação, mas não impede que um
identificador apareça historicamente associado a usuários diferentes.

Isso é intencional: a auditoria registra o que foi observado ao longo do
tempo, em vez de assumir que um e-mail, CPF ou RF jamais poderá ser reutilizado
ou corrigido.

### Índices

Dois índices atendem à resolução dos identificadores:

* `(realm, tipo, valor)` — localização de um usuário a partir de e-mail, CPF ou RF;
* `(realm, usuario_id)` — recuperação dos identificadores conhecidos de um usuário.

---

## Coleta dos identificadores

Durante a captura de eventos de usuário, os usuários presentes no lote são
identificados pelas combinações:

```text
(usuario_id, realm)
```

Cada combinação é consultada uma única vez no lote, mesmo quando o mesmo
usuário possui vários eventos.

A consulta ao Keycloak utiliza o nome lógico do realm:

```text
/admin/realms/{realm}/users/{usuario_id}
```

Por exemplo:

```text
realm lógico para a API: COTIC
realm armazenado no evento: realmId retornado pelo Keycloak
```

A resposta atual do usuário é utilizada para extrair:

* `id` → `usuario_id`;
* `email` → e-mail;
* `attributes.cpf` → CPF;
* `attributes.rf` → RF.

O registro em `IdentificadorUsuarioAuditoria` utiliza o mesmo `realm` já
normalizado e persistido nos eventos. Assim, a resolução posterior permanece
consistente com `EventoAuditoria`.

Quando o usuário já não existe no Keycloak e a consulta responde `404`, a
captura do evento não é interrompida. O evento continua seguindo para
persistência; apenas não há novos identificadores para registrar naquele
momento.

---

## Consulta por usuário

O parâmetro de consulta continua sendo chamado `usuario_id`, mantendo
compatibilidade com o contrato já existente.

Ele passa, porém, a funcionar como um identificador genérico de usuário e pode
receber:

* ID interno do usuário no Keycloak;
* e-mail atual;
* e-mail histórico;
* CPF atual ou histórico;
* RF atual ou histórico.

A consulta sempre preserva o caminho original por `usuario_id`.

Quando o valor também corresponde a um identificador alternativo, o serviço
resolve as associações históricas em `IdentificadorUsuarioAuditoria` e adiciona
os respectivos pares:

```text
(realm, usuario_id)
```

ao filtro dos eventos.

Exemplo:

```text
entrada:
antigo@exemplo.com

resolução:
realm-id-cotic + abc-123

consulta final:
EventoAuditoria(
    realm="realm-id-cotic",
    usuario_id="abc-123"
)
```

Com isso, a troca de e-mail, CPF ou RF não fragmenta o histórico de auditoria.

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
