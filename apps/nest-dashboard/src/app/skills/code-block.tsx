"use client";

import { useCallback, useState } from "react";

/**
 * Dark code block with a copy button — matches the look used on the Docs page.
 */
export function CodeBlock({
  children,
  title,
}: {
  children: string;
  title?: string;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(children).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [children]);

  return (
    <div className="group relative my-5 overflow-hidden rounded-xl border border-ink-700 bg-ink-900">
      {title && (
        <div className="border-b border-ink-700 bg-ink-800 px-4 py-2.5 font-mono text-[10px] uppercase tracking-[0.2em] text-cream-200">
          {title}
        </div>
      )}
      <button
        onClick={handleCopy}
        className="absolute top-3 right-3 rounded-md border border-ink-700 bg-ink-800 px-2.5 py-1 text-[10px] font-medium font-mono uppercase tracking-[0.18em] text-cream-200 transition-all hover:bg-ink-600 hover:text-cream-50"
        aria-label="Copy to clipboard"
        type="button"
      >
        {copied ? "Copied" : "Copy"}
      </button>
      <pre className="overflow-x-auto p-5 pr-24 text-[0.85rem] leading-relaxed text-cream-100">
        <code className="font-mono">{children}</code>
      </pre>
    </div>
  );
}
