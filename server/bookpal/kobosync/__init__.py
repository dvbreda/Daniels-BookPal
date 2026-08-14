"""Nickel-integratie voor de Kobo (laag B uit ontwerp 3).

Voor als je gewoon in Kobo's eigen lezer wilt lezen: boeken wegzetten, jouw
tabs als planken, en je voortgang terug. Los aan en uit te zetten, want dit is
de enige laag die op reverse-engineering leunt.
"""

from bookpal.kobosync.device import DeviceError, KoboDevice, open_device
from bookpal.kobosync.nickel import NickelError

__all__ = ["DeviceError", "KoboDevice", "NickelError", "open_device"]
