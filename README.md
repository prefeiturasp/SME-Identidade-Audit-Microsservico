# SME-Identidade-Audit-Microsservico

O SME-Identidade-Audit-Microsservico é responsável pela captura e persistência dos eventos de autenticação e autorização da plataforma SME-SP, permitindo rastreabilidade e auditoria das operações relacionadas às identidades digitais.

Integrado ao Keycloak por meio da SPI Event Listener, o serviço registra eventos de acesso, autenticação e demais ações relevantes, fornecendo histórico e evidências para fins de governança e observabilidade.

Além da auditoria operacional, o microsserviço apoia os processos de conformidade com a LGPD por meio da disponibilização de informações para geração de relatórios e análise de eventos de segurança.

## Estrutura do repositório

```
.
├── apps/
│   ├── core/           # cliente HTTP
├── config/             # settings, urls, wsgi
├── requirements/
│   ├── base.txt        # dependências de produção
│   └── local.txt       # base + ferramentas de desenvolvimento
└── manage.py
```

### apps/core

| Módulo | Responsabilidade |
|---|---|
| `api/views.py` | Endpoints da aplicação, incluindo o health check do serviço |
| `api/serializers.py` | Serialização e validação de dados de entrada e saída |
| `api/urls.py` | Registro e roteamento das URLs da aplicação |

## Requisitos

- Python 3.12+
- Docker e Docker Compose

## Configuração do ambiente

```bash
cp .env.example .env
make build
make run
```

**Geral**

| Variável | Padrão | Descrição |
|---|---|---|
| `DJANGO_SECRET_KEY` | — | Chave secreta do Django |
| `DJANGO_DEBUG` | `1` | Ativa o modo debug (`0` em produção) |
| `DJANGO_ALLOWED_HOSTS` | `*` | Hosts permitidos, separados por vírgula |

## Atalhos Make

Use `make help` para listar todos os comandos disponíveis. Os principais:

**Ambiente**

| Comando | Descrição |
|---|---|
| `make run` | Sobe o containers em modo dev (porta 8002) |
| `make build` | Rebuild da imagem dev |
| `make stop` | Para e remove containers |

**Testes**

| Comando | Descrição |
|---|---|
| `make test` | Suite completa com cobertura ≥ 80% |
| `make test-core` | Apenas `apps.core` |

**Qualidade**

| Comando | Descrição |
|---|---|
| `make lint` | ruff + black + isort + mypy |
| `make coverage` | Relatório HTML em `docs/_cov/` |
| `make schema` | Gera schema OpenAPI em `schema.yml` |
| `make docs` | Gera documentação Sphinx em `docs/_build/html/` |

## Endpoints

Consulte o Swagger em `/identidade-auditoria/api/v1/docs/` para a lista completa de rotas com parâmetros e exemplos de resposta.