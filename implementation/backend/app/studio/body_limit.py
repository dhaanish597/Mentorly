"""Bound studio JSON bodies before framework parsing."""
from starlette.responses import JSONResponse

class StudioBodyLimit:
    def __init__(self, app, limit=262144): self.app,self.limit=app,limit
    async def __call__(self, scope, receive, send):
        path=scope.get('path','')
        is_repo_json=path.startswith('/api/v1/repos/') and path.rstrip('/')!='/api/v1/repos/ingest' and scope.get('method') in ('POST','PUT','PATCH','DELETE')
        if scope['type']!='http' or not (path.startswith('/api/v1/studio/') or is_repo_json):
            return await self.app(scope,receive,send)
        limit = 2100000 if scope.get('path','').endswith('/speech/stt') else self.limit
        body=bytearray()
        while True:
            message=await receive()
            if message['type']=='http.disconnect': return
            chunk=message.get('body',b'')
            if len(body)+len(chunk)>limit:
                return await JSONResponse({'detail':'Request too large'},status_code=413)(scope,receive,send)
            body.extend(chunk)
            if not message.get('more_body',False): break
        delivered=False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered=True
                return {'type':'http.request','body':bytes(body),'more_body':False}
            return await receive()
        return await self.app(scope,replay,send)
