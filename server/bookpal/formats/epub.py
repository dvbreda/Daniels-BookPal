"""EPUB — metadata, omslag en spine.

Het lézen van een epub gebeurt in de client (foliate-js in web en iOS, crengine
op de Kobo), niet hier: een epub is herschikbare tekst en heeft dus geen vaste
pagina's die de server zou kunnen renderen. Wat de server wél moet weten is de
metadata, de omslag en hoeveel spine-onderdelen er zijn, zodat voortgang als
percentage betekenis heeft.
"""

from __future__ import annotations

import posixpath
import zipfile
from pathlib import Path

from lxml import etree

from bookpal.formats.base import (
    MEDIA_TYPES,
    BookFile,
    BookMetadata,
    RawPage,
    TocEntry,
    UnsupportedOperation,
)
from bookpal.models import BookKind

NS = {
    "container": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
    "xhtml": "http://www.w3.org/1999/xhtml",
}


class EpubBook(BookFile):
    kind = BookKind.EPUB

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self._zip = zipfile.ZipFile(path)
        self._opf_path = self._find_opf()
        self._opf = self._parse_xml(self._opf_path)
        self._base = posixpath.dirname(self._opf_path)
        self._manifest = self._read_manifest()
        self._spine = self._read_spine()

    # -- opbouw ---------------------------------------------------------

    def _parse_xml(self, name: str) -> etree._Element:
        parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
        root = etree.fromstring(self._zip.read(name), parser=parser)
        if root is None:
            raise ValueError(f"kon {name} niet lezen in {self.path.name}")
        return root

    def _find_opf(self) -> str:
        root = self._parse_xml("META-INF/container.xml")
        node = root.find(".//container:rootfile", NS)
        if node is None:
            raise ValueError(f"{self.path.name}: geen rootfile in container.xml")
        full_path = node.get("full-path")
        if not full_path:
            raise ValueError(f"{self.path.name}: rootfile zonder full-path")
        return full_path

    def _resolve(self, href: str) -> str:
        return posixpath.normpath(posixpath.join(self._base, href)) if self._base else href

    def _read_manifest(self) -> dict[str, dict[str, str]]:
        manifest: dict[str, dict[str, str]] = {}
        for item in self._opf.findall(".//opf:manifest/opf:item", NS):
            item_id = item.get("id")
            href = item.get("href")
            if not item_id or not href:
                continue
            manifest[item_id] = {
                "href": self._resolve(href),
                "media_type": item.get("media-type", ""),
                "properties": item.get("properties", ""),
            }
        return manifest

    def _read_spine(self) -> list[str]:
        spine: list[str] = []
        for ref in self._opf.findall(".//opf:spine/opf:itemref", NS):
            idref = ref.get("idref")
            if idref and idref in self._manifest:
                spine.append(idref)
        return spine

    # -- interface ------------------------------------------------------

    def page_count(self) -> int:
        """Aantal spine-onderdelen. Geen pagina's in de fysieke zin, maar wel de
        eenheid waarin voortgang uitgedrukt kan worden."""
        return len(self._spine)

    def get_page(self, index: int, target_width: int | None = None) -> RawPage:
        raise UnsupportedOperation(
            "een epub heeft geen vaste pagina's; de client rendert het bestand zelf"
        )

    def metadata(self) -> BookMetadata:
        meta = BookMetadata()

        def dc(tag: str) -> str | None:
            node = self._opf.find(f".//dc:{tag}", NS)
            if node is None or node.text is None:
                return None
            return node.text.strip() or None

        meta.title = dc("title")
        meta.publisher = dc("publisher")
        meta.language = dc("language")
        meta.summary = dc("description")

        for node in self._opf.findall(".//dc:creator", NS):
            if node.text and node.text.strip():
                meta.authors.append(node.text.strip())
        for node in self._opf.findall(".//dc:subject", NS):
            if node.text and node.text.strip():
                meta.tags.append(node.text.strip())

        # Calibre schrijft serie-informatie weg als los meta-element.
        for node in self._opf.findall(".//opf:meta", NS):
            name = node.get("name")
            content = node.get("content")
            if not name or not content:
                continue
            if name == "calibre:series":
                meta.series = content
            elif name == "calibre:series_index":
                meta.number = content

        if meta.language:
            meta.raw["language"] = meta.language
        meta.authors = list(dict.fromkeys(meta.authors))
        meta.tags = list(dict.fromkeys(meta.tags))
        return meta

    def _cover_href(self) -> str | None:
        # EPUB3: het manifest-item markeert zichzelf.
        for item in self._manifest.values():
            if "cover-image" in item["properties"]:
                return item["href"]
        # EPUB2: een meta-element wijst naar een manifest-id.
        for node in self._opf.findall(".//opf:meta", NS):
            if node.get("name") == "cover":
                referenced = self._manifest.get(node.get("content", ""))
                if referenced and referenced["media_type"].startswith("image/"):
                    return referenced["href"]
        # Laatste redmiddel: een afbeelding die "cover" heet.
        for item_id, item in self._manifest.items():
            if not item["media_type"].startswith("image/"):
                continue
            if "cover" in item_id.lower() or "cover" in item["href"].lower():
                return item["href"]
        return None

    def cover(self) -> RawPage | None:
        href = self._cover_href()
        if href is None:
            return None
        try:
            data = self._zip.read(href)
        except KeyError:
            return None
        suffix = Path(href).suffix.lower()
        return RawPage(data=data, media_type=MEDIA_TYPES.get(suffix, "image/jpeg"))

    def toc(self) -> list[TocEntry]:
        entries: list[TocEntry] = []
        # EPUB3-navigatiedocument.
        for item in self._manifest.values():
            if "nav" not in item["properties"]:
                continue
            try:
                root = self._parse_xml(item["href"])
            except (KeyError, ValueError):
                continue
            for anchor in root.findall(".//xhtml:nav//xhtml:a", NS):
                href = anchor.get("href")
                text = "".join(anchor.itertext()).strip()
                if href and text:
                    entries.append(TocEntry(title=text, target=href))
            if entries:
                return entries
        # EPUB2-NCX.
        for item in self._manifest.values():
            if item["media_type"] != "application/x-dtbncx+xml":
                continue
            try:
                root = self._parse_xml(item["href"])
            except (KeyError, ValueError):
                continue
            for point in root.findall(".//ncx:navPoint", NS):
                label = point.find(".//ncx:text", NS)
                content = point.find("ncx:content", NS)
                if label is not None and label.text and content is not None:
                    entries.append(
                        TocEntry(title=label.text.strip(), target=content.get("src", ""))
                    )
            break
        return entries

    def close(self) -> None:
        self._zip.close()
