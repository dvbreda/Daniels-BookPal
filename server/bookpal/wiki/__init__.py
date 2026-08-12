"""Wikipedia-artikelen als epub (achtergrond bij een serie, boek of auteur).

Waarom een epub en niet gewoon een webpagina: dan lees je het met dezelfde
lezer als de rest — zelfde lettergrootte, zelfde thema, zelfde manier van
bladeren, en op de Kobo zonder een browser open te hoeven trekken.

Geen sleutel nodig. Wikipedia's REST-API is open; we sturen wel een eigen
User-Agent mee, want dat is wat hun beleid vraagt van iedereen die
geautomatiseerd langskomt.
"""

from bookpal.wiki.service import WikiError, WikiHit, article_epub, search

__all__ = ["WikiError", "WikiHit", "article_epub", "search"]
