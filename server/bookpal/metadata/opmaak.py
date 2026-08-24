"""Opmaak uit een omschrijving halen.

Samenvattingen komen uit twee hoeken en dragen allebei hun eigen opmaak mee:
MangaDex levert HTML (`<div>`, `<br>`) en epub-metadata vaak `<p><b>`. In een
lezer die platte tekst toont staan die tags er gewoon in.

Bij het uitleveren en niet bij het opslaan. De brontekst blijft dan intact —
mocht er ooit een client komen die de opmaak wél kan tonen — en het werkt
meteen voor alles wat al in de database staat, zonder migratie.
"""

from __future__ import annotations

import html
import re

#: Blokelementen worden een regeleinde: zonder dit plakken alinea's aan elkaar
#: tot één muur tekst.
_REGELEINDE = re.compile(r"</?(?:p|div|br|li|h[1-6]|tr)\b[^>]*>", re.I)
_TAGS = re.compile(r"<[^>]+>")
#: MangaDex zet er soms BBCode tussen, restant van hun eigen editor.
_BBCODE = re.compile(r"\[/?(?:url|b|i|u|spoiler)(?:=[^\]]*)?\]", re.I)
_WITRUIMTE = re.compile(r"[ \t]+")
_LEGE_REGELS = re.compile(r"\n{3,}")


def zonder_opmaak(tekst: str | None) -> str | None:
    """Platte tekst, met de alinea-indeling intact.

    Geeft ``None`` terug als er na het strippen niets overblijft: een
    omschrijving die alleen uit lege tags bestond is geen omschrijving, en een
    lege regel in de app is verwarrender dan helemaal niets.
    """
    if not tekst:
        return None
    schoon = _REGELEINDE.sub("\n", tekst)
    schoon = _TAGS.sub("", schoon)
    schoon = _BBCODE.sub("", schoon)
    schoon = html.unescape(schoon)
    schoon = _WITRUIMTE.sub(" ", schoon)
    schoon = "\n".join(regel.strip() for regel in schoon.split("\n"))
    schoon = _LEGE_REGELS.sub("\n\n", schoon).strip()
    return schoon or None


__all__ = ["zonder_opmaak"]
