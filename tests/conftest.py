import pytest


@pytest.fixture(scope="session")
def qgis_app():
    from vgeoint.common.bootstrap import create_app

    return create_app("vGeoInt_test")


def action_texts(menu) -> list[str]:
    return ["-" if a.isSeparator() else a.text() for a in menu.actions()]
