"""Start the local Compose demo, generating a temporary API key when needed."""

import secrets
import subprocess
from pathlib import Path


def main() -> int:
    """Launch the isolated demo stack from the repository root."""
    project_root = Path(__file__).resolve().parents[1]
    env_file = project_root / ".env"
    if not env_file.exists():
        env_file.write_text(
            "# Generated for the local OpsPilot Compose demo.\n"
            f"OPSPILOT_API_KEY={secrets.token_urlsafe(32)}\n"
            "OPSPILOT_ENABLE_CHAOS_API=false\n",
            encoding="utf-8",
        )
    result = subprocess.run(
        ["docker", "compose", "up", "--build", "--detach"],
        cwd=project_root,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
