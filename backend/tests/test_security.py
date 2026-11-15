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
