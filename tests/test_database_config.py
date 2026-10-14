"""Where vGeoCatalog / vGeoEngine take their connection settings from."""

from vgeoint.common import database


def test_read_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comment\n\nVGEOINT_DB_PASSWORD=\"abc=1\"\nVGEOINT_DB_PORT = 5433\n", encoding="utf-8")
    assert database.read_env_file(env) == {"VGEOINT_DB_PASSWORD": "abc=1", "VGEOINT_DB_PORT": "5433"}
    assert database.read_env_file(tmp_path / "missing") == {}


def test_db_config_precedence(monkeypatch):
    for key in ("HOST", "PORT", "NAME", "USER", "PASSWORD"):
        monkeypatch.delenv(f"VGEOINT_DB_{key}", raising=False)
    monkeypatch.setattr(database, "read_env_file", lambda: {"VGEOINT_DB_PASSWORD": "from-env-file", "VGEOINT_DB_PORT": "5433"})
    app = "vGeoInt_db_config_test"
    database.app_settings(app).clear()

    config = database.db_config(app, "vGeoEngine")
    assert (config.host, config.port, config.name, config.user) == ("localhost", 5433, "vGeoEngine", "postgres")
    assert config.password == "from-env-file"

    database.save_password(app, "typed-by-user")  # a password entered in the app wins over .env
    assert database.db_config(app, "vGeoEngine").password == "typed-by-user"

    monkeypatch.setenv("VGEOINT_DB_PASSWORD", "from-environment")  # environment variables win over both
    assert database.db_config(app, "vGeoEngine").password == "from-environment"
    database.app_settings(app).clear()
