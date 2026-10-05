import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const AGENT_URL = process.env.AGENT_URL ?? "http://127.0.0.1:8792";
const READS = new Set(["status", "jobs"]);
const ACTIONS = new Set(["online", "offline", "config", "profile"]);

async function forward(path: string, init?: RequestInit) {
  try {
    const res = await fetch(`${AGENT_URL}${path}`, { ...init, cache: "no-store" });
    return NextResponse.json(await res.json(), { status: res.status });
  } catch {
    return NextResponse.json(
      { error: `Agent not reachable at ${AGENT_URL}. Is it running?` },
      { status: 502 },
    );
  }
}

export function GET(req: NextRequest) {
  const p = req.nextUrl.searchParams.get("p") ?? "status";
  if (!READS.has(p)) return NextResponse.json({ error: "Unknown resource" }, { status: 400 });
  return forward(`/${p}`);
}

export async function POST(req: NextRequest) {
  const { action, ...body } = await req.json();
  if (!ACTIONS.has(action)) {
    return NextResponse.json({ error: "Unknown action" }, { status: 400 });
  }
  return forward(`/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
