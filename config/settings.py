"""Configuração Django do SME-Identidade-Audit-Microsservico."""

import os
import urllib.parse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [
    host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",")
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "apps.core",
    "apps.autenticacao",
    "apps.eventos",
    "apps.auditoria",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


def _url_para_bd(url: str | None) -> dict:
    """Converta URL PostgreSQL em dicionário de configuração Django."""
    if not url:
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}

    parsed = urllib.parse.urlparse(url)

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": parsed.username or "postgres",
        "PASSWORD": parsed.password or "postgres",
        "HOST": parsed.hostname or "localhost",
        "PORT": parsed.port or 5432,
        "CONN_MAX_AGE": 600,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            "connect_timeout": 10,
        },
    }


DATABASES = {
    "default": _url_para_bd(os.getenv("IDENTIDADE_AUDITORIA_DB_URL")),
}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.autenticacao.api_key.AutenticacaoApiKey",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

# Autenticação de serviço a serviço (mesmo padrão do ETL, do Gateway e
# do Token-MS): header configurável comparado a uma chave fixa.
API_KEY = os.getenv("API_KEY", "")
API_KEY_HEADER = os.getenv("API_KEY_HEADER", "X-API-Key")

# ---------------------------------------------------------------------------
# Celery / KeyDB
# ---------------------------------------------------------------------------
URL_KEYDB = os.getenv("URL_KEYDB", "redis://localhost:6379/0")
CELERY_BROKER_URL = URL_KEYDB
CELERY_RESULT_BACKEND = URL_KEYDB
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "America/Sao_Paulo"
CELERY_ENABLE_UTC = True
CELERY_TASK_ALWAYS_EAGER = os.getenv("CELERY_TASK_ALWAYS_EAGER", "0") == "1"
CELERY_TASK_STORE_EAGER_RESULT = CELERY_TASK_ALWAYS_EAGER

# Isola um worker/broker compartilhado (ex.: rodando local contra o
# KeyDB real de QA) das filas usadas pelos workers reais — sem prefixo
# (padrão), o comportamento de produção não muda.
_PREFIXO_FILA = os.getenv("AUDITORIA_PREFIXO_FILA", "")


def _fila(nome: str) -> str:
    return f"{_PREFIXO_FILA}{nome}"


# Filas separadas por etapa, replicando o padrão de pods do
# SME-Identidade-ETL (docker-compose-dev.yml: etl_worker_celery/
# etl_worker_keycloak/etl_worker_token_ms) — um worker dedicado por
# natureza de trabalho, não um único processo escutando tudo:
# - captura de usuário e captura de admin consultam o Keycloak em
#   canais/endpoints independentes (ver apps.eventos.clientes.
#   keycloak_admin) e não devem competir pelo mesmo worker, senão uma
#   leitura lenta num canal atrasa o outro;
# - a escrita em lote no Postgres é a etapa mais pesada e não pode
#   segurar atrás dela a recepção do aviso do Gateway, que precisa ser
#   aceito de imediato.
CELERY_TASK_ROUTES = {
    "task_auditoria_consultar_eventos": {
        "queue": _fila("auditoria_captura_usuario")
    },
    "task_auditoria_consultar_admin_events": {
        "queue": _fila("auditoria_captura_admin")
    },
    "task_auditoria_persistir_lote": {
        "queue": _fila("auditoria_persistencia")
    },
    "task_auditoria_expurgar_eventos": {
        "queue": _fila("auditoria_persistencia")
    },
}

# ---------------------------------------------------------------------------
# Keycloak Admin API — origem única dos eventos de auditoria
# ---------------------------------------------------------------------------
# O realm precisa estar com eventsEnabled=true para que a Admin API
# exponha os eventos; a credencial é de service account com permissão
# de leitura de eventos — direção oposta da API Key de serviço usada
# entre os microsserviços da plataforma.
KEYCLOAK_URL_SERVIDOR = os.getenv(
    "KEYCLOAK_URL_SERVIDOR", "https://localhost:8080/"
)
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "COTIC")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "identidade-auditoria")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "")
KEYCLOAK_VERIFICAR_SSL = (
    os.getenv("KEYCLOAK_VERIFICAR_SSL", "true").lower() == "true"
)
KEYCLOAK_TIMEOUT = float(os.getenv("KEYCLOAK_TIMEOUT", "30"))

# Tipos de evento consultados na Admin API. Restringir na origem evita
# trazer a totalidade do tráfego do realm a cada ciclo.
AUDITORIA_TIPOS_EVENTO = [
    tipo.strip()
    for tipo in os.getenv(
        "AUDITORIA_TIPOS_EVENTO",
        "LOGIN,LOGIN_ERROR,LOGOUT,REGISTER,UPDATE_PASSWORD,UPDATE_EMAIL",
    ).split(",")
    if tipo.strip()
]

# Teto de eventos por leitura da Admin API. Uma janela sem leitura
# bem-sucedida acumula eventos, e sem teto uma única consulta tentaria
# trazer tudo de uma vez.
AUDITORIA_LIMITE_CONSULTA = int(os.getenv("AUDITORIA_LIMITE_CONSULTA", "500"))

# Intervalo do ciclo agendado de captura, em minutos. Piso a combinar
# com infra: um intervalo curto demais transforma a captura em carga
# constante sobre o Keycloak.
AUDITORIA_INTERVALO_POLL_MINUTOS = int(
    os.getenv("AUDITORIA_INTERVALO_POLL_MINUTOS", "5")
)

# ---------------------------------------------------------------------------
# Persistência de auditoria
# ---------------------------------------------------------------------------
# Tamanho do lote de escrita. Dimensionado a partir da estimativa de
# volume, recalibrável sem redeploy de código.
AUDITORIA_TAMANHO_LOTE = int(os.getenv("AUDITORIA_TAMANHO_LOTE", "500"))

# Retenção e expurgo. Desligado por padrão de propósito: o período
# mínimo de guarda dos registros ainda depende de definição jurídica,
# e apagar antes disso é irreversível.
AUDITORIA_RETENCAO_DIAS = int(os.getenv("AUDITORIA_RETENCAO_DIAS", "3650"))
AUDITORIA_EXPURGO_ATIVO = os.getenv("AUDITORIA_EXPURGO_ATIVO", "0") == "1"
AUDITORIA_EXPURGO_TAMANHO_LOTE = int(
    os.getenv("AUDITORIA_EXPURGO_TAMANHO_LOTE", "1000")
)
