"use client";

import { useCallback, useEffect, useState } from "react";

export type JobStatus = "running" | "succeeded" | "failed" | "cancelled" | "error";

export type Job = {
  id: string;
  name: string;
  status: JobStatus;
  started_at: number;
  ended_at: number | null;
  rate: number;
  credits: number;
};

export type Status = {
  state: "online" | "connecting" | "draining" | "offline";
  busy: boolean;
  name: string;
  runtime: string;
  coordinator: string;
  cpu_cores: number;
  max_cpu_cores: number;
  memory_mb: number;
  max_memory_mb: number;
  gpu: boolean;
  gpu_available: boolean;
  gpu_name: string | null;
  rate: { cpu: number; ram: number; gpu: number; total: number };
  username: string;
  completed: number;
  failed: number;
  completion_rate: number | null;
  rating: number | null;
  balance: number;
};

export function useApi<T>(path: "status" | "jobs") {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`/api/agent?p=${path}`, { cache: "no-store" });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error ?? "Request failed");
      setData(body);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [path]);

  useEffect(() => {
    load();
    const timer = setInterval(load, 2000);
    return () => clearInterval(timer);
  }, [load]);

  const act = useCallback(
    async (action: string, body: object = {}) => {
      try {
        const res = await fetch("/api/agent", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action, ...body }),
        });
        const reply = await res.json();
        if (!res.ok) throw new Error(reply.error ?? "Request failed");
        await load();
      } catch (e) {
        setError((e as Error).message);
      }
    },
    [load],
  );

  return { data, error, act };
}

export const credits = (n: number) => `${n.toFixed(2)} cr`;

export const duration = (s: number) =>
  s < 60
    ? `${Math.round(s)}s`
    : s < 3600
      ? `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`
      : `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;

/** Sum `value(job)` into one bucket per day for the last `days` days. */
export function perDay(jobs: Job[], value: (j: Job) => number, days = 7) {
  const buckets = Array.from({ length: days }, (_, i) => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() - (days - 1 - i));
    return { label: d.toLocaleDateString(undefined, { weekday: "short" }), start: d.getTime() / 1000, value: 0 };
  });
  for (const job of jobs) {
    const i = buckets.findLastIndex((b) => job.started_at >= b.start);
    if (i >= 0) buckets[i].value += value(job);
  }
  return buckets;
}
