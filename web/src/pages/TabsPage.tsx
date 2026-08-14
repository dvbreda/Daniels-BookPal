import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { RuleNode, Tab, TabIn } from "../api/types";
import { RuleEditor } from "../components/RuleEditor";
import { fieldDefs } from "../lib/ruleBuilder";

/** ``embedded`` laat de eigen kop en terugknop weg: in de instellingen staat
 * die er al, en twee keer "← Bibliotheek" onder elkaar is verwarrend. */
export function TabsPage({ embedded = false }: { embedded?: boolean } = {}) {
  const queryClient = useQueryClient();
  const { data: tabs } = useQuery({ queryKey: ["tabs"], queryFn: api.tabs });
  const { data: roots } = useQuery({ queryKey: ["libraries"], queryFn: api.libraries });
  const defs = fieldDefs(roots ?? []);

  const [editingId, setEditingId] = useState<number | "new" | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["tabs"] });
    void queryClient.invalidateQueries({ queryKey: ["tab-series"] });
  }

  const deleteTab = useMutation({
    mutationFn: (id: number) => api.deleteTab(id),
    onSuccess: refresh,
  });

  const move = useMutation({
    mutationFn: ({ tab, position }: { tab: Tab; position: number }) =>
      api.updateTab(tab.id, { ...tab, position }),
    onSuccess: refresh,
  });

  const sorted = [...(tabs ?? [])].sort((a, b) => a.position - b.position);

  return (
    <div className={embedded ? "" : "mx-auto max-w-3xl px-4 py-6"}>
      {!embedded && (
        <>
          <Link to="/" className="text-sm text-slate-400 hover:text-slate-200">
            ← Bibliotheek
          </Link>
          <h1 className="mt-4 text-2xl font-semibold text-slate-100">Tabs</h1>
        </>
      )}
      <p className="mt-1 text-sm text-slate-500">
        Een tab is een opgeslagen regel. Dezelfde regel bepaalt straks ook wat een
        slimme collectie toont — zie{" "}
        <Link to="/collecties" className="text-accent underline">
          Collecties
        </Link>
        .
      </p>

      <div className="mt-6 space-y-2">
        {sorted.map((tab, index) => (
          <div key={tab.id} className="flex items-center gap-3 rounded bg-ink-800 p-3">
            <div className="flex flex-col">
              <button
                disabled={index === 0}
                onClick={() => move.mutate({ tab, position: tab.position - 1 })}
                className="text-xs text-slate-500 hover:text-slate-200 disabled:opacity-30"
              >
                ▲
              </button>
              <button
                disabled={index === sorted.length - 1}
                onClick={() => move.mutate({ tab, position: tab.position + 1 })}
                className="text-xs text-slate-500 hover:text-slate-200 disabled:opacity-30"
              >
                ▼
              </button>
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-slate-100">
                {tab.icon ? `${tab.icon} ` : ""}
                {tab.name}
                {!tab.enabled && <span className="ml-2 text-xs text-slate-500">(uit)</span>}
              </p>
              <p className="truncate text-xs text-slate-500">
                {Object.keys(tab.rule).length === 0 ? "alles" : JSON.stringify(tab.rule)}
              </p>
            </div>
            <button
              onClick={() => setEditingId(tab.id)}
              className="rounded bg-ink-700 px-3 py-1.5 text-sm text-slate-200"
            >
              Bewerken
            </button>
            <button
              onClick={() => deleteTab.mutate(tab.id)}
              className="rounded bg-ink-700 px-3 py-1.5 text-sm text-slate-300"
            >
              Verwijderen
            </button>
          </div>
        ))}
        {sorted.length === 0 && (
          <p className="text-sm text-slate-500">Nog geen tabs — de bibliotheek toont nu alles.</p>
        )}
      </div>

      {editingId === null ? (
        <button
          onClick={() => setEditingId("new")}
          className="mt-6 rounded bg-accent px-4 py-2 text-sm text-ink-900"
        >
          Nieuwe tab
        </button>
      ) : (
        <TabEditor
          tab={editingId === "new" ? null : (sorted.find((t) => t.id === editingId) ?? null)}
          defs={defs}
          nextPosition={sorted.length}
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
      {message && <p className="mt-3 rounded bg-danger-bg p-3 text-sm text-danger">{message}</p>}
    </div>
  );
}

function TabEditor({
  tab,
  defs,
  nextPosition,
  onDone,
  onCancel,
}: {
  tab: Tab | null;
  defs: ReturnType<typeof fieldDefs>;
  nextPosition: number;
  onDone: (error: string | null) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(tab?.name ?? "");
  const [icon, setIcon] = useState(tab?.icon ?? "");
  const [rule, setRule] = useState<RuleNode | null>(tab?.rule ?? {});

  const save = useMutation({
    mutationFn: () => {
      if (rule === null) throw new Error("Ongeldige JSON.");
      const body: TabIn = { name, icon: icon || null, rule, position: tab?.position ?? nextPosition };
      return tab ? api.updateTab(tab.id, body) : api.createTab(body);
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
          value={icon}
          onChange={(event) => setIcon(event.target.value)}
          placeholder="🇯🇵"
          className="w-16 rounded bg-ink-700 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
        />
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Naam, bv. Manga"
          required
          className="flex-1 rounded bg-ink-700 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
        />
      </div>

      <RuleEditor initialRule={tab?.rule ?? {}} defs={defs} onChange={setRule} />

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
