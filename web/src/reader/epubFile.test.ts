import { describe, expect, it } from "vitest";

import { EPUB_MEDIA_TYPE, asEpubFile } from "./epubFile";

/** Precies de controles die foliate's makeBook doet, overgenomen uit view.js. */
const isCBZ = ({ name, type }: File) =>
  type === "application/vnd.comicbook+zip" || name.endsWith(".cbz");
const isFBZ = ({ name, type }: File) =>
  type === "application/x-zip-compressed-fb2" ||
  name.endsWith(".fb2.zip") ||
  name.endsWith(".fbz");

describe("asEpubFile", () => {
  it("geeft het bestand een naam, want foliate leest die uit", () => {
    // Een kale Blob liet foliate struikelen op name.endsWith(...)
    const file = asEpubFile(new Blob(["PK"]), 42);
    expect(file.name).toBe("42.epub");
    expect(file.type).toBe(EPUB_MEDIA_TYPE);
  });

  it("wordt door foliate niet voor een cbz of fb2 aangezien", () => {
    const file = asEpubFile(new Blob(["PK"]), 1);
    expect(isCBZ(file)).toBe(false);
    expect(isFBZ(file)).toBe(false);
  });

  it("overleeft foliate's controles zonder te klappen", () => {
    // Dit was de eigenlijke fout: op een Blob is `name` undefined en gooit
    // endsWith een TypeError, nog vóór de epub-tak bereikt wordt.
    const file = asEpubFile(new Blob(["PK"]), 7);
    expect(() => isCBZ(file)).not.toThrow();
  });

  it("houdt de inhoud intact", () => {
    // jsdom's File kent geen .text(), dus via de grootte.
    const file = asEpubFile(new Blob(["hallo"]), 3);
    expect(file.size).toBe(5);
  });
});
