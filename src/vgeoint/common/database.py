"""PostgreSQL connection settings shared by vGeoCatalog and vGeoEngine.

The C++ apps hardcoded host/port/database/user/password in BDefines.h. Here they come from, in order:
environment variables VGEOINT_DB_HOST / _PORT / _NAME / _USER / _PASSWORD, then the app's settings
under "Database/...", then the old defaults (except the password, which has no default; the user is
asked for it once and it is stored in the app settings).
"""

import os
from dataclasses import dataclass, replace

from qgis.core import QgsDataSourceUri
from qgis.PyQt.QtSql import QSqlDatabase
from qgis.PyQt.QtWidgets import QInputDialog, QLineEdit, QWidget

from vgeoint.common.utils import app_settings


@dataclass(frozen=True)
class DbConfig:
    host: str = "localhost"
    port: int = 5432
    name: str = ""
    user: str = "postgres"
    password: str = ""


def db_config(app_name: str, default_db: str) -> DbConfig:
    s = app_settings(app_name)

    def value(key: str, default):
        env = os.environ.get(f"VGEOINT_DB_{key.upper()}")
        return env if env is not None else s.value(f"Database/{key}", default)

    return DbConfig(
        host=str(value("Host", "localhost")),
        port=int(value("Port", 5432)),
        name=str(value("Name", default_db)),
        user=str(value("User", "postgres")),
        password=str(value("Password", "")),
    )


def save_password(app_name: str, password: str):
    app_settings(app_name).setValue("Database/Password", password)


def open_database(config: DbConfig, connection_name: str) -> QSqlDatabase:
    """Open (or reuse) a named QPSQL connection. Each thread needs its own connection name."""
    if QSqlDatabase.contains(connection_name):
        db = QSqlDatabase.database(connection_name, False)
    else:
        db = QSqlDatabase.addDatabase("QPSQL", connection_name)
    db.setHostName(config.host)
    db.setPort(config.port)
    db.setDatabaseName(config.name)
    db.setUserName(config.user)
    db.setPassword(config.password)
    db.open()
    return db


def open_database_interactive(
    parent: QWidget | None, app_name: str, config: DbConfig, connection_name: str
) -> tuple[QSqlDatabase, DbConfig]:
    """Open the database; on failure ask for the password (replaces the hardcoded one) and retry once."""
    db = open_database(config, connection_name)
    if db.isOpen() or parent is None:
        return db, config
    password, ok = QInputDialog.getText(
        parent,
        app_name,
        f"Nhập mật khẩu cơ sở dữ liệu ({config.user}@{config.host}:{config.port}/{config.name}):",
        QLineEdit.EchoMode.Password,
    )
    if ok and password:
        config = replace(config, password=password)
        db = open_database(config, connection_name)
        if db.isOpen():
            save_password(app_name, password)
    return db, config


def postgis_uri(config: DbConfig) -> QgsDataSourceUri:
    uri = QgsDataSourceUri()
    uri.setConnection(
        config.host, str(config.port), config.name, config.user, config.password, QgsDataSourceUri.SslMode.SslDisable
    )
    return uri
