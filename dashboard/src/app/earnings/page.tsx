"use client";

import { Bars, Shell } from "@/components/ui";
import { credits, perDay, useApi, type Job, type Status } from "@/lib/api";

export default function Earnings() {
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

  const paid = jobs.filter((j) => j.credits > 0);
  const lines: [string, string, number][] = [
    ["CPU", `${s.cpu_cores} cores`, s.rate.cpu],
    ["RAM", `${(s.memory_mb / 1024).toFixed(1)} GB`, s.rate.ram],
    ["GPU", s.gpu ? (s.gpu_name ?? "Shared") : "Not shared", s.rate.gpu],
  ];

  return (
    <Shell error={st.error ?? jb.error}>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Earnings</h1>

      <div className="mb-10">
        <div className="text-sm text-zinc-500">Wallet</div>
        <div className="text-5xl font-semibold tabular-nums tracking-tight">
          {s.balance.toFixed(2)} <span className="text-2xl text-zinc-500">credits</span>
        </div>
      </div>

      <section className="mb-10">
        <h2 className="mb-1 text-lg font-medium">What your machine earns</h2>
        <p className="mb-3 text-sm text-zinc-500">Based on the resources you share, while a job is running.</p>
        <table className="w-full text-sm">
          <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
            {lines.map(([name, detail, rate]) => (
              <tr key={name}>
                <td className="py-2 font-medium">{name}</td>
                <td className="text-zinc-500">{detail}</td>
                <td className="text-right tabular-nums">{rate.toFixed(2)} cr/hour</td>
              </tr>
            ))}
            <tr className="font-medium">
              <td className="py-2" colSpan={2}>Total</td>
              <td className="text-right tabular-nums">{s.rate.total.toFixed(2)} cr/hour</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section className="mb-10">
        <h2 className="mb-2 text-lg font-medium">Credits earned, last 7 days</h2>
        <Bars data={perDay(jobs, (j) => j.credits)} unit=" cr" />
      </section>

      <section>
        <h2 className="mb-2 text-lg font-medium">Transactions</h2>
        {paid.length === 0 ? (
          <p className="text-sm text-zinc-500">Credits appear here when you complete a job.</p>
        ) : (
          <ul className="divide-y divide-zinc-200 text-sm dark:divide-zinc-800">
            {paid.slice(0, 15).map((j) => (
              <li key={j.id} className="flex justify-between gap-4 py-2">
                <span className="truncate">{j.name}</span>
                <span className="tabular-nums text-emerald-600 dark:text-emerald-400">+{credits(j.credits)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </Shell>
  );
}
