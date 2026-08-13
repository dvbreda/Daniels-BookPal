import { useState } from "react";

import type { Bubble } from "../api/types";
import { usePageTranslation } from "./usePageTranslation";

/**
 * De vertaalde tekstwolkjes over een pagina heen (M8).
 *
 * De vakken staan in procenten, niet in pixels: de server levert ze
 * genormaliseerd op 0..1 van de hele pagina, dus dezelfde vertaling past over
 * elk beeldprofiel en over elke zoomfactor. Daarom hoeft dit niets te weten
 * van de afmeting van de afbeelding — dat scheelt een resize-observer en een
 * hoop gedoe bij het omslaan.
 *
 * Er is bewust geen inpainting: een dekkend vlakje met de vertaling erop. Tik
 * erop en je ziet het origineel weer, want dat is precies waar je bij een
 * twijfelachtige vertaling naar wilt kunnen kijken.
 */
export function TranslationOverlay({
  bookId,
  pageIndex,
  enabled,
}: {
  bookId: number;
  pageIndex: number;
  enabled: boolean;
}) {
  const { data } = usePageTranslation(bookId, pageIndex, enabled);

  // In de beeldstanden is de hele pagina al hertekend; dan hoort hier niets
  // overheen te komen, anders staat er tekst dubbel.
  if (!enabled || !data || data.full_page || data.bubbles.length === 0) return null;

  return (
    // De containercontext staat hier en niet op het ouder-element: dit vlak
    // ontleent zijn maat aan de pagina, dus containment kost hier niets.
    <div className="pointer-events-none absolute inset-0 [container-type:inline-size]">
      {data.bubbles.map((bubble, index) => (
        <BubbleBox key={index} bubble={bubble} />
      ))}
    </div>
  );
}

/**
 * Stond het origineel in kapitalen? Dit vragen we niet aan het model — het
 * staat al in de brontekst. Striplettering is traditioneel volledig in
 * kapitalen; een vertaling in onderkast daartussen valt meteen op als
 * "ingeplakt". Zelfde regel als `Bubble.upper` aan de serverkant (M8), zodat
 * de web-overlay en de ingebakken Kobo-versie er hetzelfde uitzien.
 */
function isAllCaps(source: string): boolean {
  const letters = [...source].filter((char) => /\p{L}/u.test(char));
  return letters.length >= 2 && letters.every((char) => char === char.toUpperCase());
}

function BubbleBox({ bubble }: { bubble: Bubble }) {
  const [showSource, setShowSource] = useState(false);
  const [x0, y0, x1, y1] = bubble.box;
  const upper = isAllCaps(bubble.source);

  return (
    <div
      // Zo rond als het kan: een pilvorm volgt de kortste zijde, dus bij een
      // ongeveer vierkant vlak is het een cirkel en bij een breed vlak een
      // ovaal met ronde uiteinden. Dat dekt merkbaar minder tekening af dan
      // een rechthoek, en het lijkt op wat er onder zit — een tekstballon is
      // zelf ook rond. De zijkantmarge is een percentage van het vlak zelf,
      // zodat de tekst niet in de bocht loopt.
      className="pointer-events-auto absolute flex items-center justify-center overflow-hidden rounded-full border border-black/40 bg-white text-center leading-tight text-black"
      style={{
        left: `${x0 * 100}%`,
        top: `${y0 * 100}%`,
        width: `${(x1 - x0) * 100}%`,
        height: `${(y1 - y0) * 100}%`,
        paddingInline: "8%",
        // Meeschalen met het vlak zelf: cqw is een procent van de breedte van
        // de pagina-container, dus de tekst blijft in verhouding bij zoomen.
        fontSize: `clamp(7px, ${Math.max(1.1, (x1 - x0) * 7)}cqw, 20px)`,
        fontFamily: '"Comic Neue", sans-serif',
        fontWeight: bubble.bold ? 700 : 400,
        fontStyle: bubble.italic ? "italic" : "normal",
        textTransform: upper && !showSource ? "uppercase" : "none",
      }}
      onClick={(event) => {
        event.stopPropagation();
        setShowSource((value) => !value);
      }}
      title={bubble.source}
    >
      <span className="max-h-full overflow-hidden">
        {showSource ? bubble.source : bubble.translation}
      </span>
    </div>
  );
}
