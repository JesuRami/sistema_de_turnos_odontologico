"""Contrato del seed con `.env.example`: variables SEED_* presentes y sintéticas."""

from app.seed import SEED_VARS, read_seed_config

from tests.test_env_example import _example_keys


def test_env_example_declara_el_seed_con_valores_sinteticos() -> None:
    keys = _example_keys()
    for variable in SEED_VARS:
        assert variable in keys, f"{variable} falta en .env.example"

    config = read_seed_config(keys)

    assert config.admin_email.endswith("@example.com")
    assert "cambiar" in config.admin_password.lower()  # placeholder evidente, no un secreto
