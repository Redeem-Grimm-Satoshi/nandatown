import { ensureSchema, sql } from "./db";

export type SkillSourceType = "url" | "github" | "content";

/** A SkillMD submission as stored in the database. */
export interface Skill {
  id: string;
  name: string;
  author: string | null;
  description: string | null;
  source_type: SkillSourceType;
  source_url: string | null;
  content: string | null;
  endpoints: string | null;
  tags: string | null;
  reachable: boolean | null;
  created_at: string;
}

/** Fields accepted when creating a new SkillMD submission. */
export interface NewSkill {
  name: string;
  author?: string | null;
  description?: string | null;
  source_type: SkillSourceType;
  source_url?: string | null;
  content?: string | null;
  endpoints?: string | null;
  tags?: string | null;
  reachable?: boolean | null;
}

export async function listSkills(): Promise<Skill[]> {
  await ensureSchema();
  const db = sql();
  const rows = await db`
    select id, name, author, description, source_type, source_url,
           content, endpoints, tags, reachable, created_at
    from skills
    order by created_at desc
  `;
  return rows as unknown as Skill[];
}

export async function getSkill(id: string): Promise<Skill | null> {
  await ensureSchema();
  const db = sql();
  const rows = await db`
    select id, name, author, description, source_type, source_url,
           content, endpoints, tags, reachable, created_at
    from skills
    where id = ${id}
  `;
  return (rows as unknown as Skill[])[0] ?? null;
}

export async function createSkill(input: NewSkill): Promise<Skill> {
  await ensureSchema();
  const db = sql();
  const rows = await db`
    insert into skills
      (name, author, description, source_type, source_url, content, endpoints, tags, reachable)
    values
      (${input.name}, ${input.author ?? null}, ${input.description ?? null},
       ${input.source_type}, ${input.source_url ?? null}, ${input.content ?? null},
       ${input.endpoints ?? null}, ${input.tags ?? null}, ${input.reachable ?? null})
    returning id, name, author, description, source_type, source_url,
              content, endpoints, tags, reachable, created_at
  `;
  return (rows as unknown as Skill[])[0];
}
