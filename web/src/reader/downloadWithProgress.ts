/**
 * Haalt een bestand op met voortgang, in plaats van een blinde `response.blob()`.
 *
 * Waarom dit bestaat: sommige epubs zijn tientallen tot honderden MB (een
 * geïllustreerd tuinboek met full-page foto's bijvoorbeeld). Zonder feedback
 * ziet dat er op een trage verbinding niet uit als "bezig", maar als "kapot"
 * — een spinner die niets zegt is niet te onderscheiden van een hang. Een
 * percentage lost dat op zonder dat het downloaden zelf sneller wordt.
 */

export interface DownloadProgress {
  loaded: number;
  /** `null` als de server geen Content-Length meegeeft. */
  total: number | null;
}

export async function downloadWithProgress(
  url: string,
  onProgress: (progress: DownloadProgress) => void,
): Promise<Blob> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`kon het bestand niet ophalen (${response.status})`);

  const totalHeader = response.headers.get("content-length");
  const total = totalHeader ? Number(totalHeader) : null;

  // Streaming is niet overal beschikbaar (bv. oudere WebViews); dan gewoon
  // zonder tussentijdse voortgang.
  if (!response.body) {
    const blob = await response.blob();
    onProgress({ loaded: blob.size, total: total ?? blob.size });
    return blob;
  }

  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let loaded = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    loaded += value.byteLength;
    onProgress({ loaded, total });
  }

  return new Blob(chunks as BlobPart[], {
    type: response.headers.get("content-type") ?? undefined,
  });
}
