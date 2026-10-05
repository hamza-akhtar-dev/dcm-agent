"use client";

import { Bars, JOB_TEXT, Shell, Stat, StatGrid, StateBadge, Switch } from "@/components/ui";
import { credits, perDay, useApi, type Job, type Status } from "@/lib/api";

export default function Overview() {
  const st = useApi<Status>("status");
  const jb = useApi<{ jobs: Job[] }>("jobs");
  const s = st.data;
  const jobs = jb.data?.jobs ?? [];

  if (!s) {
    return (
      <Shell error={st.error}>
        <p className="text-sm text-zinc-500">Contacting agent…</p>
      </Shell>
    );
  }

  const on = s.state === "online" || s.state === "connecting";
  const running = jobs.filter((j) => j.status === "running").length;

  return (
    <Shell error={st.error ?? jb.error}>
      <div className="mb-8 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{s.username}</h1>
          <StateBadge state={s.state} />
        </div>
        <Switch on={on} label="Take jobs" onChange={(n) => st.act(n ? "online" : "offline")} />
      </div>

      <StatGrid>
        <Stat href="/earnings" label="Wallet" value={credits(s.balance)} hint={`${s.rate.total} cr per hour`} />
        <Stat
          href="/profile"
          label="Completion"
          value={s.completion_rate === null ? "—" : `${Math.round(s.completion_rate * 100)}%`}
          hint={`${s.completed} done, ${s.failed} failed`}
        />
        <Stat
          href="/resources"
          label="Sharing"
          value={`${s.cpu_cores} cores`}
          hint={`${(s.memory_mb / 1024).toFixed(1)} GB RAM${s.gpu ? " + GPU" : ""}`}
        />
        <Stat href="/jobs" label="Jobs" value={running ? `${running} running` : "Idle"} hint={`${jobs.length} total`} />
      </StatGrid>

      <section className="mt-10">
        <h2 className="mb-2 text-lg font-medium">Credits earned, last 7 days</h2>
        <Bars data={perDay(jobs, (j) => j.credits)} unit=" cr" />
      </section>

      <section className="mt-10">
        <h2 className="mb-2 text-lg font-medium">Recent jobs</h2>
        {jobs.length === 0 ? (
          <p className="text-sm text-zinc-500">No jobs yet. Stay online and the coordinator will send some.</p>
        ) : (
          <ul className="divide-y divide-zinc-200 text-sm dark:divide-zinc-800">
            {jobs.slice(0, 5).map((j) => (
              <li key={j.id} className="flex justify-between gap-4 py-2">
                <span className="truncate">{j.name}</span>
                <span className={JOB_TEXT[j.status]}>{j.status}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </Shell>
  );
}
