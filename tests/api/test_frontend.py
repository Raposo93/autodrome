from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from api.frontend import FrontendFiles


@pytest.mark.anyio
async def test_frontend_routes_and_missing_assets(tmp_path):
    (tmp_path / 'index.html').write_text('<h1>Autodrome</h1>')
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets/app.js').write_text('console.log("app")')
    app = FastAPI()
    app.mount('/', FrontendFiles(directory=tmp_path))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        for path in ('/', '/library/album'):
            response = await client.get(path)
            assert response.status_code == 200
            assert '<h1>Autodrome</h1>' in response.text
        response = await client.get('/assets/app.js')
        assert response.status_code == 200
        assert 'console.log' in response.text
        for path in ('/assets/missing.js', '/api/missing', '/ws', '/%2e%2e/README.md'):
            assert (await client.get(path)).status_code == 404


def test_frontend_does_not_reference_build_time_token():
    source = Path('frontend/src/services/api.js').read_text()
    assert 'import.meta.env.VITE_API_TOKEN' not in source
    assert 'sessionStorage' in source
