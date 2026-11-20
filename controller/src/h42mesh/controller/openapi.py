"""Export the OpenAPI description, the contract with the GUI and the agent.

    uv run python -m h42mesh.controller.openapi            # write openapi/controller.json
    uv run python -m h42mesh.controller.openapi --check    # fail if it is out of date

The default output is ``openapi/controller.json`` at the repository root.
Neither the database nor the passphrase is needed.
"""

import argparse
import json
import sys
from pathlib import Path

from h42mesh.controller.app import create_app

# src/h42mesh/controller/openapi.py -> repository root
_PROJECT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = _PROJECT_DIR.parent / "openapi" / "controller.json"


def render_openapi() -> str:
    """OpenAPI description as stable, diff-friendly JSON text."""
    schema = create_app().openapi()
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check", action="store_true", help="only check that the file is up to date"
    )
    args = parser.parse_args(argv)
    output: Path = args.output
    content = render_openapi()

    if args.check:
        current = output.read_text(encoding="utf-8") if output.exists() else None
        if current != content:
            print(f"{output} is out of date: run python -m h42mesh.controller.openapi")
            return 1
        print(f"{output} is up to date")
        return 0

    if not (_PROJECT_DIR / "pyproject.toml").exists() and args.output == DEFAULT_OUTPUT:
        print("not running from the source tree: pass --output", file=sys.stderr)
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8", newline="\n")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
