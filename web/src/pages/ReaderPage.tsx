import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import { ComicReader } from "../reader/ComicReader";
import { EpubReader } from "../reader/EpubReader";

export function ReaderPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const { data, isLoading, error } = useQuery({
    queryKey: ["book", Number(id)],
    queryFn: () => api.book(Number(id)),
  });

  if (isLoading) {
    return <div className="flex h-screen items-center justify-center bg-ink-900 text-slate-400">Laden…</div>;
  }
  if (error || !data) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4 bg-ink-900 text-slate-300">
        <p>Kon dit boek niet openen.</p>
        <button className="rounded bg-ink-700 px-4 py-2" onClick={() => navigate(-1)}>
          Terug
        </button>
      </div>
    );
  }

  const close = () => navigate(`/serie/${data.series_id}`);

  // Epub rendert de client zelf (foliate-js): herschikbare tekst heeft geen
  // vaste pagina's die de server kan knippen. Strips en pdf komen als beeld
  // van de server en gaan naar de stripleer.
  return data.kind === "epub" ? (
    <EpubReader book={data} onClose={close} />
  ) : (
    <ComicReader book={data} onClose={close} />
  );
}
