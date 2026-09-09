"""Foreground production entry point used by the launcher and systemd."""
from pathlib import Path

import uvicorn

from autodrome.config import Config


def main():
    settings = Config()
    settings.validate()
    if not (Path(__file__).resolve().parent.parent / 'frontend/dist/index.html').is_file():
        raise SystemExit('Frontend build missing. Run: npm ci --prefix frontend && npm run build --prefix frontend')
    uvicorn.run('app:app', host=settings.api_host, port=settings.api_port, workers=1)


if __name__ == '__main__':
    main()
