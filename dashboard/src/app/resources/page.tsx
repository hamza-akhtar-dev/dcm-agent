"use client";

import { useState } from "react";
import { Shell, StateBadge, Switch } from "@/components/ui";
import { useApi, type Status } from "@/lib/api";

export default function Resources() {
  const st = useApi<Status>("status");
  const [cores, setCores] = useState<number | null>(null);
  const [mem, setMem] = useState<number | null>(null);
  const [gpu, setGpu] = useState<boolean | null>(null);
  const s = st.data;

  if (!s) {
    return (
      <Shell error={st.error}>
        <p className="text-sm text-zinc-500">Contacting agent…</p>
      </Shell>
    );
  }

  const c = cores ?? s.cpu_cores;
  const m = mem ?? s.memory_mb;
  const g = gpu ?? s.gpu;
  const dirty = c !== s.cpu_cores || m !== s.memory_mb || g !== s.gpu;

  const save = async () => {
    await st.act("config", { cpu_cores: c, memory_mb: m, gpu: g });
    setCores(null);
    setMem(null);
    setGpu(null);
  };

  return (
    <Shell error={st.error}>
      <div className="mb-8 flex items-baseline justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Resources</h1>
        <StateBadge state={s.state} />
      </div>

      <div className="space-y-8">
        <div className="space-y-2">
          <div className="flex items-baseline justify-between">
            <label htmlFor="cores" className="text-sm font-medium">CPU cores</label>
            <span className="text-sm tabular-nums">{c} of {s.max_cpu_cores}</span>
          </div>
          <input id="cores" type="range" min={1} max={s.max_cpu_cores} step={1} value={c}
            onChange={(e) => setCores(Number(e.target.value))} className="w-full accent-emerald-500" />
        </div>

        <div className="space-y-2">
          <div className="flex items-baseline justify-between">
            <label htmlFor="ram" className="text-sm font-medium">RAM</label>
            <span className="text-sm tabular-nums">
              {(m / 1024).toFixed(1)} of {(s.max_memory_mb / 1024).toFixed(1)} GB
            </span>
          </div>
          <input id="ram" type="range" min={512} max={Math.floor(s.max_memory_mb / 256) * 256} step={256} value={m}
            onChange={(e) => setMem(Number(e.target.value))} className="w-full accent-emerald-500" />
        </div>

        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-sm font-medium">GPU</div>
            <p className="text-sm text-zinc-500">{s.gpu_available ? s.gpu_name : "No GPU detected on this machine"}</p>
          </div>
          <Switch on={g} disabled={!s.gpu_available} label="Share GPU" onChange={setGpu} />
        </div>

        <div className="flex items-center gap-3">
          <button onClick={save} disabled={!dirty}
            className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-40">
            Save changes
          </button>
          <p className="text-sm text-zinc-500">
            {s.busy ? "Applies from the next job." : "Applies to new jobs."} Current rate: {s.rate.total} cr per hour.
          </p>
        </div>
      </div>
    </Shell>
  );
}
