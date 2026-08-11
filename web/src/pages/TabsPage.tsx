import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { RuleNode, Tab, TabIn } from "../api/types";
import { KIND_LABELS, REGION_LABELS } from "../lib/labels";

type FieldKey =
  | "kind"
  | "extension"
  | "origin_region"
  | "publisher"
  | "tag"
  | "root"
  | "source"
  | "reading_status";

type ValueType = "select" | "multiselect" | "text";

interface FieldDef {
  label: string;
  op: string;
  valueType: ValueType;
  options?: { value: string; label: string }[];
}

const EXTENSION_OPTIONS = [
  { value: "cbz", label: "cbz" },
  { value: "cbr", label: "cbr" },
  { value: "cb7", label: "cb7" },
  { value: "epub", label: "epub" },
  { value: "pdf", label: "pdf" },
];

const SOURCE_OPTIONS = [
  { value: "local", label: "Lokaal bestand" },
  { value: "remote", label: "Alleen online" },
];

const READING_STATUS_OPTIONS = [
  { value: "unread", label: "Onbegonnen" },
  { value: "reading", label: "Bezig" },
  { value: "finished", label: "Uitgelezen" },
];

/** Bouwt de FIELD_DEFS met de bibliotheekmappen erbij, want die zijn dynamisch. */
function fieldDefs(roots: { id: number; name: string }[]): Record<FieldKey, FieldDef> {
  return {
    kind: {
      label: "Soort",
      op: "eq",
      valueType: "select",
      options: Object.entries(KIND_LABELS).map(([value, label]) => ({ value, label })),
    },
    extension: {
      label: "Bestandstype",
      op: "in",
      valueType: "multiselect",
      options: EXTENSION_OPTIONS,
    },
    origin_region: {
      label: "Herkomst",
      op: "eq",
      valueType: "select",
      options: Object.entries(REGION_LABELS).map(([value, label]) => ({ value, label })),
    },
    publisher: { label: "Uitgever bevat", op: "contains", valueType: "text" },
    tag: { label: "Label", op: "eq", valueType: "text" },
    root: {
      label: "Map",
      op: "eq",
      valueType: "select",
      options: roots.map((root) => ({ value: String(root.id), label: root.name })),
    },
    source: { label: "Bron", op: "eq", valueType: "select", options: SOURCE_OPTIONS },
    reading_status: {
      label: "Leesstatus",
      op: "eq",
      valueType: "select",
      options: READING_STATUS_OPTIONS,
    },
  };
}

interface ConditionRow {
  field: FieldKey;
  value: string | string[];
}

function emptyRow(field: FieldKey, def: FieldDef): ConditionRow {
  return { field, value: def.valueType === "multiselect" ? [] : "" };
}

function hasValue(row: ConditionRow): boolean {
  return Array.isArray(row.value) ? row.value.length > 0 : row.value !== "";
}

function rowToNode(row: ConditionRow, defs: Record<FieldKey, FieldDef>): RuleNode {
  const def = defs[row.field];
  const value = def.valueType === "select" && row.field === "root" ? Number(row.value) : row.value;
  return { [row.field]: { [def.op]: value } };
}

function compileRows(rows: ConditionRow[], defs: Record<FieldKey, FieldDef>): RuleNode {
  const nodes = rows.filter(hasValue).map((row) => rowToNode(row, defs));
  if (nodes.length === 0) return {};
  const [first] = nodes;
  if (nodes.length === 1 && first) return first;
  return { and: nodes };
}

/** Best-effort: alleen platte "and van bekende condities" is als rijen te tonen. */
function decompileRule(rule: RuleNode, defs: Record<FieldKey, FieldDef>): ConditionRow[] | null {
  const nodeToRow = (node: RuleNode): ConditionRow | null => {
    const entries = Object.entries(node);
    const entry = entries[0];
    if (entries.length !== 1 || !entry) return null;
    const [field, spec] = entry;
    if (!(field in defs) || typeof spec !== "object" || spec === null) return null;
    const def = defs[field as FieldKey];
    const specEntries = Object.entries(spec as Record<string, unknown>);
    const specEntry = specEntries[0];
    if (specEntries.length !== 1 || !specEntry || specEntry[0] !== def.op) return null;
    const value = specEntry[1];
    if (def.valueType === "multiselect" && !Array.isArray(value)) return null;
    return { field: field as FieldKey, value: value as string | string[] };
  };

  if (Object.keys(rule).length === 0) return [];
  if ("and" in rule && Array.isArray(rule.and)) {
    const rows = (rule.and as RuleNode[]).map(nodeToRow);
    return rows.every((row): row is ConditionRow => row !== null) ? rows : null;
  }
  const single = nodeToRow(rule);
  return single ? [single] : null;
}

export function TabsPage() {
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
    <div className="mx-auto max-w-3xl px-4 py-6">
      <Link to="/" className="text-sm text-slate-400 hover:text-slate-200">
        ← Bibliotheek
      </Link>
      <h1 className="mt-4 text-2xl font-semibold text-slate-100">Tabs</h1>
      <p className="mt-1 text-sm text-slate-500">
        Een tab is een opgeslagen regel. Dezelfde regel bepaalt straks ook wat een
        slimme collectie toont.
      </p>

      <div className="mt-6 space-y-2">
        {sorted.map((tab, index) => (
          <div
            key={tab.id}
            className="flex items-center gap-3 rounded bg-ink-800 p-3"
          >
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
      {message && <p className="mt-3 rounded bg-red-950 p-3 text-sm text-red-300">{message}</p>}
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
  defs: Record<FieldKey, FieldDef>;
  nextPosition: number;
  onDone: (error: string | null) => void;
  onCancel: () => void;
}) {
  const initialRows = tab ? decompileRule(tab.rule, defs) : [];
  const [advanced, setAdvanced] = useState(initialRows === null);
  const [name, setName] = useState(tab?.name ?? "");
  const [icon, setIcon] = useState(tab?.icon ?? "");
  const [rows, setRows] = useState<ConditionRow[]>(initialRows ?? []);
  const [rawRule, setRawRule] = useState(() => JSON.stringify(tab?.rule ?? {}, null, 2));

  const save = useMutation({
    mutationFn: () => {
      let rule: RuleNode;
      if (advanced) {
        try {
          rule = JSON.parse(rawRule) as RuleNode;
        } catch {
          throw new Error("Ongeldige JSON.");
        }
      } else {
        rule = compileRows(rows, defs);
      }
      const body: TabIn = { name, icon: icon || null, rule, position: tab?.position ?? nextPosition };
      return tab ? api.updateTab(tab.id, body) : api.createTab(body);
    },
    onSuccess: () => onDone(null),
    onError: (error: unknown) => {
      onDone(error instanceof ApiError || error instanceof Error ? error.message : "Opslaan mislukt.");
    },
  });

  function addRow() {
    setRows([...rows, emptyRow("kind", defs.kind)]);
  }

  function updateRow(index: number, next: ConditionRow) {
    setRows(rows.map((row, i) => (i === index ? next : row)));
  }

  function removeRow(index: number) {
    setRows(rows.filter((_, i) => i !== index));
  }

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

      <div className="flex items-center justify-between">
        <span className="text-xs uppercase tracking-wide text-slate-500">
          Regel (alle voorwaarden moeten kloppen)
        </span>
        <button
          type="button"
          onClick={() => setAdvanced(!advanced)}
          className="text-xs text-slate-400 underline"
        >
          {advanced ? "Eenvoudige weergave" : "Geavanceerd (JSON)"}
        </button>
      </div>

      {advanced ? (
        <textarea
          value={rawRule}
          onChange={(event) => setRawRule(event.target.value)}
          rows={6}
          spellCheck={false}
          className="w-full rounded bg-ink-900 px-3 py-2 font-mono text-xs text-slate-100"
        />
      ) : (
        <div className="space-y-2">
          {rows.map((row, index) => (
            <ConditionRowEditor
              key={index}
              row={row}
              defs={defs}
              onChange={(next) => updateRow(index, next)}
              onRemove={() => removeRow(index)}
            />
          ))}
          <button
            type="button"
            onClick={addRow}
            className="rounded bg-ink-700 px-3 py-1.5 text-sm text-slate-200"
          >
            + Voorwaarde
          </button>
        </div>
      )}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={save.isPending}
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

function ConditionRowEditor({
  row,
  defs,
  onChange,
  onRemove,
}: {
  row: ConditionRow;
  defs: Record<FieldKey, FieldDef>;
  onChange: (row: ConditionRow) => void;
  onRemove: () => void;
}) {
  const def = defs[row.field];
  return (
    <div className="flex flex-wrap items-center gap-2 rounded bg-ink-800 p-2">
      <select
        value={row.field}
        onChange={(event) => {
          const field = event.target.value as FieldKey;
          onChange(emptyRow(field, defs[field]));
        }}
        className="rounded bg-ink-700 px-2 py-1.5 text-sm text-slate-100"
      >
        {Object.entries(defs).map(([key, fieldDef]) => (
          <option key={key} value={key}>
            {fieldDef.label}
          </option>
        ))}
      </select>

      {def.valueType === "text" && (
        <input
          value={row.value as string}
          onChange={(event) => onChange({ ...row, value: event.target.value })}
          className="min-w-0 flex-1 rounded bg-ink-700 px-2 py-1.5 text-sm text-slate-100"
        />
      )}

      {def.valueType === "select" && (
        <select
          value={row.value as string}
          onChange={(event) => onChange({ ...row, value: event.target.value })}
          className="min-w-0 flex-1 rounded bg-ink-700 px-2 py-1.5 text-sm text-slate-100"
        >
          <option value="">— kies —</option>
          {def.options?.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      )}

      {def.valueType === "multiselect" && (
        <div className="flex flex-wrap gap-2">
          {def.options?.map((option) => {
            const selected = (row.value as string[]).includes(option.value);
            return (
              <button
                type="button"
                key={option.value}
                onClick={() => {
                  const current = row.value as string[];
                  const next = selected
                    ? current.filter((v) => v !== option.value)
                    : [...current, option.value];
                  onChange({ ...row, value: next });
                }}
                className={`rounded px-2 py-1 text-xs ${
                  selected ? "bg-accent text-ink-900" : "bg-ink-700 text-slate-300"
                }`}
              >
                {option.label}
              </button>
            );
          })}
        </div>
      )}

      <button type="button" onClick={onRemove} className="ml-auto text-xs text-slate-500">
        verwijderen
      </button>
    </div>
  );
}
