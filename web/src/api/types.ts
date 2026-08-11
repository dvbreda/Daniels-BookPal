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
  /** Van een abonnement (bron) in plaats van uit je eigen mappen. */
  from_source: boolean;
  /** Wie dit vertaald heeft, als de bron dat meegeeft. */
  source_group_name: string | null;
  /** Gezet bij een tijdelijke readahead-download. */
  expires_at: string | null;
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
  authors: string[];
  tags: string[];
  summary: string | null;
  book_count: number;
  kinds: BookKind[];
  /** Gevolgd bij een bron; kan hoofdstukken hebben zonder lokaal bestand. */
  from_source: boolean;
  /** Heeft deze serie een omslag van een bron (in plaats van "pagina 1")? */
  has_cover_url: boolean;
  /** Handmatig gekozen paginanummer voor de omslag, als dat gezet is. */
  cover_page_index: number | null;
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

/**
 * Een regelboom: combinatoren (`and`/`or`/`not`) met condities op een veld,
 * bv. `{"origin_region": {"eq": "europe"}}`. Spiegelt bookpal/tabs/rules.py —
 * bewust `unknown` op waarde-niveau, want de vorm hangt af van het veld.
 */
export type RuleNode = Record<string, unknown>;

export interface Tab {
  id: number;
  name: string;
  icon: string | null;
  position: number;
  rule: RuleNode;
  view_mode: string;
  group_by: string | null;
  enabled: boolean;
}

export interface TabIn {
  name: string;
  icon?: string | null;
  position?: number;
  rule?: RuleNode;
  view_mode?: string;
  group_by?: string | null;
  enabled?: boolean;
}

export interface Collection {
  id: number;
  name: string;
  smart: boolean;
  rule: RuleNode;
  group_by: string | null;
}

export interface CollectionIn {
  name: string;
  smart?: boolean;
  rule?: RuleNode;
  group_by?: string | null;
}

export interface SourceRow {
  id: number;
  type: string;
  name: string;
  enabled: boolean;
}

export interface SearchHit {
  ref: string;
  title: string;
  description: string | null;
  year: number | null;
  status: string | null;
  original_language: string | null;
  tracker_ids: Record<string, string>;
  /** Gevuld als je deze serie al volgt. */
  subscribed_series_id: number | null;
  /** Rechtstreeks tonen als miniatuur; alleen na koppelen gaat hij door onze
   * eigen cache (zie SourceBadge/imageUrl.seriesCover). */
  cover_url: string | null;
}

export type SubscriptionPolicy = "permanent" | "readahead";

/** Een vertaalgroep die deze reeks (deels) heeft gedaan. */
export interface TranslationGroup {
  id: string;
  name: string;
  chapters: number;
}

export interface SubscriptionRow {
  id: number;
  source_id: number;
  series_id: number;
  policy: SubscriptionPolicy;
  readahead_n: number;
  ttl_days: number;
  last_checked_at: string | null;
  /** Leeg = automatisch kiezen. */
  preferred_group_id: string | null;
  available_groups: TranslationGroup[];
  series_title: string;
  chapters_total: number;
  chapters_local: number;
}

export interface SubscribeResult {
  subscription: SubscriptionRow;
  series_id: number;
  chapters_added: number;
}

export interface RunReport {
  subscriptions: number;
  chapters_added: number;
  downloaded: number;
  expired: number;
  errors: string[];
}

export type BubbleKind = "speech" | "thought" | "caption" | "sfx";

export interface Bubble {
  /** [x0, y0, x1, y1], genormaliseerd op 0..1 van de hele pagina. */
  box: [number, number, number, number] | number[];
  source: string;
  translation: string;
  kind: BubbleKind;
  bold: boolean;
  italic: boolean;
}

export type TranslateMode = "text" | "image_fast" | "image_pro";

export interface PageTranslation {
  book_id: number;
  page_index: number;
  target_lang: string;
  provider: string;
  model: string;
  bubbles: Bubble[];
  mode: TranslateMode;
  /** In de beeldstanden is de hele pagina hertekend; dan is er geen overlay
   * maar een vervangende afbeelding, en valt er niet op een ballon te tikken. */
  full_page: boolean;
}

export interface TranslateModeInfo {
  mode: TranslateMode;
  /** Zonder Gemini-sleutel is er niets te kiezen. */
  configured: boolean;
  /** Ruwe richtprijs per pagina in dollar, per stand. */
  costs: Record<string, number>;
}

export interface TranslationStatus {
  book_id: number;
  target_lang: string;
  provider: string;
  /** False als er geen Gemini-sleutel is; dan blijft de knop verborgen. */
  configured: boolean;
  page_count: number | null;
  translated: number;
  queued: number;
}

export interface TranslateBookResult {
  queued: number;
  already_done: number;
}

export interface TrackerAccountRow {
  id: number;
  provider: string;
  enabled: boolean;
  dry_run: boolean;
  last_sync_at: string | null;
  /** True zodra de OAuth-uitwisseling een access_token heeft opgeleverd. */
  connected: boolean;
}

export interface PushResultRow {
  series_id: number;
  title: string;
  pushed: boolean;
  dry_run: boolean;
  detail: string;
}

export interface PushReport {
  provider: string;
  pushed: number;
  results: PushResultRow[];
  errors: string[];
}
