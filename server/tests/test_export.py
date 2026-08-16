"""Een compleet vertaald of ingekleurd hoofdstuk als eigen editie (M9)."""

from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from bookpal.db import session_scope
from bookpal.library import export
from bookpal.models import Book, Edition, Series
from bookpal.translate import sidecar
from bookpal.translate.modes import TranslateMode
from bookpal.translate.service import colour_variant


def _storm_boek(client: TestClient) -> int:
    """Deel 1 van Storm: 5 pagina's, uit Dupuis dus Europa."""
    with session_scope() as s:
        reeks = s.scalar(select(Series).where(Series.title == "Storm"))
        boek = s.scalar(select(Book).where(Book.series_id == reeks.id, Book.number == "1"))
        return boek.id


def _plaatje() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 60), (200, 40, 40)).save(buffer, format="WEBP")
    return buffer.getvalue()


def _zet_hertekend(session, boek: Book, pagina: int, *, taal: str = "nl") -> None:
    series = session.get(Series, boek.series_id)
    pad = sidecar.image_path(series, boek, pagina, taal, TranslateMode.IMAGE_FAST)
    sidecar.write_bytes(pad, _plaatje())


def _zet_kleur(session, boek: Book, pagina: int, *, ook_vertaald: str | None = None) -> None:
    series = session.get(Series, boek.series_id)
    variant = colour_variant(ook_vertaald)
    pad = sidecar.variant_path(series, boek, pagina, variant)
    sidecar.write_bytes(pad, _plaatje())


class TestCompleetheid:
    def test_an_untranslated_chapter_is_not_complete(self, scanned: TestClient):
        boek_id = _storm_boek(scanned)
        with session_scope() as s:
            boek = s.get(Book, boek_id)
            assert not export.compleet(s, boek, export.ExportKind.VERTAALD)

    def test_one_missing_page_is_enough_to_block_it(self, scanned: TestClient):
        boek_id = _storm_boek(scanned)
        with session_scope() as s:
            boek = s.get(Book, boek_id)
            for pagina in range(boek.page_count - 1):  # opzettelijk de laatste overslaan
                _zet_hertekend(s, boek, pagina)
            assert not export.compleet(s, boek, export.ExportKind.VERTAALD)

    def test_every_page_present_is_complete(self, scanned: TestClient):
        boek_id = _storm_boek(scanned)
        with session_scope() as s:
            boek = s.get(Book, boek_id)
            for pagina in range(boek.page_count):
                _zet_hertekend(s, boek, pagina)
            assert export.compleet(s, boek, export.ExportKind.VERTAALD)


class TestExporteren:
    def test_nothing_is_written_for_an_incomplete_chapter(self, scanned: TestClient):
        boek_id = _storm_boek(scanned)
        with session_scope() as s:
            boek = s.get(Book, boek_id)
            resultaat = export.exporteer(s, boek, export.ExportKind.VERTAALD)
            assert resultaat is None

    def test_a_complete_translation_becomes_a_readable_file(self, scanned: TestClient):
        boek_id = _storm_boek(scanned)
        with session_scope() as s:
            boek = s.get(Book, boek_id)
            for pagina in range(boek.page_count):
                _zet_hertekend(s, boek, pagina)

            editie_boek = export.exporteer(s, boek, export.ExportKind.VERTAALD)
            assert editie_boek is not None
            assert editie_boek.file is not None
            pad = Path(editie_boek.file.path)
            assert pad.is_file()
            assert pad.name.endswith(".nl.cbz")
            assert pad.parent == sidecar.series_home(s.get(Series, boek.series_id), boek)

            with zipfile.ZipFile(pad) as archief:
                namen = archief.namelist()
                assert len([n for n in namen if n != "ComicInfo.xml"]) == boek.page_count
                assert "ComicInfo.xml" in namen
                info = archief.read("ComicInfo.xml").decode("utf-8")
                assert "<Series>Storm</Series>" in info
                assert "<Number>1</Number>" in info

    def test_the_edition_ranks_behind_your_own_files(self, scanned: TestClient):
        """Nieuw komt achteraan: het mag niet ongevraagd je voorkeur worden."""
        boek_id = _storm_boek(scanned)
        with session_scope() as s:
            boek = s.get(Book, boek_id)
            for pagina in range(boek.page_count):
                _zet_hertekend(s, boek, pagina)
            eigen_rank = s.get(Edition, boek.edition_id).rank

            editie_boek = export.exporteer(s, boek, export.ExportKind.VERTAALD)
            nieuwe_editie = s.get(Edition, editie_boek.edition_id)
            assert nieuwe_editie.rank > eigen_rank
            assert nieuwe_editie.id != boek.edition_id

    def test_colour_only_gets_the_col_suffix(self, scanned: TestClient):
        boek_id = _storm_boek(scanned)
        with session_scope() as s:
            boek = s.get(Book, boek_id)
            for pagina in range(boek.page_count):
                _zet_kleur(s, boek, pagina)

            editie_boek = export.exporteer(s, boek, export.ExportKind.KLEUR)
            assert editie_boek is not None
            assert editie_boek.file is not None
            assert Path(editie_boek.file.path).name.endswith(".col.cbz")

    def test_colour_with_translation_gets_col_and_language(self, scanned: TestClient):
        boek_id = _storm_boek(scanned)
        with session_scope() as s:
            boek = s.get(Book, boek_id)
            for pagina in range(boek.page_count):
                _zet_kleur(s, boek, pagina, ook_vertaald="nl")

            editie_boek = export.exporteer(s, boek, export.ExportKind.KLEUR_VERTAALD)
            assert editie_boek is not None
            assert editie_boek.file is not None
            assert Path(editie_boek.file.path).name.endswith(".col.nl.cbz")

    def test_colour_only_and_combined_are_independent_editions(self, scanned: TestClient):
        """Kleur-zonder-vertaling en kleur-mét-vertaling zijn allebei een
        legitieme, andere leeservaring — geen van beide vervangt de ander."""
        boek_id = _storm_boek(scanned)
        with session_scope() as s:
            boek = s.get(Book, boek_id)
            for pagina in range(boek.page_count):
                _zet_kleur(s, boek, pagina, ook_vertaald="nl")
                _zet_kleur(s, boek, pagina)  # de losse kleur-variant blijft ook liggen

            kleur = export.exporteer(s, boek, export.ExportKind.KLEUR)
            kleur_nl = export.exporteer(s, boek, export.ExportKind.KLEUR_VERTAALD)
            assert kleur is not None and kleur_nl is not None
            assert kleur.edition_id != kleur_nl.edition_id
            assert kleur.id != kleur_nl.id

    def test_exporting_twice_without_changes_reuses_the_same_book(self, scanned: TestClient):
        boek_id = _storm_boek(scanned)
        with session_scope() as s:
            boek = s.get(Book, boek_id)
            for pagina in range(boek.page_count):
                _zet_hertekend(s, boek, pagina)

            eerste = export.exporteer(s, boek, export.ExportKind.VERTAALD)
            eerste_mtime = eerste.file.mtime
            tweede = export.exporteer(s, boek, export.ExportKind.VERTAALD)

            assert tweede.id == eerste.id
            assert tweede.file.mtime == eerste_mtime

            # Geen tweede editie of tweede rij is ontstaan.
            edities = s.scalars(select(Edition).where(Edition.series_id == boek.series_id)).all()
            assert sum(1 for e in edities if e.export_key is not None) == 1

    def test_a_changed_source_page_triggers_a_rebuild(self, scanned: TestClient):
        boek_id = _storm_boek(scanned)
        with session_scope() as s:
            boek = s.get(Book, boek_id)
            for pagina in range(boek.page_count):
                _zet_hertekend(s, boek, pagina)
            eerste = export.exporteer(s, boek, export.ExportKind.VERTAALD)
            eerste_mtime = eerste.file.mtime
            eerste_id = eerste.id

            # Eén bronpagina opnieuw wegschrijven, met een latere mtime.
            series = s.get(Series, boek.series_id)
            pad = sidecar.image_path(series, boek, 0, "nl", TranslateMode.IMAGE_FAST)
            os.utime(pad, (eerste_mtime + 10, eerste_mtime + 10))

            tweede = export.exporteer(s, boek, export.ExportKind.VERTAALD)
            assert tweede.id == eerste_id  # zelfde boek, alleen het bestand vernieuwd
            assert tweede.file.mtime > eerste_mtime

    def test_pro_beats_fast_when_both_exist_for_a_page(self, scanned: TestClient):
        """Is een pagina met het dure model overgedaan, dan telt die."""
        boek_id = _storm_boek(scanned)
        with session_scope() as s:
            boek = s.get(Book, boek_id)
            series = s.get(Series, boek.series_id)
            for pagina in range(boek.page_count):
                _zet_hertekend(s, boek, pagina)
            pro_pad = sidecar.image_path(series, boek, 0, "nl", TranslateMode.IMAGE_PRO)
            pro_bytes = b"x" * 999
            sidecar.write_bytes(pro_pad, pro_bytes)

            editie_boek = export.exporteer(s, boek, export.ExportKind.VERTAALD)
            with zipfile.ZipFile(Path(editie_boek.file.path)) as archief:
                eerste_pagina = archief.read(
                    sorted(n for n in archief.namelist() if n != "ComicInfo.xml")[0]
                )
            assert eerste_pagina == pro_bytes


class TestProbeerAlle:
    def test_only_what_is_complete_gets_exported(self, scanned: TestClient):
        boek_id = _storm_boek(scanned)
        with session_scope() as s:
            boek = s.get(Book, boek_id)
            for pagina in range(boek.page_count):
                _zet_hertekend(s, boek, pagina)  # alleen vertaling compleet

            gemaakt = export.probeer_alle(s, boek)
            assert len(gemaakt) == 1
            assert Path(gemaakt[0].file.path).name.endswith(".nl.cbz")

    def test_nothing_ready_yet_makes_nothing(self, scanned: TestClient):
        boek_id = _storm_boek(scanned)
        with session_scope() as s:
            boek = s.get(Book, boek_id)
            assert export.probeer_alle(s, boek) == []
