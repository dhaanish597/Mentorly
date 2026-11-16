-- Shared Vercel instance coordination and private ephemeral speech cache.
CREATE TABLE cloud_leases (
 id TEXT PRIMARY KEY,
 kind TEXT NOT NULL,
 owner TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('HELD','STARTED','UNCERTAIN')),
 expires_at DOUBLE PRECISION NOT NULL,
 created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX cloud_leases_kind_expiry ON cloud_leases(kind,expires_at);
CREATE TABLE cloud_audio (
 scope TEXT NOT NULL,
 session_id TEXT NOT NULL,
 cache_key TEXT NOT NULL,
 wav BYTEA NOT NULL,
 created_at DOUBLE PRECISION NOT NULL,
 PRIMARY KEY(scope,session_id,cache_key)
);
