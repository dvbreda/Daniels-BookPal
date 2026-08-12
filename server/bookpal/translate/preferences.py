"""De gekozen vertaalstand, bewaard in de database (M8).

Bewust niet in de omgeving (`BOOKPAL_...`): dit is een keuze die je tijdens het
lezen wilt kunnen omzetten, niet een die een herstart van de container vraagt.
De duurdere standen kosten per pagina geld, dus het hoort een bewuste, zichtbare
schakelaar te zijn in plaats van iets dat in een `.env` verstopt zit.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from bookpal.models import Setting
from bookpal.translate.modes import TranslateMode

logger = logging.getLogger(__name__)

SETTING_KEY = "translate"


def get_mode(session: Session) -> TranslateMode:
    """De ingestelde stand. Valt terug op de goedkope: een dure stand hoort
    nooit de standaard te zijn die je per ongeluk aan laat staan."""
    row = session.get(Setting, SETTING_KEY)
    if row is None:
        return TranslateMode.TEXT
    try:
        return TranslateMode(str(row.value.get("mode", TranslateMode.TEXT)))
    except ValueError:
        logger.warning("onbekende vertaalstand in instellingen: %r", row.value)
        return TranslateMode.TEXT


def get_button_mode(session: Session) -> TranslateMode:
    """Wat de knop in de lezer doet.

    Losgekoppeld van de automatische stand, en dat is het hele punt: vanzelf
    vertalen mag goedkoop zijn, maar als je zelf op een pagina drukt is dat
    juist omdat die ene het waard is. Standaard het snelle beeldmodel — een
    bewuste stap omhoog ten opzichte van de tekststand, zonder meteen de
    duurste te zijn.
    """
    row = session.get(Setting, SETTING_KEY)
    if row is None:
        return TranslateMode.IMAGE_FAST
    try:
        return TranslateMode(str(row.value.get("button_mode", TranslateMode.IMAGE_FAST)))
    except ValueError:
        logger.warning("onbekende knopstand in instellingen: %r", row.value)
        return TranslateMode.IMAGE_FAST


def set_button_mode(session: Session, mode: TranslateMode) -> TranslateMode:
    row = session.get(Setting, SETTING_KEY)
    if row is None:
        row = Setting(key=SETTING_KEY, value={})
        session.add(row)
    row.value = {**row.value, "button_mode": str(mode)}
    session.commit()
    return mode


def set_mode(session: Session, mode: TranslateMode) -> TranslateMode:
    row = session.get(Setting, SETTING_KEY)
    if row is None:
        row = Setting(key=SETTING_KEY, value={})
        session.add(row)
    # Nieuw dict: SQLAlchemy ziet een wijziging ín een JSON-dict niet.
    row.value = {**row.value, "mode": str(mode)}
    session.commit()
    return mode
