'use client';

import { useState, useEffect, useCallback } from 'react';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface TocItem {
  id: string;
  label: string;
}

const TOC: TocItem[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'tiers', label: 'Tier 1 vs Tier 2' },
  { id: 'installation', label: 'Installation' },
  { id: 'first-experiment', label: 'Your first experiment' },
  { id: 'scenarios', label: 'Scenario YAML reference' },
  { id: 'layers', label: 'The twelve layers' },
  { id: 'metrics', label: 'Metrics' },
  { id: 'templates', label: 'Agent templates' },
  { id: 'plugins', label: 'Writing a plugin' },
  { id: 'cli', label: 'CLI reference' },
  { id: 'faq', label: 'FAQ' },
];

/* ------------------------------------------------------------------ */
/*  Code blocks                                                        */
/* ------------------------------------------------------------------ */

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [text]);

  return (
    <button
      onClick={handleCopy}
      className="absolute top-3 right-3 rounded-md border border-ink-700 bg-ink-800 px-2.5 py-1 text-[10px] font-medium font-mono uppercase tracking-[0.18em] text-cream-200 transition-all hover:bg-ink-600 hover:text-cream-50"
      aria-label="Copy to clipboard"
    >
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}

function CodeBlock({
  children,
  title,
}: {
  children: string;
  title?: string;
}) {
  return (
    <div className="group relative my-5 overflow-hidden rounded-xl border border-ink-700 bg-ink-900">
      {title && (
        <div className="border-b border-ink-700 bg-ink-800 px-4 py-2.5 font-mono text-[10px] uppercase tracking-[0.2em] text-cream-200">
          {title}
        </div>
      )}
      <CopyButton text={children} />
      <pre className="overflow-x-auto p-5 pr-24 text-[0.85rem] leading-relaxed text-cream-100">
        <code className="font-mono">{children}</code>
      </pre>
    </div>
  );
}

function TerminalBlock({ children }: { children: string }) {
  return (
    <div className="group relative my-5 overflow-hidden rounded-xl border border-ink-700 bg-ink-900">
      <div className="flex items-center gap-2 border-b border-ink-700 bg-ink-800 px-4 py-2.5">
        <span className="h-2.5 w-2.5 rounded-full bg-ink-600" />
        <span className="h-2.5 w-2.5 rounded-full bg-ink-600" />
        <span className="h-2.5 w-2.5 rounded-full bg-ink-600" />
        <span className="ml-2 font-mono text-[10px] uppercase tracking-[0.2em] text-cream-200">
          Terminal
        </span>
      </div>
      <pre className="overflow-x-auto p-5 text-[0.85rem] leading-relaxed text-cream-100">
        <code className="font-mono">{children}</code>
      </pre>
    </div>
  );
}

function InlineCode({ children }: { children: React.ReactNode }) {
  return (
    <code className="rounded-md border border-cream-400/70 bg-cream-200 px-1.5 py-0.5 text-[0.85em] font-mono text-rust">
      {children}
    </code>
  );
}

/* ------------------------------------------------------------------ */
/*  Section wrapper                                                    */
/* ------------------------------------------------------------------ */

function Section({
  id,
  eyebrow,
  title,
  children,
}: {
  id: string;
  eyebrow?: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-20 py-10 first:pt-2">
      {eyebrow && (
        <p className="eyebrow mb-4">{eyebrow}</p>
      )}
      <h2 className="font-display text-[clamp(1.9rem,3vw,2.6rem)] leading-[1.1] tracking-tight text-ink-900 mb-8">
        {title}
      </h2>
      {children}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  Sidebar                                                            */
/* ------------------------------------------------------------------ */

function Sidebar({
  activeId,
  open,
  onClose,
}: {
  activeId: string;
  open: boolean;
  onClose: () => void;
}) {
  return (
    <>
      {open && (
        <div
          className="fixed inset-0 z-40 bg-ink-900/40 backdrop-blur-sm lg:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={`
          fixed top-16 left-0 z-50 h-[calc(100vh-4rem)] w-72 transform border-r border-cream-400/70
          bg-cream-100/95 backdrop-blur-md transition-transform duration-300 ease-in-out
          lg:sticky lg:z-10 lg:translate-x-0 lg:bg-transparent lg:border-r lg:border-cream-400/70
          ${open ? 'translate-x-0' : '-translate-x-full'}
        `}
      >
        <nav className="h-full overflow-y-auto px-7 py-10">
          <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-ink-300 mb-6">
            Documentation
          </p>
          <ul className="space-y-0.5">
            {TOC.map((item) => {
              const isActive = activeId === item.id;
              return (
                <li key={item.id}>
                  <a
                    href={`#${item.id}`}
                    onClick={onClose}
                    className={`
                      flex items-center py-2 text-[0.92rem] transition-all
                      ${
                        isActive
                          ? 'text-ink-900 font-medium'
                          : 'text-ink-400 hover:text-ink-900'
                      }
                    `}
                  >
                    <span
                      className={`mr-3 h-px transition-all ${
                        isActive ? 'w-6 bg-rust' : 'w-3 bg-cream-400'
                      }`}
                    />
                    {item.label}
                  </a>
                </li>
              );
            })}
          </ul>

          <div className="mt-12 rounded-2xl border border-cream-400/70 bg-cream-200 p-5">
            <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-ink-400">
              Need help?
            </p>
            <p className="mt-3 text-[0.88rem] leading-relaxed text-ink-500">
              Open an issue on{' '}
              <a
                href="https://github.com/mariagorskikh/nest/issues"
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-rust hover:text-ink-900 transition-colors"
              >
                GitHub
              </a>
              , or read the source on the same repo.
            </p>
          </div>
        </nav>
      </aside>
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  FAQ item                                                           */
/* ------------------------------------------------------------------ */

function FaqItem({
  question,
  answer,
}: {
  question: string;
  answer: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b border-cream-400/70 last:border-b-0">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between py-6 text-left transition-colors hover:text-rust"
      >
        <span className="font-display text-[1.3rem] leading-tight text-ink-900 pr-8">
          {question}
        </span>
        <span
          className="shrink-0 font-mono text-[0.95rem] text-ink-400 transition-transform"
          style={{ transform: open ? 'rotate(45deg)' : 'none' }}
        >
          +
        </span>
      </button>
      {open && (
        <div className="pb-6 text-[0.98rem] leading-[1.65] text-ink-500">
          {answer}
        </div>
      )}
    </div>
  );
}

/* ================================================================== */
/*  Page                                                               */
/* ================================================================== */

export default function DocsPage() {
  const [activeId, setActiveId] = useState('overview');
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    const ids = TOC.map((t) => t.id);
    const elements = ids
      .map((id) => document.getElementById(id))
      .filter(Boolean) as HTMLElement[];

    if (elements.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => {
            const aIdx = ids.indexOf(a.target.id);
            const bIdx = ids.indexOf(b.target.id);
            return aIdx - bIdx;
          });
        if (visible.length > 0) setActiveId(visible[0].target.id);
      },
      { rootMargin: '-80px 0px -60% 0px', threshold: 0 },
    );
    elements.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, []);

  return (
    <div className="relative min-h-screen bg-cream-100">
      {/* Mobile menu button */}
      <button
        onClick={() => setSidebarOpen(true)}
        className="fixed bottom-6 left-6 z-50 flex items-center gap-2 rounded-full border border-cream-400/70 bg-cream-50 px-4 py-2.5 text-[0.85rem] font-medium text-ink-900 shadow-lg transition-all hover:bg-cream-200 lg:hidden"
        aria-label="Open navigation"
      >
        Contents
      </button>

      <Sidebar
        activeId={activeId}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      {/* Main content */}
      <div className="lg:ml-72">
        <div className="mx-auto max-w-3xl px-6 pb-24 pt-10 lg:px-12">
          {/* Overview */}
          <Section id="overview" title="Overview">
            <p className="mb-5 text-[1.05rem] leading-[1.7] text-ink-500">
              NEST (Network Environment for Swarm Testing) is a sandbox for
              testing how AI agents interact with each other. You define a
              scenario in YAML &mdash; agents, roles, protocol layers, failure
              conditions &mdash; and NEST runs the simulation, recording every
              message in a JSONL trace you can inspect and replay.
            </p>
            <p className="mb-8 text-[1.05rem] leading-[1.7] text-ink-500">
              NEST is built at MIT Media Lab as part of Project NANDA. It is
              open-source research software (Apache 2.0).
            </p>

            <div className="grid gap-3 sm:grid-cols-2">
              {[
                { title: 'Researchers', desc: 'Study emergent behavior, coordination failures, and trust dynamics with full observability.' },
                { title: 'Protocol designers', desc: 'Stress-test your agent protocol with configurable failure injection and deterministic replay.' },
                { title: 'Developers', desc: 'Build and debug multi-agent systems with JSONL traces, metrics, and HTML reports.' },
                { title: 'Students', desc: 'Learn about agent coordination, game theory, and multi-agent interaction hands-on.' },
              ].map((card) => (
                <div key={card.title} className="rounded-xl bg-cream-200 p-6">
                  <p className="font-display text-[1.25rem] text-ink-900 leading-tight">
                    {card.title}
                  </p>
                  <p className="mt-2 text-[0.92rem] leading-[1.6] text-ink-500">
                    {card.desc}
                  </p>
                </div>
              ))}
            </div>
          </Section>

          <div className="h-px bg-cream-400/70" />

          {/* Tiers */}
          <Section id="tiers" title="Tier 1 vs Tier 2">
            <p className="mb-8 text-[1.05rem] leading-[1.7] text-ink-500">
              NEST has two simulation tiers. They share the same scenario format,
              the same twelve protocol layers, and the same trace output &mdash;
              they differ in what drives agent decisions.
            </p>

            <div className="grid gap-5 md:grid-cols-2">
              {/* Tier 1 */}
              <div className="rounded-2xl border border-cream-400/70 bg-cream-50 p-7">
                <div className="flex items-center justify-between">
                  <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-ink-400">
                    Tier 01
                  </p>
                  <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-rust">
                    Deterministic
                  </span>
                </div>
                <h3 className="mt-4 font-display text-[1.7rem] leading-tight text-ink-900">
                  State-machine agents.
                </h3>
                <p className="mt-3 text-[0.95rem] leading-[1.6] text-ink-500">
                  Agents are state machines with hard-coded rules. Same seed
                  produces an identical trace, every time.
                </p>
                <ul className="mt-6 space-y-2.5 text-[0.92rem] text-ink-500">
                  {[
                    ['Reproducible.', 'Same seed produces identical output, bit-for-bit.'],
                    ['Fast.', '10,000+ agents on a laptop, sub-second runs.'],
                    ['Free.', 'No API keys, no internet, no cost per run.'],
                    ['Isolates protocol logic.', 'When something fails, it is the protocol, not the LLM.'],
                  ].map(([head, body]) => (
                    <li key={head} className="flex gap-2.5">
                      <span className="text-rust shrink-0 mt-1 leading-none">·</span>
                      <span>
                        <strong className="text-ink-900 font-medium">{head}</strong>{' '}
                        {body}
                      </span>
                    </li>
                  ))}
                  <li className="flex gap-2.5">
                    <span className="text-ink-300 shrink-0 mt-1 leading-none">·</span>
                    <span>Agents follow fixed rules; no creativity or adaptation.</span>
                  </li>
                </ul>

                <div className="mt-7 border-t border-cream-400/70 pt-5">
                  <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-ink-400">
                    Use Tier 1 to
                  </p>
                  <ul className="mt-3 space-y-1.5 text-[0.88rem] text-ink-500">
                    <li>— Validate protocol correctness before adding LLMs</li>
                    <li>— Run large-scale (1000+) simulations quickly</li>
                    <li>— Reproduce bugs deterministically</li>
                    <li>— Test failure injection (message drops, partitions)</li>
                  </ul>
                </div>
              </div>

              {/* Tier 2 */}
              <div className="rounded-2xl border border-rust/30 bg-rust-bg/40 p-7">
                <div className="flex items-center justify-between">
                  <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-rust">
                    Tier 02
                  </p>
                  <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-ink-400">
                    LLM-backed
                  </span>
                </div>
                <h3 className="mt-4 font-display text-[1.7rem] leading-tight text-ink-900">
                  Real model agents.
                </h3>
                <p className="mt-3 text-[0.95rem] leading-[1.6] text-ink-500">
                  Agents are backed by GPT-4, Claude, or any OpenAI-compatible
                  endpoint. They receive scenario context as a system prompt
                  and decide what to do each tick.
                </p>
                <ul className="mt-6 space-y-2.5 text-[0.92rem] text-ink-500">
                  {[
                    ['Realistic.', 'Agents make decisions like real AI systems.'],
                    ['Emergent behavior.', 'Agents can surprise you.'],
                    ['Custom prompts.', 'YAML templates control each agent’s personality.'],
                  ].map(([head, body]) => (
                    <li key={head} className="flex gap-2.5">
                      <span className="text-rust shrink-0 mt-1 leading-none">·</span>
                      <span>
                        <strong className="text-ink-900 font-medium">{head}</strong>{' '}
                        {body}
                      </span>
                    </li>
                  ))}
                  {[
                    ['Non-deterministic.', 'Different runs yield different traces.'],
                    ['Costs money.', 'Each agent turn is an API call.'],
                    ['Slow.', 'Limited by API latency and rate limits (10–100 agents).'],
                  ].map(([head, body]) => (
                    <li key={head} className="flex gap-2.5">
                      <span className="text-ink-300 shrink-0 mt-1 leading-none">·</span>
                      <span>
                        <strong className="text-ink-700 font-medium">{head}</strong>{' '}
                        {body}
                      </span>
                    </li>
                  ))}
                </ul>

                <div className="mt-7 border-t border-rust/30 pt-5">
                  <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-rust">
                    Use Tier 2 to
                  </p>
                  <ul className="mt-3 space-y-1.5 text-[0.88rem] text-ink-500">
                    <li>— Test how LLMs behave in multi-agent protocols</li>
                    <li>— Benchmark different models on the same scenario</li>
                    <li>— Study emergent coordination and strategic behavior</li>
                    <li>— Evaluate prompt engineering for agent roles</li>
                  </ul>
                </div>
              </div>
            </div>

            <div className="mt-6 rounded-2xl bg-cream-200 p-6">
              <p className="text-[0.98rem] leading-[1.7] text-ink-500">
                <strong className="text-ink-900 font-medium">Recommended workflow.</strong> Start with Tier 1 to
                validate your scenario and protocol logic, then switch to Tier 2 by
                changing <InlineCode>brain: state-machine</InlineCode> to{' '}
                <InlineCode>brain: llm</InlineCode> in your YAML. Everything else
                stays the same &mdash; same layers, same metrics, same trace format.
              </p>
            </div>
          </Section>

          <div className="h-px bg-cream-400/70" />

          {/* Installation */}
          <Section id="installation" title="Installation">
            <h3 className="text-[1.15rem] font-medium text-ink-900 mb-3">
              Quick install (from PyPI)
            </h3>
            <CodeBlock>pip install &quot;nest-core[plugins]&quot;</CodeBlock>
            <p className="mb-8 text-[0.95rem] text-ink-500">
              This installs the NEST engine, CLI, and all twelve default
              plugins. Requires <strong className="text-ink-900">Python 3.12+</strong>.
            </p>

            <h3 className="text-[1.15rem] font-medium text-ink-900 mb-3">
              Or: install from source (development)
            </h3>
            <ul className="mb-4 space-y-1.5 text-[0.95rem] text-ink-500">
              <li>
                — <strong className="text-ink-900">Python 3.12+</strong>: check with{' '}
                <InlineCode>python --version</InlineCode>
              </li>
              <li>
                — <strong className="text-ink-900">uv</strong> (recommended):{' '}
                <InlineCode>pip install uv</InlineCode>
              </li>
            </ul>
            <CodeBlock>pip install &quot;nest-core[plugins]&quot;</CodeBlock>

            <p className="mt-4 text-[0.95rem] text-ink-500">
              This installs the CLI, the reference plugins for all 12 layers,
              and the seven built-in scenarios. To hack on NEST itself instead:
            </p>
            <CodeBlock>
{`git clone https://github.com/mariagorskikh/nest.git
cd nest
uv sync`}
            </CodeBlock>

            <h3 className="mt-8 text-[1.15rem] font-medium text-ink-900 mb-3">
              Verify your installation
            </h3>
            <CodeBlock>nest doctor</CodeBlock>

            <TerminalBlock>
{`$ nest doctor
NEST doctor
========================================
  [OK] Python 3.12.9
  [OK] nest-core
  [OK] scenario loader
  [OK] plugin registry
  [OK] scenario runner
  [OK] simulator
  [OK] all 12 default plugins resolve
========================================
7/7 checks passed`}
            </TerminalBlock>

            <h3 className="mt-8 text-[1.15rem] font-medium text-ink-900 mb-3">
              For Tier 2 (LLM agents)
            </h3>
            <p className="mb-3 text-[0.95rem] text-ink-500">
              If you want to run LLM-backed agents, set your API key:
            </p>
            <CodeBlock>
{`# OpenAI
export OPENAI_API_KEY="sk-..."

# or Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."`}
            </CodeBlock>
          </Section>

          <div className="h-px bg-cream-400/70" />

          {/* First experiment */}
          <Section id="first-experiment" title="Your first experiment">
            <p className="mb-8 text-[1.05rem] leading-[1.7] text-ink-500">
              Run a marketplace simulation end-to-end in three steps.
              Fifty buyers and fifty sellers negotiate prices over ten rounds.
            </p>

            {[
              {
                step: '01',
                title: 'Run the scenario',
                code: 'nest run marketplace',
                note: (
                  <>
                    This creates the agents, runs the simulation, and writes
                    the trace to <InlineCode>traces/marketplace.jsonl</InlineCode>.
                  </>
                ),
              },
              {
                step: '02',
                title: 'Inspect the trace',
                code: 'nest inspect traces/marketplace.jsonl',
                note: 'Shows a summary of every event: sends, receives, drops, per-agent stats, and timing.',
              },
              {
                step: '03',
                title: 'Generate an HTML report',
                code: 'nest report traces/marketplace.jsonl -o report.html',
                note: 'Produces an HTML page with delivery rate, deal rate, latency, throughput, per-agent breakdown, and event summary.',
              },
            ].map((step) => (
              <div key={step.step} className="mb-10">
                <div className="flex items-baseline gap-4">
                  <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-rust">
                    {step.step}
                  </span>
                  <h3 className="font-display text-[1.5rem] leading-tight text-ink-900">
                    {step.title}
                  </h3>
                </div>
                <CodeBlock>{step.code}</CodeBlock>
                <p className="mt-2 text-[0.9rem] text-ink-400">{step.note}</p>
              </div>
            ))}
          </Section>

          <div className="h-px bg-cream-400/70" />

          {/* Scenarios */}
          <Section id="scenarios" title="Scenario YAML reference">
            <p className="mb-6 text-[1.05rem] leading-[1.7] text-ink-500">
              A scenario YAML defines everything about a simulation run. Here
              is a complete, annotated example matching the actual schema.
            </p>

            <CodeBlock title="scenarios/marketplace.yaml">
{`name: marketplace
description: "50 buyers and 50 sellers trading products."

tier: 1                           # 1 = state-machine, 2 = LLM
seed: 42                          # RNG seed (deterministic replay)

agents:
  count: 100                      # Total agent count
  brain: state-machine            # "state-machine" or "llm"
  # llm_provider: openai          # For Tier 2: openai or anthropic
  # llm_model: gpt-4o-mini        # For Tier 2: model name
  roles:
    - name: buyer
      count: 50
    - name: seller
      count: 50

layers:                           # Plugin name for each protocol layer
  transport: in_memory
  comms: nest_native
  identity: did_key
  registry: in_memory
  auth: jwt
  trust: score_average
  payments: prepaid_credits
  coordination: contract_net
  negotiation: alternating_offers
  memory: blackboard
  privacy: noop
  datafacts: datafacts_v1

task:
  type: marketplace               # Scenario type
  config:
    rounds: 10                    # Scenario-specific config

failures:                         # Failure injection
  message_drop: 0.0              # 0.0 = no drops, 0.1 = 10% drop rate
  byzantine_agents: 0.0          # Fraction of agents that garble messages
  # network_partition:            # Split agents into isolated groups
  #   groups: [["buyer-0"], ["seller-0"]]

duration: "ticks: 10000"          # Max simulation ticks

metrics:                          # Which metrics to compute
  - delivery_rate
  - deal_rate
  - mean_latency
  - message_count
  - agent_count

output:
  trace: ./traces/marketplace.jsonl
  # report: ./reports/marketplace.html  # Optional HTML report`}
            </CodeBlock>

            <h3 className="mt-10 mb-4 text-[1.15rem] font-medium text-ink-900">
              Available scenarios
            </h3>
            <RefTable
              head={['File', 'Description', 'Agents']}
              rows={[
                ['marketplace.yaml', 'Buyers and sellers negotiate prices', '50 buyers + 50 sellers'],
                ['auction.yaml', 'Sealed-bid auction with auctioneer', '1 auctioneer + 49 bidders'],
                ['voting.yaml', 'Proposer, voters, and coordinator', '1 proposer + 20 voters + 1 coordinator'],
                ['consensus.yaml', 'Leader-based quorum voting', '1 leader + 19 followers'],
                ['supply_chain.yaml', '4-hop supply chain pipeline', 'supplier, manufacturer, distributor, retailer'],
                ['reputation.yaml', 'Honest and malicious traders with observer', '6 honest + 2 malicious + 1 observer'],
              ]}
              monoFirstCol
            />
          </Section>

          <div className="h-px bg-cream-400/70" />

          {/* Layers */}
          <Section id="layers" title="The twelve layers">
            <p className="mb-6 text-[1.05rem] leading-[1.7] text-ink-500">
              NEST organises agent capabilities into twelve protocol layers. Each
              layer has a default reference implementation you can swap out.
              Agents access layers via{' '}
              <InlineCode>ctx.plugins.get(&quot;layer_name&quot;)</InlineCode>.
            </p>

            <RefTable
              head={['Layer', 'What it does', 'Default']}
              rows={[
                ['Transport', 'Moves messages between agents', 'in_memory'],
                ['Comms', 'Structures message formats', 'nest_native'],
                ['Identity', 'Assigns and verifies agent identities', 'did_key'],
                ['Registry', 'Agent discovery and service lookup', 'in_memory'],
                ['Auth', 'Authentication and permissions', 'jwt'],
                ['Trust', 'Calculates and updates reputation scores', 'score_average'],
                ['Payments', 'Virtual currency balance and transfers', 'prepaid_credits'],
                ['Coordination', 'Orchestrates multi-agent workflows', 'contract_net'],
                ['Negotiation', 'Runs negotiation protocols', 'alternating_offers'],
                ['Memory', 'Stores and retrieves agent memory', 'blackboard'],
                ['Privacy', 'Enforces data-sharing boundaries', 'noop'],
                ['Data Facts', 'Validates and attests to data claims', 'datafacts_v1'],
              ]}
              monoLastCol
            />

            <p className="mt-5 text-[0.9rem] leading-[1.6] text-ink-400">
              Currently, the marketplace scenario uses registry, identity,
              trust, and payments layers. Other scenarios use the layers
              passively (they are resolved but agents do not yet call them).
              Wiring more scenarios to use layers is in progress.
            </p>
          </Section>

          <div className="h-px bg-cream-400/70" />

          {/* Metrics */}
          <Section id="metrics" title="Metrics">
            <p className="mb-6 text-[1.05rem] leading-[1.7] text-ink-500">
              NEST computes metrics from the JSONL trace after each run. Specify
              which metrics you want in the scenario YAML. There is no single
              composite score &mdash; each metric measures something specific.
            </p>

            <RefTable
              head={['Metric', 'What it measures']}
              rows={[
                ['delivery_rate', 'Fraction of sent messages that were received. 100% in Tier 1 with no message drops.'],
                ['deal_rate', 'Percentage of buy requests that resulted in a trade. Marketplace and auction only.'],
                ['rejection_rate', 'Percentage of buy requests that were rejected. Marketplace only.'],
                ['mean_rounds_to_deal', 'Average negotiation rounds before a successful trade.'],
                ['mean_latency', 'Average time (ticks) between a send and its correlated receive.'],
                ['message_count', 'Total number of send + receive events in the trace.'],
                ['dropped_count', 'Number of messages dropped by failure injection.'],
                ['agent_count', 'Number of distinct agents that participated.'],
                ['duration', 'Time span from first to last event (ticks).'],
                ['throughput', 'Messages per tick across all agents.'],
                ['unique_pairs', 'Number of unique agent pairs that exchanged messages.'],
              ]}
              monoFirstCol
            />
          </Section>

          <div className="h-px bg-cream-400/70" />

          {/* Templates */}
          <Section id="templates" title="Agent templates (Tier 2)">
            <p className="mb-6 text-[1.05rem] leading-[1.7] text-ink-500">
              Templates are YAML files that define LLM-backed agent behaviour:
              system prompt, provider, model, and parameters. They are only
              used in Tier 2 scenarios.
            </p>

            <CodeBlock title="templates/agents/marketplace-buyer.yaml">
{`name: marketplace-buyer
description: "Buyer agent for marketplace scenarios."
provider: openai
model: gpt-4o-mini
temperature: 0.7
max_tokens: 256
system_prompt: |
  You are a buyer in a marketplace simulation.

  ACTION: send
  TO: <agent-id>
  MESSAGE: <message-content>

  Rules:
  - Send buy:<product>:<price> to purchase.
  - If rejected, increase your offer or try another seller.`}
            </CodeBlock>

            <h3 className="mt-8 mb-3 text-[1.15rem] font-medium text-ink-900">
              CLI commands
            </h3>
            <CodeBlock>
{`nest templates list              # List all templates
nest templates show <name>       # View a template
nest templates create <name>     # Create from scratch
nest templates duplicate <src> <dest>  # Copy and modify`}
            </CodeBlock>
          </Section>

          <div className="h-px bg-cream-400/70" />

          {/* Plugins */}
          <Section id="plugins" title="Writing a plugin">
            <p className="mb-6 text-[1.05rem] leading-[1.7] text-ink-500">
              You can replace any of the twelve layers with your own implementation.
              A plugin is a Python class that matches the expected interface,
              registered via Python entry points.
            </p>

            <h3 className="mb-3 text-[1.15rem] font-medium text-ink-900">
              Example: custom trust plugin
            </h3>
            <p className="mb-3 text-[0.95rem] text-ink-500">
              Look at the reference implementations in{' '}
              <InlineCode>packages/nest-plugins-reference/</InlineCode> for
              the interface each layer expects. Here is a trust plugin:
            </p>
            <CodeBlock title="my_trust/plugin.py">
{`from nest_core.types import AgentId, Evidence, ReputationScore

class DecayTrust:
    """Custom trust layer with time decay."""

    def __init__(self, identity=None):
        self._scores: dict[AgentId, list[float]] = {}

    async def score(self, agent: AgentId) -> ReputationScore:
        entries = self._scores.get(agent, [])
        if not entries:
            return ReputationScore(
                agent_id=agent, score=0.5,
                confidence=0.0, sample_count=0,
            )
        avg = sum(entries) / len(entries)
        return ReputationScore(
            agent_id=agent, score=avg,
            confidence=min(1.0, len(entries) / 50),
            sample_count=len(entries),
        )

    async def report(self, agent: AgentId, evidence: Evidence):
        val = 1.0 if evidence.kind == "positive" else 0.0
        self._scores.setdefault(agent, []).append(val)`}
            </CodeBlock>

            <h3 className="mt-8 mb-3 text-[1.15rem] font-medium text-ink-900">
              Register via entry point
            </h3>
            <CodeBlock title="pyproject.toml">
{`[project]
name = "my-trust-plugin"
version = "0.1.0"
dependencies = ["nest-core"]

[project.entry-points."nest.plugins.trust"]
my_decay = "my_trust.plugin:DecayTrust"`}
            </CodeBlock>

            <p className="mt-4 text-[0.95rem] text-ink-500">
              Then reference it in your scenario YAML:
            </p>
            <CodeBlock>
{`layers:
  trust: my_decay  # Uses your custom plugin`}
            </CodeBlock>
          </Section>

          <div className="h-px bg-cream-400/70" />

          {/* CLI */}
          <Section id="cli" title="CLI reference">
            <p className="mb-6 text-[1.05rem] leading-[1.7] text-ink-500">
              After installing with{' '}
              <InlineCode>pip install &quot;nest-core[plugins]&quot;</InlineCode>,
              all commands are available via the <InlineCode>nest</InlineCode> CLI.
            </p>

            <RefTable
              head={['Command', 'Description']}
              rows={[
                ['nest run <name | path.yaml>', 'Run a built-in scenario by name or a local YAML file and write its trace'],
                ['nest scenarios list / show / cp', 'List, print, or copy the seven built-in scenarios'],
                ['nest inspect <trace.jsonl>', 'Print event summary and per-agent stats'],
                ['nest report <trace.jsonl>', 'Generate an HTML metrics report'],
                ['nest init <name>', 'Scaffold a new scenario YAML'],
                ['nest doctor', 'Check installation health and plugin status'],
                ['nest version', 'Print the installed NEST version'],
                ['nest dashboard [trace.jsonl]', 'Open the interactive trace viewer in a browser'],
                ['nest plugins list', 'List all installed layer plugins'],
                ['nest templates list', 'List available agent templates'],
                ['nest templates show <name>', 'Display a template'],
                ['nest templates create <name>', 'Create a new agent template'],
                ['nest templates duplicate <src> <dest>', 'Copy a template'],
              ]}
              monoFirstCol
            />
          </Section>

          <div className="h-px bg-cream-400/70" />

          {/* FAQ */}
          <Section id="faq" title="FAQ">
            <div className="rounded-2xl border border-cream-400/70 bg-cream-50 px-7">
              <FaqItem
                question="Can I pip install this?"
                answer={
                  <p>
                    Yes. Run <InlineCode>pip install &quot;nest-core[plugins]&quot;</InlineCode> and
                    you are ready to go. This installs the engine, CLI, and all
                    twelve default plugins.
                  </p>
                }
              />
              <FaqItem
                question="Do I need an API key?"
                answer={
                  <p>
                    Only for <strong className="text-ink-900">Tier 2</strong> (LLM-backed) scenarios. Set{' '}
                    <InlineCode>OPENAI_API_KEY</InlineCode> or{' '}
                    <InlineCode>ANTHROPIC_API_KEY</InlineCode>. Tier 1 runs
                    entirely locally with no API calls.
                  </p>
                }
              />
              <FaqItem
                question="How many agents can NEST handle?"
                answer={
                  <p>
                    <strong className="text-ink-900">Tier 1:</strong> 10,000+ agents on a modern laptop,
                    sub-second runs. <strong className="text-ink-900">Tier 2:</strong> 10&ndash;100
                    agents, limited by API rate limits and cost.
                  </p>
                }
              />
              <FaqItem
                question="Can I use my own LLM?"
                answer={
                  <p>
                    Yes. Set <InlineCode>llm_provider</InlineCode> and{' '}
                    <InlineCode>llm_model</InlineCode> in your scenario YAML.
                    NEST supports OpenAI, Anthropic, and any OpenAI-compatible
                    endpoint.
                  </p>
                }
              />
              <FaqItem
                question="Is NEST production-ready?"
                answer={
                  <p>
                    No. NEST is research software in active development. It is
                    excellent for experimentation and benchmarking but APIs may
                    change between releases.
                  </p>
                }
              />
              <FaqItem
                question="What does Tier 1 actually test if agents are scripted?"
                answer={
                  <p>
                    Tier 1 tests the <em>protocol</em>, not the agents. It
                    answers: <em>if every agent follows the rules perfectly,
                    does the protocol still work under message drops, network
                    partitions, and Byzantine failures?</em> This is the same
                    logic behind TLA+ model checking &mdash; verify the design
                    before adding implementation complexity.
                  </p>
                }
              />
            </div>
          </Section>

          {/* Footer CTA */}
          <div className="mt-12 rounded-2xl bg-ink-900 text-cream-50 p-10 sm:p-14 text-center">
            <h3 className="font-display text-[clamp(2rem,4vw,3rem)] leading-tight tracking-tight">
              Ready to start?
            </h3>
            <p className="mx-auto mt-4 max-w-md text-[1rem] leading-[1.65] text-cream-200">
              Clone the repo and run your first simulation in under two minutes.
            </p>
            <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <a
                href="#installation"
                className="inline-flex items-center justify-center rounded-md bg-cream-50 text-ink-900 px-6 py-2.5 text-[0.9rem] font-medium hover:bg-cream-200 transition-colors"
              >
                Get started
              </a>
              <a
                href="https://github.com/mariagorskikh/nest"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center justify-center rounded-md border border-cream-200/30 px-6 py-2.5 text-[0.9rem] font-medium text-cream-100 hover:bg-ink-700 transition-colors"
              >
                View on GitHub
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Shared: reference table                                            */
/* ------------------------------------------------------------------ */

function RefTable({
  head,
  rows,
  monoFirstCol,
  monoLastCol,
}: {
  head: string[];
  rows: string[][];
  monoFirstCol?: boolean;
  monoLastCol?: boolean;
}) {
  return (
    <div className="overflow-x-auto rounded-2xl border border-cream-400/70 bg-cream-50">
      <table className="w-full text-[0.92rem]">
        <thead>
          <tr className="border-b border-cream-400/70 bg-cream-200">
            {head.map((h) => (
              <th
                key={h}
                className="px-4 py-3.5 text-left font-mono text-[10px] uppercase tracking-[0.22em] text-ink-400"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-cream-400/40">
          {rows.map((row, i) => (
            <tr key={i} className="hover:bg-cream-200/60 transition-colors">
              {row.map((cell, j) => {
                const isFirst = j === 0;
                const isLast = j === row.length - 1;
                const isMono =
                  (monoFirstCol && isFirst) || (monoLastCol && isLast);
                return (
                  <td
                    key={j}
                    className={`px-4 py-3 ${
                      isMono
                        ? 'font-mono text-[0.82rem] text-rust whitespace-nowrap'
                        : isFirst
                          ? 'font-medium text-ink-900 whitespace-nowrap'
                          : 'text-ink-500'
                    }`}
                  >
                    {cell}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
