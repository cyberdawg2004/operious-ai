from app.core.config import Settings


def test_rediss_url_adds_redis_py_ssl_cert_reqs_value() -> None:
    settings = Settings(REDIS_URL="rediss://:secret@example.redis:6379/0")

    assert settings.redis_url.endswith("ssl_cert_reqs=required")


def test_rediss_url_preserves_existing_ssl_cert_reqs_value() -> None:
    settings = Settings(
        REDIS_URL="rediss://:secret@example.redis:6379/0?ssl_cert_reqs=none"
    )

    assert settings.redis_url.endswith("ssl_cert_reqs=none")
