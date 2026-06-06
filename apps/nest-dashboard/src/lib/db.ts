import { neon } from "@neondatabase/serverless";

/**
 * Nanda Town's Postgres connection (Neon).
 *
 * We create the client lazily and read DATABASE_URL at call time so that
 * importing this module never throws during the build step. In dev the URL
 * comes from .env.local; in production set it in your host's env vars.
 */
let client: ReturnType<typeof neon> | null = null;

export function sql() {
  if (!client) {
    const url = process.env.DATABASE_URL;
    if (!url) {
      throw new Error("DATABASE_URL is not set. Add it to .env.local.");
    }
    client = neon(url);
  }
  return client;
}

/**
 * Create the `skills` table once per server process. `create table if not
 * exists` makes this safe to call on every request.
 */
let schemaReady: Promise<void> | null = null;

export function ensureSchema(): Promise<void> {
  if (!schemaReady) {
    const db = sql();
    schemaReady = db`
      create table if not exists skills (
        id          uuid primary key default gen_random_uuid(),
        name        text not null,
        author      text,
        description text,
        source_type text not null check (source_type in ('url', 'github', 'content')),
        source_url  text,
        content     text,
        endpoints   text,
        tags        text,
        reachable   boolean,
        created_at  timestamptz not null default now()
      )
    `.then(() => undefined);
  }
  return schemaReady;
}
