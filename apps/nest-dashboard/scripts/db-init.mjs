// One-shot: verify Neon connectivity and create the SkillMD registry table.
// Run: node scripts/db-init.mjs
import { readFileSync } from "node:fs";
import { neon } from "@neondatabase/serverless";

// Minimal .env.local reader (so this works outside Next's runtime).
function loadEnv() {
  try {
    const raw = readFileSync(new URL("../.env.local", import.meta.url), "utf8");
    for (const line of raw.split("\n")) {
      const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
      if (!m) continue;
      let val = m[2].trim();
      if (
        (val.startsWith('"') && val.endsWith('"')) ||
        (val.startsWith("'") && val.endsWith("'"))
      ) {
        val = val.slice(1, -1);
      }
      if (!process.env[m[1]]) process.env[m[1]] = val;
    }
  } catch {
    /* ignore */
  }
}

loadEnv();

const url = process.env.DATABASE_URL;
if (!url) {
  console.error("DATABASE_URL not set");
  process.exit(1);
}

const sql = neon(url);

const version = await sql`select version()`;
console.log("CONNECTED:", version[0].version.split(",")[0]);

await sql`
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
`;
console.log("TABLE skills ready.");

const count = await sql`select count(*)::int as n from skills`;
console.log("ROWS:", count[0].n);
