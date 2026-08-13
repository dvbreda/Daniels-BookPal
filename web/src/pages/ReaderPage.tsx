import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import { ComicReader } from "../reader/ComicReader";
import { EpubReader } from "../reader/EpubReader";

/**
 * Tot hoever "ik heb er even in gekeken" loopt.
 *
 * Een hoofdstuk aanklikken en na een paar pagina's terugkeren is geen lezen,
 * maar het staat wel als voortgang genoteerd en telt daarmee mee voor
 * verder-lezen. Onder deze grens vragen we of het weg mag; erboven gaan we
 * ervan uit dat je echt bezig was.
 */
const NET_BEGONNEN = 10;

export function ReaderPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["book", Number(id)],
    queryFn: () => api.book(Number(id)),
  });

  // De stand waarmee je afsloot, zolang de vraag openstaat.
  const [afsluiten, setAfsluiten] = useState<number | null>(null);

  const alsOngelezen = useMutation({
    mutationFn: () => api.setReadState(Number(id), false),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["series-detail"] });
      void queryClient.invalidateQueries({ queryKey: ["continue"] });
      terug();
    },
  });

  const terug = () => {
    navigate(data ? `/serie/${data.series_id}` : "/");
  };

  if (isLoading) {
    return (
      <div className="flex h-viewport items-center justify-center bg-ink-900 text-slate-400">
        Laden…
      </div>
    );
  }
  if (error || !data) {
    return (
      <div className="flex h-viewport flex-col items-center justify-center gap-4 bg-ink-900 text-slate-300">
        <p>Kon dit boek niet openen.</p>
        <button className="rounded bg-ink-700 px-4 py-2" onClick={() => navigate(-1)}>
          Terug
        </button>
      </div>
    );
  }

  const close = (percent: number) => {
    // Alleen als er iets te wissen valt, en niet bij iets wat je al uit had:
    // dan is even terugkijken juist normaal en hoort er niets te veranderen.
    const alUit = data.progress?.finished ?? false;
    if (!alUit && percent > 0 && percent < NET_BEGONNEN) {
      setAfsluiten(percent);
      return;
    }
    terug();
  };

  return (
    <>
      {data.kind === "epub" ? (
        <EpubReader book={data} onClose={close} />
      ) : (
        <ComicReader book={data} onClose={close} />
      )}

      {afsluiten !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/80 p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Als ongelezen markeren?"
            className="w-full max-w-sm rounded-lg bg-ink-800 p-4 text-slate-200 shadow-xl"
          >
            <p className="text-sm">
              Je bent hier net begonnen ({Math.round(afsluiten)}%). Als ongelezen markeren?
            </p>
            <div className="mt-4 flex flex-wrap justify-end gap-2">
              <button
                onClick={terug}
                className="rounded bg-ink-700 px-3 py-2 text-sm text-slate-300"
              >
                Nee, bewaar mijn plek
              </button>
              <button
                onClick={() => alsOngelezen.mutate()}
                disabled={alsOngelezen.isPending}
                className="rounded bg-accent px-3 py-2 text-sm text-ink-900 disabled:opacity-50"
              >
                {alsOngelezen.isPending ? "Bezig…" : "Ja, als ongelezen"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
