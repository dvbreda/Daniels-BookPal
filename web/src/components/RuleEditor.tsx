import { useEffect, useState } from "react";

import type { RuleNode } from "../api/types";
import {
  type ConditionRow,
  type FieldDef,
  type FieldKey,
  compileRows,
  decompileRule,
  emptyRow,
} from "../lib/ruleBuilder";

/**
 * Voorwaarden-bouwer voor het gangbare geval (platte "en"), met een JSON-modus
 * erachter voor geneste and/or/not-regels die de bouwer niet kan tonen.
 * Meldt bij elke wijziging de gecompileerde regel — `null` betekent ongeldige
 * JSON, waarmee de aanroeper opslaan kan blokkeren.
 */
export function RuleEditor({
  initialRule,
  defs,
  onChange,
}: {
  initialRule: RuleNode;
  defs: Record<FieldKey, FieldDef>;
  onChange: (rule: RuleNode | null) => void;
}) {
  const initialRows = decompileRule(initialRule, defs);
  const [advanced, setAdvanced] = useState(initialRows === null);
  const [rows, setRows] = useState<ConditionRow[]>(initialRows ?? []);
  const [rawRule, setRawRule] = useState(() => JSON.stringify(initialRule, null, 2));

  useEffect(() => {
    if (advanced) {
      try {
        onChange(JSON.parse(rawRule) as RuleNode);
      } catch {
        onChange(null);
      }
    } else {
      onChange(compileRows(rows, defs));
    }
    // onChange komt van een useState-setter bij de aanroeper en is stabiel.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [advanced, rows, rawRule, defs]);

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
    <div className="space-y-2">
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
    </div>
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
