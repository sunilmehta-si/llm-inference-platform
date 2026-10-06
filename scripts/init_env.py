import secrets
from pathlib import Path

path = Path(".env")
if path.exists():
    raise SystemExit(".env already exists; left unchanged")
text = (
    Path(".env.example")
    .read_text()
    .replace(
        "replace-with-a-generated-secret-at-least-24-characters",
        secrets.token_urlsafe(32),
    )
)
# Create privately and exclusively; never display the generated credential.
with path.open("x") as file:
    path.chmod(0o600)
    file.write(text)
print("Created private .env. Load it locally with: set -a; source .env; set +a")
