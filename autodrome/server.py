"""Foreground production entry point for the installed application."""

import uvicorn

from autodrome.web import FRONTEND_DIRECTORY, app, conf


def main() -> None:
    conf.validate()
    if not (FRONTEND_DIRECTORY / "index.html").is_file():
        raise SystemExit(
            "Packaged frontend is missing. Rebuild Autodrome after running "
            "`npm ci --prefix frontend && npm run build --prefix frontend`."
        )
    uvicorn.run(app, host=conf.api_host, port=conf.api_port, workers=1)


if __name__ == "__main__":
    main()
