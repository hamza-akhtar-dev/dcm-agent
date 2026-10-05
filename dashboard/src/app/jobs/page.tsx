"use client";

import { Bars, JOB_BAR, JOB_TEXT, Shell, Stat, StatGrid } from "@/components/ui";
import { credits, duration, perDay, useApi, type Job } from "@/lib/api";

export default function Jobs() {
  const jb = useApi<{ jobs: Job[]; now: number }>("jobs");

  if (!jb.data) {
    return (
      <Shell error={jb.error}>
        <p className="text-sm text-zinc-500">Contacting agent…</p>
      </Shell>
    );
  }

  const { jobs, now } = jb.data;
  const count = (f: (j: Job) => boolean) => String(jobs.filter(f).length);
  const recent = jobs.slice(0, 10).reverse();
  const t0 = recent.length ? Math.min(...recent.map((j) => j.started_at)) : now;
  const span = Math.max(now - t0, 1);
  const time = (t: number) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <Shell error={jb.error}>
      <h1 className="mb-8 text-2xl font-semibold tracking-tight">Jobs</h1>

      <StatGrid>
        <Stat label="Running" value={count((j) => j.status === "running")} />
        <Stat label="Succeeded" value={count((j) => j.status === "succeeded")} />
        <Stat label="Failed" value={count((j) => j.status === "failed" || j.status === "error")} />
        <Stat label="Cancelled" value={count((j) => j.status === "cancelled")} />
      </StatGrid>

      <section className="mt-10">
        <h2 className="mb-2 text-lg font-medium">Jobs per day</h2>
        <Bars data={perDay(jobs, () => 1)} />
      </section>

      <section className="mt-10">
        <h2 className="mb-3 text-lg font-medium">Timeline</h2>
        {recent.length === 0 ? (
          <p className="text-sm text-zinc-500">No jobs yet. Stay online and the coordinator will send some.</p>
        ) : (
          <>
            <ul className="space-y-2">
              {recent.map((j) => {
                const end = j.ended_at ?? now;
                return (
                  <li key={j.id} className="grid grid-cols-[8rem_1fr] items-center gap-3 text-xs">
                    <span className="truncate text-zinc-500">{j.name}</span>
                    <div className="relative h-4 rounded bg-zinc-100 dark:bg-zinc-900">
                      <div
                        title={`${j.status}, ${duration(end - j.started_at)}`}
                        className={`absolute h-full rounded ${JOB_BAR[j.status]} ${j.status === "running" ? "animate-pulse" : ""}`}
                        style={{
                          left: `${((j.started_at - t0) / span) * 100}%`,
                          width: `${Math.max(((end - j.started_at) / span) * 100, 1)}%`,
                        }}
                      />
                    </div>
                  </li>
                );
              })}
            </ul>
            <div className="mt-1 flex justify-between pl-[8.75rem] text-xs text-zinc-500">
              <span>{time(t0)}</span>
              <span>now</span>
            </div>
          </>
        )}
      </section>

      {jobs.length > 0 && (
        <section className="mt-10 overflow-x-auto">
          <h2 className="mb-2 text-lg font-medium">History</h2>
          <table className="w-full text-left text-sm">
            <thead className="text-zinc-500">
              <tr>
                <th className="py-2 font-normal">Job</th>
                <th className="font-normal">Status</th>
                <th className="font-normal">Started</th>
                <th className="font-normal">Duration</th>
                <th className="text-right font-normal">Credits</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
              {jobs.map((j) => (
                <tr key={j.id}>
                  <td className="py-2 pr-4">{j.name}</td>
                  <td className={JOB_TEXT[j.status]}>{j.status}</td>
                  <td>{time(j.started_at)}</td>
                  <td className="tabular-nums">{duration((j.ended_at ?? now) - j.started_at)}</td>
                  <td className="text-right tabular-nums">{credits(j.credits)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </Shell>
  );
}
