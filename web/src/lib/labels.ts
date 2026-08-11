import type { BookKind, OriginRegion } from "../api/types";

export const REGION_LABELS: Record<OriginRegion, string> = {
  europe: "Europa",
  japan: "Japan",
  korea: "Korea",
  china: "China",
  us: "VS",
  other: "Overig",
  unknown: "Onbekend",
};

export const KIND_LABELS: Record<BookKind, string> = {
  comic: "Strips",
  epub: "Boeken",
  pdf: "PDF",
};
