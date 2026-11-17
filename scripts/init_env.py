"""Generate local credentials without overwriting an existing environment file."""

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    path = ROOT / ".env"
    if path.exists():
        print(".env already exists; preserved without changes")
        return
    password = secrets.token_hex(24)
    content = (ROOT / ".env.example").read_text()
    content = content.replace("POSTGRES_PASSWORD=\n", f"POSTGRES_PASSWORD={password}\n")
    url = "postgresql+psycopg://cloudpilot:" + password + "@127.0.0.1:15432/cloudpilot"
    content = content.replace("DATABASE_URL=\n", f"DATABASE_URL={url}\n")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(content)
    print("Created .env with private local credentials; values are not printed")


if __name__ == "__main__":
    main()
