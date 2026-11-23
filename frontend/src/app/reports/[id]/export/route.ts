import { BACKEND_URL } from "@/lib/api";

/** Proxies report downloads from the backend (which is not exposed to the browser). */
export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) return new Response("Invalid report id", { status: 400 });
  const format = new URL(req.url).searchParams.get("format") === "csv" ? "csv" : "md";
  const res = await fetch(`${BACKEND_URL}/api/reports/${id}/export?format=${format}`, { cache: "no-store" });
  if (!res.ok) return new Response("Report not available", { status: res.status });
  return new Response(await res.text(), {
    headers: {
      "Content-Type": res.headers.get("content-type") ?? "text/plain",
      "Content-Disposition": res.headers.get("content-disposition") ?? "attachment",
    },
  });
}
