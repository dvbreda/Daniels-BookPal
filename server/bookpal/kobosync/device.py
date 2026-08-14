"""Een aangesloten Kobo herkennen.

Een Kobo die via USB hangt is een gewone schijf met een verborgen map ``.kobo``
erop. Die map is het bewijs: staat hij er, dan is dit een Kobo en niet zomaar
een USB-stick waar we per ongeluk bestanden op zouden zetten.

Er wordt bewust niet gezocht naar aangesloten apparaten. Deze server draait in
een container op een NAS en ziet alleen wat je hem laat zien; jij wijst de
gekoppelde map aan en wij controleren of het klopt.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Waar Nickel zijn database bewaart, gerekend vanaf de wortel van het apparaat.
DB_RELATIVE = Path(".kobo/KoboReader.sqlite")


class DeviceError(RuntimeError):
    """Hier staat geen Kobo, of hij is niet bruikbaar."""


@dataclass(frozen=True, slots=True)
class KoboDevice:
    """Een gekoppelde Kobo."""

    mount: Path

    @property
    def database(self) -> Path:
        return self.mount / DB_RELATIVE

    @property
    def writable(self) -> bool:
        probe = self.mount / ".bookpal-schrijftest"
        try:
            probe.write_bytes(b"")
            probe.unlink()
        except OSError:
            return False
        return True


def open_device(mount: str | Path) -> KoboDevice:
    """Controleer dat hier een Kobo staat en geef hem terug."""
    pad = Path(mount)
    if not pad.is_dir():
        raise DeviceError(f"{pad} is niet gekoppeld")
    device = KoboDevice(mount=pad)
    if not device.database.is_file():
        raise DeviceError(
            f"in {pad} staat geen .kobo/KoboReader.sqlite; is dit wel de Kobo en staat hij aan?"
        )
    return device


def find(mounts: list[str]) -> KoboDevice | None:
    """De eerste van deze mappen waar een Kobo blijkt te staan."""
    for mount in mounts:
        try:
            return open_device(mount)
        except DeviceError:
            continue
    return None


__all__ = ["DB_RELATIVE", "DeviceError", "KoboDevice", "find", "open_device"]
