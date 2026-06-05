"""Allow ``python -m bioflow.cli`` to dispatch the same typer app the
``bioflow`` console-script entry point uses."""
from bioflow.cli import app

if __name__ == "__main__":
    app()
