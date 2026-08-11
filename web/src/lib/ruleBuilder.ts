/**
 * Bouwt en leest de platte "en van condities"-vorm die de eenvoudige
 * regel-bouwer aankan. Spiegelt de velden die bookpal/tabs/rules.py
 * ondersteunt; alles wat hier niet in past (geneste and/or/not) blijft
 * alleen als JSON te bewerken — zie components/RuleEditor.tsx.
 */

import type { LibraryRoot, RuleNode } from "../api/types";
import { KIND_LABELS, REGION_LABELS } from "./labels";

export type FieldKey =
  | "kind"
  | "extension"
  | "origin_region"
  | "publisher"
  | "tag"
  | "root"
  | "source"
  | "reading_status";

type ValueType = "select" | "multiselect" | "text";

export interface FieldDef {
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
export function fieldDefs(roots: Pick<LibraryRoot, "id" | "name">[]): Record<FieldKey, FieldDef> {
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

export interface ConditionRow {
  field: FieldKey;
  value: string | string[];
}

export function emptyRow(field: FieldKey, def: FieldDef): ConditionRow {
  return { field, value: def.valueType === "multiselect" ? [] : "" };
}

export function hasValue(row: ConditionRow): boolean {
  return Array.isArray(row.value) ? row.value.length > 0 : row.value !== "";
}

function rowToNode(row: ConditionRow, defs: Record<FieldKey, FieldDef>): RuleNode {
  const def = defs[row.field];
  const value = def.valueType === "select" && row.field === "root" ? Number(row.value) : row.value;
  return { [row.field]: { [def.op]: value } };
}

export function compileRows(rows: ConditionRow[], defs: Record<FieldKey, FieldDef>): RuleNode {
  const nodes = rows.filter(hasValue).map((row) => rowToNode(row, defs));
  if (nodes.length === 0) return {};
  const [first] = nodes;
  if (nodes.length === 1 && first) return first;
  return { and: nodes };
}

/** Best-effort: alleen platte "and van bekende condities" is als rijen te tonen. */
export function decompileRule(
  rule: RuleNode,
  defs: Record<FieldKey, FieldDef>,
): ConditionRow[] | null {
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
