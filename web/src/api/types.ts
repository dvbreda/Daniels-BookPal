/** Spiegelt bookpal/schemas.py. Dit is het contract waar alle clients aan hangen. */

export type BookKind = "comic" | "epub" | "pdf";

export type OriginRegion =
  | "europe"
  | "japan"
  | "korea"
  | "china"
  | "us"
  | "other"
  | "unknown";

export type OriginSource = "manual" | "online" | "embedded" | "root_default" | "none";

export interface Progress {
  position: Record<string, unknown>;
  percent: number;
  finished: boolean;
  device: string | null;
  updated_at: string;
}

export interface Book {
  id: number;
  series_id: number;
  kind: BookKind;
  title: string;
  number: string | null;
  volume: string | null;
  page_count: number | null;
  right_to_left: boolean;
  has_file: boolean;
  extension: string | null;
  added_at: string;
  progress: Progress | null;
}

export interface TocEntry {
  title: string;
  target: string;
  level: number;
}

export interface BookDetail extends Book {
  series_title: string;
  toc: TocEntry[];
}

export interface Series {
  id: number;
  title: string;
  sort_title: string;
  library_root_id: number | null;
  folder_path: string | null;
  origin_language: string | null;
  origin_country: string | null;
  origin_region: OriginRegion;
  origin_source: OriginSource;
  publisher: string | null;
  tags: string[];
  summary: string | null;
  book_count: number;
  kinds: BookKind[];
}

export interface SeriesDetail extends Series {
  books: Book[];
}

export interface LibraryRoot {
  id: number;
  name: string;
  path: string;
  enabled: boolean;
  default_origin_language: string | null;
  default_origin_region: OriginRegion | null;
  folder_as_collection: boolean;
  last_scan_at: string | null;
  series_count: number;
  book_count: number;
}

export interface ScanResult {
  root: string;
  added: number;
  updated: number;
  unchanged: number;
  removed: number;
  errors: string[];
}

export interface Health {
  status: string;
  version: string;
  roots: number;
  series: number;
  books: number;
  cache_mb: number;
}

export interface ImageProfile {
  name: string;
  max_width: number | null;
  max_height: number | null;
  format: string;
  grayscale: boolean;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export interface SeriesQuery {
  root_id?: number;
  region?: OriginRegion;
  kind?: BookKind;
  search?: string;
  offset?: number;
  limit?: number;
}
