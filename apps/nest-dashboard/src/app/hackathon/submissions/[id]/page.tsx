/**
 * /hackathon/submissions/[id] — full detail view for one PR.
 *
 * Header → author block → judge breakdown → diff stats → links out
 * to the PR and the raw diff.
 */

import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  findSubmissionById,
  formatLinesAdded,
  formatScore,
  loadDataset,
  SCORE_DIMENSIONS,
  SCORE_DIMENSION_MAX,
  SCORE_TOTAL_MAX,
  type ScoreDimension,
} from "@/lib/hackathon";
import { AuthorBadge } from "@/components/hackathon-card";

export const revalidate = 300;

export async function generateStaticParams() {
  const data = await loadDataset();
  return data.submissions.map((s) => ({ id: s.id }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const data = await loadDataset();
  const sub = findSubmissionById(data, id);
  if (!sub) return { title: "Submission not found — NEST" };
  return {
    title: `${sub.title.replace(/^\[Hackathon\]\s*/i, "")} — NEST`,
    description: sub.short_description,
  };
}

function ScoreBar({
  label,
  value,
}: {
  label: string;
  value: number | null;
}) {
  // Dimensions are scored 1-5 per the rubric in scripts/judge/rubric.md;
  // the bar fills proportionally against SCORE_DIMENSION_MAX (5).
  const width =
    value === null
      ? 0
      : Math.min(100, Math.max(0, (value / SCORE_DIMENSION_MAX) * 100));
  return (
    <div>
      <div className="flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.18em] text-ink-400">
        <span>{label}</span>
        <span className="tabular-nums text-ink-900">
          {value === null ? "—" : `${value.toFixed(0)}/${SCORE_DIMENSION_MAX}`}
        </span>
      </div>
      <div className="mt-2 h-1 w-full rounded-full bg-cream-300 overflow-hidden">
        <div
          className="h-1 rounded-full bg-rust"
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  );
}

export default async function SubmissionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const data = await loadDataset();
  const sub = findSubmissionById(data, id);
  if (!sub) {
    notFound();
  }

  const score = sub.score;
  const layer = data.layers.find((l) => l.key === sub.layer);
  const totalScore = score?.total ?? null;

  return (
    <div className="bg-cream-100">
      <section className="paper-texture border-b border-cream-400/70">
        <div className="mx-auto max-w-[1240px] px-6 sm:px-10 pt-16 pb-12">
          <div className="flex flex-wrap items-center gap-4 mb-8 animate-fade-in">
            <Link
              href="/hackathon"
              className="font-mono text-[10px] uppercase tracking-[0.22em] text-ink-300 hover:text-ink-900"
            >
              ← Hackathon
            </Link>
            {layer && (
              <Link
                href={`/hackathon/layers/${layer.key}`}
                className="font-mono text-[10px] uppercase tracking-[0.22em] text-ink-300 hover:text-ink-900"
              >
                ↳ {layer.label} layer
              </Link>
            )}
          </div>

          <div className="grid gap-10 lg:grid-cols-[1.5fr_1fr] lg:items-start">
            <div>
              <div className="flex flex-wrap items-center gap-2 mb-6">
                <AuthorBadge submission={sub} />
                <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-ink-300">
                  PR #{sub.pr_number}
                </span>
                {layer && (
                  <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-ink-300">
                    {layer.label}
                  </span>
                )}
              </div>
              <h1 className="font-display animate-fade-in stagger-1 text-[clamp(2rem,4.6vw,3.4rem)] leading-[1.06] tracking-tight text-ink-900">
                {sub.title.replace(/^\[Hackathon\]\s*/i, "")}
              </h1>
              <p className="mt-6 text-[1.05rem] leading-[1.65] text-ink-500 max-w-2xl">
                {sub.short_description || "No description provided."}
              </p>
            </div>

            {/* Author block */}
            <div className="rounded-2xl border border-cream-400/70 bg-cream-50 p-6">
              <p className="eyebrow">Author</p>
              <div className="mt-4 flex items-center gap-4">
                <Image
                  src={sub.author.avatar_url}
                  alt={`${sub.author.handle} avatar`}
                  width={64}
                  height={64}
                  className="h-16 w-16 rounded-full border border-cream-400/70 object-cover bg-cream-200"
                  unoptimized
                />
                <div className="min-w-0">
                  <p className="font-display text-[1.4rem] leading-tight text-ink-900">
                    @{sub.author.handle}
                  </p>
                  <a
                    href={sub.author.profile_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-mono text-[10px] uppercase tracking-[0.18em] text-ink-400 hover:text-ink-900"
                  >
                    github profile →
                  </a>
                </div>
              </div>
              <dl className="mt-6 grid grid-cols-2 gap-x-4 gap-y-3 font-mono text-[10px] uppercase tracking-[0.18em] text-ink-400">
                <div>
                  <dt>Lines added</dt>
                  <dd className="mt-1 font-display text-[1.15rem] leading-none text-ink-900 tabular-nums">
                    +{formatLinesAdded(sub.additions ?? 0)}
                  </dd>
                </div>
                <div>
                  <dt>Lines removed</dt>
                  <dd className="mt-1 font-display text-[1.15rem] leading-none text-ink-900 tabular-nums">
                    −{formatLinesAdded(sub.deletions ?? 0)}
                  </dd>
                </div>
                <div>
                  <dt>Files</dt>
                  <dd className="mt-1 font-display text-[1.15rem] leading-none text-ink-900 tabular-nums">
                    {sub.changed_files ?? 0}
                  </dd>
                </div>
                <div>
                  <dt>Branch</dt>
                  <dd className="mt-1 text-[0.78rem] text-ink-500 truncate normal-case tracking-normal font-mono">
                    {sub.branch}
                  </dd>
                </div>
              </dl>
            </div>
          </div>
        </div>
      </section>

      {/* Judge score breakdown */}
      <section className="border-b border-cream-400/70">
        <div className="mx-auto max-w-[1240px] px-6 sm:px-10 py-12 grid gap-10 lg:grid-cols-[1fr_2fr]">
          <div>
            <p className="eyebrow">Judge score</p>
            <h2 className="mt-4 font-display text-[1.8rem] leading-[1.1] text-ink-900">
              {totalScore !== null ? (
                <>
                  <span className="tabular-nums">
                    {formatScore(totalScore)}
                  </span>
                  <span className="text-ink-300"> / {SCORE_TOTAL_MAX}</span>
                </>
              ) : (
                <span className="italic text-ink-400">unscored</span>
              )}
            </h2>
            {totalScore === null && (
              <p className="mt-3 text-[0.92rem] text-ink-500 max-w-xs">
                Judging in progress. Scores publish to{" "}
                <code className="font-mono text-[0.8rem] bg-cream-200 px-1 rounded">
                  docs/hackathon/scores.json
                </code>{" "}
                and rebuild this page within five minutes.
              </p>
            )}
            {score?.notes && (
              <p className="mt-4 text-[0.92rem] leading-[1.55] text-ink-500 italic max-w-md">
                &ldquo;{score.notes}&rdquo;
              </p>
            )}
          </div>

          <div className="rounded-2xl border border-cream-400/70 bg-cream-50 p-7 grid gap-6 md:grid-cols-2">
            {SCORE_DIMENSIONS.map(({ key, label }) => (
              <ScoreBar
                key={key}
                label={label}
                value={
                  score
                    ? (score[key as ScoreDimension] as number | null)
                    : null
                }
              />
            ))}
          </div>
        </div>
      </section>

      {/* Body + links */}
      <section>
        <div className="mx-auto max-w-[1240px] px-6 sm:px-10 py-12 grid gap-10 lg:grid-cols-[2fr_1fr]">
          <div>
            <p className="eyebrow">Description</p>
            <h2 className="mt-4 font-display text-[1.8rem] leading-[1.1] text-ink-900">
              The pitch.
            </h2>
            <pre className="mt-6 max-h-[60vh] overflow-auto rounded-2xl border border-cream-400/70 bg-cream-50 p-6 text-[0.88rem] leading-[1.55] text-ink-700 font-sans whitespace-pre-wrap">
              {sub.body_markdown || "No PR body provided."}
            </pre>
          </div>

          <div className="space-y-3">
            <p className="eyebrow">Try it</p>
            <a
              href={sub.pr_url}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-primary w-full justify-center"
            >
              Open PR on GitHub
            </a>
            <a
              href={sub.diff_url}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-secondary w-full justify-center"
            >
              View diff
            </a>
            <div className="rounded-2xl border border-cream-400/70 bg-cream-50 p-5 mt-6 text-[0.85rem] leading-[1.55] text-ink-500">
              <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-ink-300">
                Checkout locally
              </p>
              <code className="mt-3 block font-mono text-[0.78rem] text-ink-700 break-all">
                git fetch origin {sub.branch}
                <br />
                git checkout {sub.branch}
              </code>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
