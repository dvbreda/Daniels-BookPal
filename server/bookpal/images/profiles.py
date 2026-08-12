"""Beeldprofielen: één bron, meerdere doelen.

Het profiel-concept staat er vanaf het begin in omdat de Kobo eraan hangt. Een
e-ink-apparaat wil geen kleuren-WebP van 1600 pixels breed dat het zelf moet
decoderen en verkleinen; het wil precies de paneelresolutie, in grijstinten, al
gedither. Door dat hier te doen hoeft de Kobo-app straks alleen nog te blitten —
en dat is wat een leeservaring op zulke hardware vlot maakt.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ImageProfile:
    name: str
    max_width: int | None = None
    max_height: int | None = None
    format: str = "webp"  # webp | jpeg | png
    quality: int = 82
    grayscale: bool = False
    # E-ink toont 16 grijswaarden; dithering voorkomt banding in kleurvlakken.
    dither_levels: int | None = None

    @property
    def extension(self) -> str:
        return {"webp": ".webp", "jpeg": ".jpg", "png": ".png"}[self.format]

    @property
    def media_type(self) -> str:
        return {"webp": "image/webp", "jpeg": "image/jpeg", "png": "image/png"}[self.format]


# Schermen waarvoor we renderen. De Kobo-profielen komen exact overeen met het
# paneel, zodat er op het apparaat niets meer geschaald hoeft te worden.
PROFILES: dict[str, ImageProfile] = {
    "thumb": ImageProfile("thumb", max_width=320, quality=75),
    "cover": ImageProfile("cover", max_width=640, quality=80),
    "web": ImageProfile("web", max_width=1600, quality=82),
    "web-hidpi": ImageProfile("web-hidpi", max_width=2400, quality=80),
    "original": ImageProfile("original", format="png", quality=100),
    # Voor omslagen in BookPal Lite. Png en geen webp: de browser van een Kobo
    # kent webp niet, en dan blijft er een leeg vlak staan zonder dat er iets
    # in het log komt. Grijs en geditherd omdat het scherm toch niet meer kan.
    "kobo-thumb": ImageProfile(
        "kobo-thumb", max_width=240, format="png", grayscale=True, dither_levels=16
    ),
    # E-ink. PNG omdat grijswaarden verliesloos moeten blijven: na dithering
    # maakt JPEG-ruis het beeld juist slechter, niet kleiner.
    "kobo-nia": ImageProfile("kobo-nia", 758, 1024, format="png", grayscale=True, dither_levels=16),
    "kobo-clara": ImageProfile(
        "kobo-clara", 1072, 1448, format="png", grayscale=True, dither_levels=16
    ),
    "kobo-libra": ImageProfile(
        "kobo-libra", 1264, 1680, format="png", grayscale=True, dither_levels=16
    ),
    "kobo-elipsa": ImageProfile(
        "kobo-elipsa", 1404, 1872, format="png", grayscale=True, dither_levels=16
    ),
    "kobo-sage": ImageProfile(
        "kobo-sage", 1440, 1920, format="png", grayscale=True, dither_levels=16
    ),
}

DEFAULT_PROFILE = "web"


def get_profile(name: str | None) -> ImageProfile:
    if not name:
        return PROFILES[DEFAULT_PROFILE]
    profile = PROFILES.get(name)
    if profile is None:
        raise KeyError(name)
    return profile


def profile_names() -> list[str]:
    return sorted(PROFILES)
