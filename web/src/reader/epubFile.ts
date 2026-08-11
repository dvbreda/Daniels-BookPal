/**
 * foliate-js herkent het formaat aan naam én mediatype van het bestand:
 * `isCBZ({ name, type })` leest `name.endsWith('.cbz')`. Een `Blob` uit
 * `fetch()` heeft geen `name`, dus daar loopt het stuk voordat het bij de
 * epub-tak is. Vandaar deze wikkel — apart gezet zodat de aanname te testen is
 * zonder een echte lezer op te tuigen.
 */

export const EPUB_MEDIA_TYPE = "application/epub+zip";

export function asEpubFile(blob: Blob, bookId: number): File {
  return new File([blob], `${bookId}.epub`, { type: EPUB_MEDIA_TYPE });
}
