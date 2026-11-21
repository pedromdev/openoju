from app.security import generate_api_key, split_api_key


def test_generated_api_key_uses_oju_prefix():
    full_key, prefix, secret_hash = generate_api_key()
    assert full_key.startswith("oju_")
    assert prefix in full_key
    assert len(secret_hash) == 64


def test_split_api_key_accepts_oju_prefix():
    parsed = split_api_key("oju_abcdef_ghijkl")
    assert parsed == ("abcdef", "ghijkl")


def test_split_api_key_rejects_old_camera_prefix():
    assert split_api_key("cam_abcdef_ghijkl") is None


def test_split_api_key_rejects_malformed_values():
    assert split_api_key("oju_abcdef") is None
    assert split_api_key("oju__ghijkl") is None
    assert split_api_key("oju_abcdef_") is None


def test_postgres_limiter_shares_window_between_sessions():
    from app.db import SessionLocal
    from app.models import LoginAttempt
    from app.security import PostgresLimiter

    limiter = PostgresLimiter()
    key = "10.0.0.1:owner@acme.com"
    first = SessionLocal()
    second = SessionLocal()
    try:
        limiter.hit(first, key, window_s=300)
        assert limiter.blocked(second, key, attempts=2, window_s=300) is False
        limiter.hit(second, key, window_s=300)
        assert limiter.blocked(first, key, attempts=2, window_s=300) is True
        assert first.query(LoginAttempt).filter(LoginAttempt.key == key).count() == 2
        limiter.reset(second, key)
        assert limiter.blocked(first, key, attempts=2, window_s=300) is False
    finally:
        first.close()
        second.close()


def test_limiter_for_uses_settings():
    from app.config import Settings
    from app.security import PostgresLimiter, SlidingWindowLimiter, limiter_for

    assert isinstance(
        limiter_for(Settings(rate_limit_backend="postgres")), PostgresLimiter
    )
    assert isinstance(
        limiter_for(Settings(rate_limit_backend="memory")), SlidingWindowLimiter
    )
