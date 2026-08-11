import { afterEach, describe, expect, it, vi } from "vitest";

import { downloadWithProgress } from "./downloadWithProgress";

function streamingResponse(chunks: Uint8Array[], contentLength?: number): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
  const headers: Record<string, string> = {};
  if (contentLength !== undefined) headers["content-length"] = String(contentLength);
  return new Response(stream, { status: 200, headers });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("downloadWithProgress", () => {
  it("plakt de chunks aan elkaar tot het volledige bestand", async () => {
    const chunks = [new Uint8Array([1, 2, 3]), new Uint8Array([4, 5])];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamingResponse(chunks, 5)));

    const blob = await downloadWithProgress("/bestand", () => {});
    expect(blob.size).toBe(5);
  });

  it("meldt voortgang na elke chunk, oplopend", async () => {
    const chunks = [new Uint8Array(10), new Uint8Array(15), new Uint8Array(5)];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamingResponse(chunks, 30)));

    const seen: number[] = [];
    await downloadWithProgress("/bestand", (progress) => {
      seen.push(progress.loaded);
      expect(progress.total).toBe(30);
    });
    expect(seen).toEqual([10, 25, 30]);
  });

  it("geeft total=null als de server geen Content-Length stuurt", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamingResponse([new Uint8Array(4)])));

    const totals: (number | null)[] = [];
    await downloadWithProgress("/bestand", (progress) => totals.push(progress.total));
    expect(totals).toEqual([null]);
  });

  it("gooit een leesbare fout bij een niet-ok status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 404, statusText: "Not Found" })),
    );
    await expect(downloadWithProgress("/weg", () => {})).rejects.toThrow("404");
  });

  it("valt terug op response.blob() zonder streaming-ondersteuning", async () => {
    const body = new Blob([new Uint8Array([9, 9, 9])]);
    const response = {
      ok: true,
      body: null,
      headers: new Headers({ "content-length": "3" }),
      blob: () => Promise.resolve(body),
    } as unknown as Response;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));

    const progress: number[] = [];
    const blob = await downloadWithProgress("/bestand", (p) => progress.push(p.loaded));
    expect(blob.size).toBe(3);
    expect(progress).toEqual([3]);
  });
});
