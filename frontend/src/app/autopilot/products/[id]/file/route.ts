import { BACKEND_URL } from "@/lib/api";

/** Proxies the generated PDF download from the backend. */
export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) return new Response("Invalid product id", { status: 400 });
  const res = await fetch(`${BACKEND_URL}/api/autopilot/products/${id}/file`, { cache: "no-store" });
  if (!res.ok) return new Response("File not available", { status: res.status });
  return new Response(await res.arrayBuffer(), {
    headers: {
      "Content-Type": "application/pdf",
      "Content-Disposition": res.headers.get("content-disposition") ?? "attachment",
    },
  });
}
