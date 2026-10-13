"""Port of vGeoEngine BDefines.h."""

import hashlib

# enum { GROUP = 0, CLASS, TYPE, AIRCRAFT }
GROUP, CLASS, TYPE, AIRCRAFT = range(4)

# enum { ADMIN = 1, USER } — quyền tài khoản
ADMIN, USER = 1, 2


def green(text: str) -> str:
    """vnstring_green."""
    return f"<font color='green'>{text}</font>"


def blue(text: str) -> str:
    """vnstring_blue."""
    return f"<font color='blue'>{text}</font>"


def red(text: str) -> str:
    """vnstring_red."""
    return f"<font color='red'>{text}</font>"


def make_ido(code: str, id_: int) -> str:
    """make_ido("GRP", 1) -> "GRP00001"."""
    return f"{code}{int(id_):05d}"


def ido2id(ido: str) -> int:
    """ido2id("GRP00001") -> 1 (0 when not a number, like QString::toInt)."""
    try:
        return int(str(ido)[3:])
    except ValueError:
        return 0


def md5_hex(password: str) -> str:
    """QCryptographicHash::hash(password.toUtf8(), Md5).toHex() — the stored account password format."""
    return hashlib.md5(password.encode("utf-8")).hexdigest()
