"""Serve a built SPA without masking missing API routes or static assets."""
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


class FrontendFiles(StaticFiles):
    async def get_response(self, path, scope):
        if path in {"", ".", "/"}:
            path = "index.html"
        if path.split('/')[0] in {'api', 'ws', 'ping'}:
            raise HTTPException(status_code=404)
        try:
            return await super().get_response(path, scope)
        except HTTPException as error:
            if error.status_code != 404 or '.' in path or scope['method'] not in {'GET', 'HEAD'}:
                raise
            response = await super().get_response('index.html', scope)
            response.headers['Cache-Control'] = 'no-cache'
            return response
