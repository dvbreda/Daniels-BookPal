import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { Collection, CollectionIn, RuleNode } from "../api/types";
import { RuleEditor } from "../components/RuleEditor";
import { fieldDefs } from "../lib/ruleBuilder";

const GROUP_BY_OPTIONS = [
  { value: "", label: "Geen groepering" },
  { value: "publisher", label: "Uitgever" },
  { value: "folder", label: "Map" },
];

export function CollectionsPage() {
  const queryClient = useQueryClient();
  const { data: collections } = useQuery({ queryKey: ["collections"], queryFn: api.collections });
  const { data: roots } = useQuery({ queryKey: ["libraries"], queryFn: api.libraries });
  const defs = fieldDefs(roots ?? []);

  const [editingId, setEditingId] = useState<number | "new" | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["collections"] });
  }

  const deleteCollection = useMutation({
    mutationFn: (id: number) => api.deleteCollection(id),
    onSuccess: refresh,
  });

  return (
    <div className="mx-auto max-w-3xl px-4 py-6">
      <Link to="/" className="text-sm text-slate-400 hover:text-slate-200">
        ← Bibliotheek
      </Link>
      <h1 className="mt-4 text-2xl font-semibold text-slate-100">Collecties</h1>
      <p className="mt-1 text-sm text-slate-500">
        Dezelfde regel-engine als{" "}
        <Link to="/tabs" className="text-accent underline">
          tabs
        </Link>
        , maar met een groepering in plaats van een vaste plek in de tabbalk. Alle
        collecties hier zijn slim: ze volgen hun regel, je kiest geen boeken met de
        hand.
      </p>

      <div className="mt-6 space-y-2">
        {collections?.map((collection) => (
          <div key={collection.id} className="flex items-center gap-3 rounded bg-ink-800 p-3">
            <div className="min-w-0 flex-1">
              <p className="truncate text-slate-100">{collection.name}</p>
              <p className="truncate text-xs text-slate-500">
                {Object.keys(collection.rule).length === 0
                  ? "alles"
                  : JSON.stringify(collection.rule)}
                {collection.group_by &&
                  ` · gegroepeerd op ${GROUP_BY_OPTIONS.find((o) => o.value === collection.group_by)?.label ?? collection.group_by}`}
              </p>
            </div>
            <Link
              to={`/collectie/${collection.id}`}
              className="rounded bg-ink-700 px-3 py-1.5 text-sm text-slate-200"
            >
              Bekijken
            </Link>
            <button
              onClick={() => setEditingId(collection.id)}
              className="rounded bg-ink-700 px-3 py-1.5 text-sm text-slate-200"
            >
              Bewerken
            </button>
            <button
              onClick={() => deleteCollection.mutate(collection.id)}
              className="rounded bg-ink-700 px-3 py-1.5 text-sm text-slate-300"
            >
              Verwijderen
            </button>
          </div>
        ))}
        {collections?.length === 0 && (
          <p className="text-sm text-slate-500">Nog geen collecties.</p>
        )}
      </div>

      {editingId === null ? (
        <button
          onClick={() => setEditingId("new")}
          className="mt-6 rounded bg-accent px-4 py-2 text-sm text-ink-900"
        >
          Nieuwe collectie
        </button>
      ) : (
        <CollectionEditor
          collection={
            editingId === "new" ? null : (collections?.find((c) => c.id === editingId) ?? null)
          }
          defs={defs}
          onDone={(error) => {
            setMessage(error);
            if (!error) {
              setEditingId(null);
              refresh();
            }
          }}
          onCancel={() => setEditingId(null)}
        />
      )}
      {message && <p className="mt-3 rounded bg-red-950 p-3 text-sm text-red-300">{message}</p>}
    </div>
  );
}

function CollectionEditor({
  collection,
  defs,
  onDone,
  onCancel,
}: {
  collection: Collection | null;
  defs: ReturnType<typeof fieldDefs>;
  onDone: (error: string | null) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(collection?.name ?? "");
  const [groupBy, setGroupBy] = useState(collection?.group_by ?? "");
  const [rule, setRule] = useState<RuleNode | null>(collection?.rule ?? {});

  const save = useMutation({
    mutationFn: () => {
      if (rule === null) throw new Error("Ongeldige JSON.");
      const body: CollectionIn = { name, rule, group_by: groupBy || null };
      return collection ? api.updateCollection(collection.id, body) : api.createCollection(body);
    },
    onSuccess: () => onDone(null),
    onError: (error: unknown) => {
      onDone(error instanceof ApiError || error instanceof Error ? error.message : "Opslaan mislukt.");
    },
  });

  return (
    <form
      className="mt-6 space-y-4 rounded border border-ink-600 p-4"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <div className="flex gap-2">
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Naam, bv. Compleet uitgelezen"
          required
          className="flex-1 rounded bg-ink-700 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
        />
        <select
          value={groupBy}
          onChange={(event) => setGroupBy(event.target.value)}
          className="rounded bg-ink-700 px-3 py-2 text-sm text-slate-100"
        >
          {GROUP_BY_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      <RuleEditor initialRule={collection?.rule ?? {}} defs={defs} onChange={setRule} />

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={save.isPending || rule === null}
          className="rounded bg-accent px-4 py-2 text-sm text-ink-900 disabled:opacity-50"
        >
          Opslaan
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded bg-ink-700 px-4 py-2 text-sm text-slate-300"
        >
          Annuleren
        </button>
      </div>
    </form>
  );
}
