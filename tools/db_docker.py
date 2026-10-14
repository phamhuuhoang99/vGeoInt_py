"""Run the PostGIS server of vGeoCatalog / vGeoEngine in Docker (see docker-compose.yml).

    pixi run db-up      # create .env with a random password if needed, start and wait until ready
    pixi run db-down    # stop the container (data stays in the "vgeoint-pgdata" volume)

The apps read the connection from .env (VGEOINT_DB_*), so they connect without asking for a password.
"""

import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"


def ensure_env_file() -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    if any(line.strip().startswith("VGEOINT_DB_PASSWORD=") for line in lines):
        return
    lines.append(f"VGEOINT_DB_PASSWORD={secrets.token_urlsafe(18)}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Đã tạo mật khẩu database trong {ENV_FILE}")


def compose(*args: str) -> int:
    return subprocess.call(["docker", "compose", *args], cwd=ROOT)


def main() -> int:
    if shutil.which("docker") is None:
        sys.exit("Chưa cài Docker Desktop (https://www.docker.com/products/docker-desktop/)")
    if subprocess.call(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
        sys.exit("Docker chưa chạy: mở Docker Desktop rồi thử lại")
    command = sys.argv[1] if len(sys.argv) > 1 else "up"
    if command == "up":
        ensure_env_file()
        # First start: the init script builds both databases before the health check passes (~1 min).
        code = compose("up", "-d", "--wait", "--wait-timeout", "600")
        if code == 0:
            print("PostGIS sẵn sàng tại 127.0.0.1:5432 (database vGeoCatalog, vGeoEngine)")
        return code
    if command == "down":
        return compose("stop")
    return compose(*sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
