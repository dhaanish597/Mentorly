-- A request fence and durable dispatch boundary. Legacy rows remain fail-closed.
CREATE TABLE codebase_request_fences (
 request_id TEXT PRIMARY KEY, token TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('ACTIVE','FENCED','DONE'))
);
CREATE TABLE codebase_dispatch_fences (
 usage_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, token TEXT NOT NULL, operation TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('PREPARED','DISPATCHING','SETTLED','FENCED'))
);
