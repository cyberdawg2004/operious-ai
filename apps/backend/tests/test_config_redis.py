from app.core.config import Settings


def test_rediss_url_adds_redis_py_ssl_cert_reqs_value() -> None:
    settings = Settings(REDIS_URL="rediss://:secret@example.redis:6379/0")

    assert settings.redis_url.endswith("ssl_cert_reqs=required")


def test_rediss_url_preserves_existing_ssl_cert_reqs_value() -> None:
    settings = Settings(
        REDIS_URL="rediss://:secret@example.redis:6379/0?ssl_cert_reqs=none"
    )

    assert settings.redis_url.endswith("ssl_cert_reqs=none")


def test_rediss_result_backend_uses_same_database_for_single_db_providers() -> None:
    settings = Settings(REDIS_URL="rediss://:secret@example.redis:6379/0")

    assert settings.celery_result_backend_url == settings.redis_url


def test_plain_redis_result_backend_keeps_dedicated_database() -> None:
    settings = Settings(REDIS_URL="redis://localhost:6379/0")

    assert settings.celery_result_backend_url == "redis://localhost:6379/1"


def test_celery_broker_url_falls_back_to_redis_url_when_unset() -> None:
    settings = Settings(REDIS_URL="redis://localhost:6379/0")

    assert settings.celery_broker_url == settings.redis_url


def test_celery_broker_url_overrides_redis_when_set_to_amqps() -> None:
    settings = Settings(
        REDIS_URL="redis://localhost:6379/0",
        CELERY_BROKER_URL="amqps://operator:secret@rabbit.example/%2F",
    )

    assert settings.celery_broker_url == "amqps://operator:secret@rabbit.example/%2F"
