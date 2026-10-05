"use client";

import { useState } from "react";
import { Shell, Stat, StatGrid } from "@/components/ui";
import { useApi, type Status } from "@/lib/api";

export default function Profile() {
  const st = useApi<Status>("status");
  const [name, setName] = useState<string | null>(null);
  const s = st.data;

  if (!s) {
    return (
      <Shell error={st.error}>
        <p className="text-sm text-zinc-500">Contacting agent…</p>
      </Shell>
    );
  }

  const draft = name ?? s.username;
  const save = async () => {
    await st.act("profile", { username: draft });
    setName(null);
  };

  return (
    <Shell error={st.error}>
      <h1 className="mb-1 text-2xl font-semibold tracking-tight">Profile</h1>
      <p className="mb-8 text-sm text-zinc-500">Consumers see this before they send you jobs.</p>

      <div className="mb-10 flex flex-wrap items-end gap-3">
        <div className="flex-1 space-y-1">
          <label htmlFor="username" className="text-sm font-medium">Username</label>
          <input
            id="username"
            value={draft}
            maxLength={32}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-md border border-zinc-300 bg-transparent px-3 py-2 text-sm dark:border-zinc-700"
          />
        </div>
        <button
          onClick={save}
          disabled={!draft.trim() || draft === s.username}
          className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-40"
        >
          Save username
        </button>
      </div>

      <StatGrid>
        <Stat
          label="Completion rate"
          value={s.completion_rate === null ? "—" : `${Math.round(s.completion_rate * 100)}%`}
          hint={s.completion_rate === null ? "No finished jobs yet" : "Completed of finished jobs"}
        />
        <Stat label="Rating" value={s.rating === null ? "—" : `★ ${s.rating.toFixed(1)}`} hint={s.rating === null ? "No ratings yet" : "From consumers"} />
        <Stat label="Jobs completed" value={String(s.completed)} />
        <Stat label="Jobs failed" value={String(s.failed)} />
      </StatGrid>

      <p className="mt-6 text-sm text-zinc-500">
        Offering {s.cpu_cores} cores, {(s.memory_mb / 1024).toFixed(1)} GB RAM
        {s.gpu && s.gpu_name ? `, ${s.gpu_name}` : ", no GPU"}.
      </p>
    </Shell>
  );
}
