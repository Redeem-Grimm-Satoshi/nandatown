/**
 * /hackathon/layers — the 12-layer grid.
 *
 * One card per layer. Shows submission count, top score, and an
 * "open for submissions" affordance on empty layers.
 */

import Link from "next/link";
import { formatScore, loadDataset } from "@/lib/hackathon";

export const revalidate = 300;

export const metadata = {
  title: "Hackathon layers — NEST",
  description:
    "Browse hackathon submissions by the 12 NEST protocol layers.",
};

export default async function HackathonLayersPage() {
  const data = await loadDataset();

  return (
    <div className="bg-cream-100">
      <section className="paper-texture border-b border-cream-400/70">
        <div className="mx-auto max-w-[1240px] px-6 sm:px-10 pt-16 pb-12">
          <div className="flex items-center gap-3 mb-8 animate-fade-in">
            <Link
              href="/hackathon"
              className="font-mono text-[10px] uppercase tracking-[0.22em] text-ink-300 hover:text-ink-900"
            >
              ← Hackathon
            </Link>
          </div>

          <div className="grid gap-12 lg:grid-cols-[1.4fr_1fr] lg:items-end">
            <h1 className="font-display animate-fade-in stagger-1 text-[clamp(2.4rem,5.4vw,4.2rem)] leading-[1.04] tracking-tight text-ink-900">
              Twelve layers.
              <br />
              <span className="italic text-ink-700">One stack.</span>
            </h1>
            <p className="animate-fade-in stagger-2 text-[1.05rem] leading-[1.6] text-ink-500 max-w-md">
              Every NEST scenario picks one plugin per layer. The grid below
              shows which layers have hackathon submissions and which are
              still open. Click any layer to see its entries.
            </p>
          </div>
        </div>
      </section>

      <section>
        <div className="mx-auto max-w-[1240px] px-6 sm:px-10 py-12">
          <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
            {data.layers.map((layer, idx) => (
              <Link
                key={layer.key}
                href={`/hackathon/layers/${layer.key}`}
                className="group block rounded-2xl border border-cream-400/70 bg-cream-50 p-7 transition-colors hover:bg-cream-200/60"
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-ink-300 tabular-nums">
                    {String(idx + 1).padStart(2, "0")}
                  </span>
                  {layer.is_open ? (
                    <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-mono uppercase tracking-[0.18em] border border-dashed border-cream-400 text-ink-400">
                      open
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-mono uppercase tracking-[0.18em] bg-rust-bg text-rust border border-rust-soft/60">
                      {layer.submission_count}{" "}
                      {layer.submission_count === 1 ? "PR" : "PRs"}
                    </span>
                  )}
                </div>

                <h3 className="mt-5 font-display text-[1.6rem] leading-[1.15] text-ink-900 group-hover:text-ink-700">
                  {layer.label}
                </h3>
                <p className="mt-2 text-[0.92rem] leading-[1.55] text-ink-500">
                  {layer.blurb}
                </p>

                <div className="mt-5 flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.18em] text-ink-400">
                  <span>
                    {layer.is_open ? "open for submissions" : "top score"}
                  </span>
                  <span className="tabular-nums text-ink-700">
                    {layer.is_open
                      ? "—"
                      : layer.top_score !== null
                        ? formatScore(layer.top_score)
                        : "unscored"}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
