"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import type { JobStatus, Status } from "@/lib/api";

const LINKS = [
  ["/", "Overview"],
  ["/profile", "Profile"],
  ["/resources", "Resources"],
  ["/jobs", "Jobs"],
  ["/earnings", "Earnings"],
];

export function Shell({ error, children }: { error?: string | null; children: ReactNode }) {
  const path = usePathname();
  return (
    <div
      className="py-6 sm:py-10"
      // 30px side margin on phones, growing linearly to 225px from 1280px wide upward
      style={{ paddingInline: "clamp(30px, calc(30px + (100% - 480px) * 0.24375), 225px)" }}
    >
      <nav className="mb-8 flex flex-wrap gap-1 border-b border-zinc-200 dark:border-zinc-800">
        {LINKS.map(([href, label]) => (
          <Link
            key={href}
            href={href}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${
              path === href
                ? "border-emerald-500 font-medium"
                : "border-transparent text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
            }`}
          >
            {label}
          </Link>
        ))}
      </nav>
      {error && (
        <p role="alert" className="mb-6 rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
      {children}
    </div>
  );
}

const STATE: Record<Status["state"], [string, string]> = {
  online: ["Online", "bg-emerald-500"],
  connecting: ["Connecting…", "bg-amber-500 animate-pulse"],
  draining: ["Finishing current job…", "bg-amber-500 animate-pulse"],
  offline: ["Offline", "bg-zinc-400"],
};

export function StateBadge({ state }: { state: Status["state"] }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-zinc-500">
      <span className={`h-2.5 w-2.5 rounded-full ${STATE[state][1]}`} />
      {STATE[state][0]}
    </span>
  );
}

export function Switch({
  on, disabled, label, onChange,
}: { on: boolean; disabled?: boolean; label: string; onChange: (next: boolean) => void }) {
  return (
    <button
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={`relative h-8 w-14 shrink-0 rounded-full transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-500 disabled:opacity-40 ${
        on ? "bg-emerald-500" : "bg-zinc-300 dark:bg-zinc-700"
      }`}
    >
      <span className={`absolute left-1 top-1 h-6 w-6 rounded-full bg-white transition-transform ${on ? "translate-x-6" : ""}`} />
    </button>
  );
}

export function Stat({ label, value, hint, href }: { label: string; value: string; hint?: string; href?: string }) {
  const body = (
    <>
      <div className="text-sm text-zinc-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums tracking-tight">{value}</div>
      {hint && <div className="mt-1 text-xs text-zinc-500">{hint}</div>}
    </>
  );
  const cls = "block bg-white p-4 dark:bg-zinc-950";
  return href ? <Link href={href} className={`${cls} hover:bg-zinc-50 dark:hover:bg-zinc-900`}>{body}</Link> : <div className={cls}>{body}</div>;
}

export function StatGrid({ children }: { children: ReactNode }) {
  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-zinc-200 bg-zinc-200 dark:border-zinc-800 dark:bg-zinc-800 sm:grid-cols-4">
      {children}
    </div>
  );
}

export function Bars({ data, unit = "" }: { data: { label: string; value: number }[]; unit?: string }) {
  const max = Math.max(...data.map((d) => d.value), 1);
  return (
    <div>
      <div className="flex h-40 items-end gap-2 border-b border-zinc-300 dark:border-zinc-700">
        {data.map((d, i) => (
          <div key={i} className="flex h-full flex-1 flex-col justify-end" title={`${d.label}: ${d.value.toFixed(2)}${unit}`}>
            <div className="mx-auto w-full max-w-14 rounded-t bg-emerald-500" style={{ height: `${(d.value / max) * 100}%` }} />
          </div>
        ))}
      </div>
      <div className="mt-1 flex gap-2">
        {data.map((d, i) => (
          <span key={i} className="flex-1 text-center text-xs text-zinc-500">{d.label}</span>
        ))}
      </div>
    </div>
  );
}

export const JOB_TEXT: Record<JobStatus, string> = {
  running: "text-amber-600 dark:text-amber-400",
  succeeded: "text-emerald-600 dark:text-emerald-400",
  failed: "text-red-600 dark:text-red-400",
  error: "text-red-600 dark:text-red-400",
  cancelled: "text-zinc-500",
};

export const JOB_BAR: Record<JobStatus, string> = {
  running: "bg-amber-500",
  succeeded: "bg-emerald-500",
  failed: "bg-red-500",
  error: "bg-red-500",
  cancelled: "bg-zinc-400",
};
