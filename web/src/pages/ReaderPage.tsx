import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import { ComicReader } from "../reader/ComicReader";

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

  return <ComicReader book={data} onClose={() => navigate(`/serie/${data.series_id}`)} />;
}
