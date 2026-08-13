# Captura de eventos

Definido em `apps/eventos/`. A rota exige `AutenticacaoApiKey` (header
configurável, comparado a `settings.API_KEY` — mesmo padrão usado no
SME-Identidade-ETL, no Gateway e no Token-MS).

Rota registrada sob `identidade-auditoria/api/v1/`.

---

## Por que o aviso não carrega o evento

O Gateway sabe do login, da troca de senha e da troca de e-mail no momento em
que processa a requisição; o Keycloak materializa o mesmo acontecimento com o
seu próprio `time`. Se as duas fontes produzissem eventos, a deduplicação
teria de reconciliar dois registros do mesmo fato com timestamps diferentes —
e uma divergência de milissegundos passaria despercebida, gerando duplicata.

Por isso o Gateway envia apenas um aviso (`realm` + `usuario_id`), e o evento
é sempre lido do Keycloak. O aviso antecipa a leitura do caminho mais usado;
o ciclo agendado cobre todo o resto (Admin Console, integrações máquina a
máquina, OIDC direto), independentemente de o Gateway saber que aconteceu.

---

## Aviso de atividade

| Método | Endpoint | Descrição |
|---|---|---|
| `POST` | `/gatilho-poll/` | Solicita a consulta antecipada dos eventos do realm |

```json
// POST /gatilho-poll/
{
  "realm": "COTIC",
  "usuario_id": "5c29cc47-0000-0000-0000-000000000000"
}
```

| Status | Situação |
|---|---|
| `202` | Aviso aceito; consulta enfileirada |
| `400` | Aviso incompleto (falta `realm` ou `usuario_id`) |
| `401` | API Key ausente ou inválida |
| `503` | Fila indisponível; o ciclo agendado ainda captura depois |

Qualquer campo de evento enviado junto do aviso é ignorado — o endpoint não
aceita evento pronto.

---

## Leitura no Keycloak

`task_auditoria_consultar_eventos` atende tanto o ciclo agendado quanto o
aviso sob demanda. Consulta `GET /admin/realms/{realm}/events` com credencial
de service account (client credentials) e exige `eventsEnabled=true` no realm
— sem isso a Admin API responde uma lista vazia, sem erro.

O corte por instante é estrito (`time > checkpoint`): o evento exatamente no
marcador já foi capturado na leitura anterior. Como a Admin API filtra apenas
por dia (`dateFrom`), o corte fino é aplicado sobre o que ela devolveu.

O marcador (`CheckpointCaptura`, um por realm) só avança depois que os
eventos foram entregues para escrita, e nunca retrocede. Se a entrega falhar,
o marcador fica onde está e a leitura seguinte cobre a mesma janela — repetir
uma leitura é resolvido pela restrição de unicidade na escrita; perder um
evento, não.

---

## Chave de deduplicação

A Admin REST API não expõe um identificador único e estável do evento de forma
padronizada entre versões do Keycloak. `evento_id_origem` é derivado por
SHA-256 (truncado em 32 caracteres) de `realm`, `type`, `userId`, `time` e
`sessionId`, com campos ausentes entrando como string vazia para que o mesmo
evento sempre produza a mesma chave.

Decisão assumida enquanto não há acesso a um Keycloak real: se a versão em uso
expuser um identificador nativo confiável, ele é preferível a este hash.

---

## Configuração

| Variável | Papel |
|---|---|
| `KEYCLOAK_URL_SERVIDOR` | Servidor Keycloak |
| `KEYCLOAK_REALM` | Realm consultado por padrão |
| `KEYCLOAK_CLIENT_ID` / `KEYCLOAK_CLIENT_SECRET` | Service account com permissão de leitura de eventos |
| `AUDITORIA_TIPOS_EVENTO` | Tipos consultados, para não trazer o tráfego inteiro |
| `AUDITORIA_LIMITE_CONSULTA` | Teto de eventos por leitura |
| `AUDITORIA_INTERVALO_POLL_MINUTOS` | Intervalo do ciclo agendado |
