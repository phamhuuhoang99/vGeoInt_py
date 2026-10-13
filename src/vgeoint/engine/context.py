"""The vGeoEngine database connection (the C++ MainWindow::database() static QSqlDatabase)."""

from qgis.PyQt.QtSql import QSqlDatabase

from vgeoint.common.database import DbConfig, db_config, open_database_interactive
from vgeoint.common.defines import ENGINE_NAME

DB_NAME = "vGeoEngine"
CONNECTION = "vgeoengine"

_config: DbConfig | None = None


def config() -> DbConfig:
    global _config
    if _config is None:
        _config = db_config(ENGINE_NAME, DB_NAME)
    return _config


def database(parent=None) -> QSqlDatabase:
    """Open the shared connection, asking for the password once if needed (parent given)."""
    global _config
    if QSqlDatabase.contains(CONNECTION):
        db = QSqlDatabase.database(CONNECTION, False)
        if db.isOpen():
            return db
    db, _config = open_database_interactive(parent, ENGINE_NAME, config(), CONNECTION)
    return db


def reset():
    """Forget the cached configuration and close the connection (tests)."""
    global _config
    _config = None
    if QSqlDatabase.contains(CONNECTION):
        QSqlDatabase.database(CONNECTION, False).close()
