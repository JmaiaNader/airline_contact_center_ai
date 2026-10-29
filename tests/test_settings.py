from src.config.settings import Settings


def test_default_settings_do_not_connect_to_database() -> None:
    settings = Settings(_env_file=None)
    assert settings.db_name == "db_airlines"
    assert settings.llm_provider == "ollama"
    assert settings.default_employee_language == "en"
