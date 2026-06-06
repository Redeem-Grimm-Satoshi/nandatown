import type { NextRequest } from "next/server";
import { getSkill } from "@/lib/skills";

export const dynamic = "force-dynamic";

const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * GET /api/skills/[id]
 * Returns one SkillMD — its metadata plus the instructions (the `content`
 * field for pasted skills, or the `source_url` to fetch for hosted ones).
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  if (!UUID.test(id)) {
    return Response.json({ error: "Not found." }, { status: 404 });
  }
  const skill = await getSkill(id);
  if (!skill) {
    return Response.json({ error: "Not found." }, { status: 404 });
  }
  return Response.json({ skill });
}
