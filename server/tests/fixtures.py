"""Genereert kleine testbestanden.

Bewust gegenereerd in plaats van meegeleverd: er hoort geen stripmateriaal in de
repo, en gegenereerde bestanden laten zich precies afstemmen op wat een test wil
bewijzen (paginavolgorde, ontbrekende metadata, misbenoemde extensies).
"""

from __future__ import annotations

import os
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

import libarchive
import pymupdf
from PIL import Image

# Kleuren zodat pagina's visueel uit elkaar te houden zijn in een debugsessie.
_COLORS = [(220, 60, 60), (60, 160, 220), (250, 210, 80), (120, 200, 120), (180, 120, 220)]


def page_png(index: int, size: tuple[int, int] = (400, 600)) -> bytes:
    image = Image.new("RGB", size, _COLORS[index % len(_COLORS)])
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def comicinfo_xml(
    series: str = "Testreeks",
    number: str = "1",
    volume: str | None = None,
    publisher: str | None = None,
    language: str | None = None,
    manga: str | None = None,
) -> bytes:
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
        f"<Series>{series}</Series>",
        f"<Number>{number}</Number>",
        "<Writer>Iemand Anders</Writer>",
        "<Genre>Avontuur, Humor</Genre>",
    ]
    if volume:
        parts.append(f"<Volume>{volume}</Volume>")
    if publisher:
        parts.append(f"<Publisher>{publisher}</Publisher>")
    if language:
        parts.append(f"<LanguageISO>{language}</LanguageISO>")
    if manga:
        parts.append(f"<Manga>{manga}</Manga>")
    parts.append("</ComicInfo>")
    return "".join(parts).encode("utf-8")


def make_cbz(
    path: Path,
    pages: int = 5,
    comicinfo: bytes | None = None,
    *,
    shuffled_names: bool = False,
) -> Path:
    """Schrijf een cbz.

    ``shuffled_names`` zet de bestandsnamen in een volgorde die alleen met
    natuurlijk sorteren goedkomt (1, 2, 10 in plaats van 1, 10, 2).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
        for index in range(pages):
            name = f"page{index + 1}.png" if shuffled_names else f"{index + 1:03d}.png"
            archive.writestr(name, page_png(index))
        # Ruis die de adapter moet negeren.
        archive.writestr("__MACOSX/._001.png", b"resource fork")
        archive.writestr("thumbs.db", b"nope")
        if comicinfo is not None:
            archive.writestr("ComicInfo.xml", comicinfo)
    return path


def make_cb7(path: Path, pages: int = 4, comicinfo: bytes | None = None) -> Path:
    """Schrijf een 7z-stripbestand.

    Dit deelt de volledige libarchive-leescode met cbr; RAR zelf kunnen we niet
    genereren omdat er geen vrije compressor voor bestaat.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.parent / f".staging-{path.stem}"
    staging.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    for index in range(pages):
        name = f"{index + 1:03d}.png"
        (staging / name).write_bytes(page_png(index))
        names.append(name)
    if comicinfo is not None:
        (staging / "ComicInfo.xml").write_bytes(comicinfo)
        names.append("ComicInfo.xml")

    cwd = Path.cwd()
    try:
        os.chdir(staging)
        with libarchive.file_writer(str(path), "7zip") as writer:
            writer.add_files(*names)
    finally:
        os.chdir(cwd)
    for name in names:
        (staging / name).unlink()
    staging.rmdir()
    return path


def make_epub(
    path: Path,
    title: str = "Een Testboek",
    author: str = "A. Schrijver",
    language: str = "nl",
    chapters: int = 3,
    with_cover: bool = True,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = []
    spine = []
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        # De mimetype moet als eerste en ongecomprimeerd in het archief staan.
        archive.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", zipfile.ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?>'
            '<container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        for index in range(chapters):
            name = f"chap{index + 1}.xhtml"
            archive.writestr(
                f"OEBPS/{name}",
                f'<?xml version="1.0" encoding="utf-8"?>'
                f'<html xmlns="http://www.w3.org/1999/xhtml"><head>'
                f"<title>Hoofdstuk {index + 1}</title></head>"
                f"<body><h1>Hoofdstuk {index + 1}</h1><p>Tekst.</p></body></html>",
            )
            manifest.append(
                f'<item id="c{index}" href="{name}" media-type="application/xhtml+xml"/>'
            )
            spine.append(f'<itemref idref="c{index}"/>')

        cover_meta = ""
        if with_cover:
            archive.writestr("OEBPS/cover.png", page_png(0, size=(200, 300)))
            manifest.append(
                '<item id="cover-img" href="cover.png" media-type="image/png" '
                'properties="cover-image"/>'
            )
            cover_meta = '<meta name="cover" content="cover-img"/>'

        archive.writestr(
            "OEBPS/nav.xhtml",
            '<?xml version="1.0" encoding="utf-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops"><body>'
            '<nav epub:type="toc"><ol>'
            + "".join(
                f'<li><a href="chap{i + 1}.xhtml">Hoofdstuk {i + 1}</a></li>'
                for i in range(chapters)
            )
            + "</ol></nav></body></html>",
        )
        manifest.append(
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        )

        archive.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0" encoding="utf-8"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
            'unique-identifier="bookid">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f"<dc:title>{title}</dc:title>"
            f"<dc:creator>{author}</dc:creator>"
            f"<dc:language>{language}</dc:language>"
            "<dc:publisher>Testuitgeverij</dc:publisher>"
            '<dc:identifier id="bookid">urn:uuid:test</dc:identifier>'
            f"{cover_meta}"
            "</metadata>"
            f"<manifest>{''.join(manifest)}</manifest>"
            f"<spine>{''.join(spine)}</spine>"
            "</package>",
        )
    return path


def make_pdf(path: Path, pages: int = 3, title: str = "Een Testdocument") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for index in range(pages):
        page = doc.new_page(width=400, height=600)
        page.insert_text((60, 100), f"Pagina {index + 1}", fontsize=28)
    doc.set_metadata({"title": title, "author": "P. Documentmaker", "keywords": "test, pdf"})
    doc.save(str(path))
    doc.close()
    return path


@contextmanager
def sample_library(root: Path) -> Iterator[Path]:
    """Een complete testbibliotheek met de mappenstructuur die de scanner verwacht."""
    strips = root / "strips" / "De Testreeks"
    manga = root / "manga" / "Tesuto"
    boeken = root / "boeken"

    make_cbz(
        strips / "De Testreeks 01.cbz",
        pages=5,
        comicinfo=comicinfo_xml(series="De Testreeks", number="1", publisher="Dupuis"),
    )
    make_cbz(
        strips / "De Testreeks 02.cbz",
        pages=4,
        comicinfo=comicinfo_xml(series="De Testreeks", number="2", publisher="Dupuis"),
    )
    make_cb7(
        manga / "Tesuto v01.cb7",
        pages=3,
        comicinfo=comicinfo_xml(series="Tesuto", number="1", manga="YesAndRightToLeft"),
    )
    make_epub(boeken / "Een Testboek.epub")
    make_pdf(boeken / "Een Testdocument.pdf")
    yield root
