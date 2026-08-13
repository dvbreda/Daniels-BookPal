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
  /** Uit welke uitgave dit deel komt; alleen gevuld in de seriepagina. */
  edition_id: number | null;
  edition_name: string | null;
  /** Waarin die uitgave zich onderscheidt: taal en een label als "kleur". */
  edition_language: string | null;
  edition_note: string | null;
  /** Hetzelfde hoofdstuk uit een andere uitgave. */
  alternatives: BookAlternative[];
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

export interface MergeCandidate {
  id: number;
  title: string;
  books: number;
}

export interface SeriesRenamed extends Series {
  /** Was de naam vrij? Binnen één map kan een titel maar één keer bestaan;
   * dan is samenvoegen de enige weg vooruit. */
  renamed: boolean;
  /** Een serie die dezelfde naam blijkt te hebben. */
  merge_candidate: MergeCandidate | null;
}

export interface SyncCoversResult {
  updated: number;
  editions: string[];
  errors: string[];
}

export interface SeriesDetail extends Series {
  /** Eén regel per aflevering, tenzij je om alle uitgaven vraagt. */
  books: Book[];
  editions: Edition[];
}

export interface WikiHit {
  title: string;
  key: string;
  description: string | null;
  lang: string;
}

export interface NextChapter {
  book_id: number;
  title: string;
  number: string | null;
  volume: string | null;
  /** Al binnen, of moet het nog opgehaald worden? */
  has_file: boolean;
}

export interface ContinueInfo {
  book_id: number;
  title: string;
  number: string | null;
  /** De pagina waar je gebleven was; 0 voor een nieuw hoofdstuk. */
  page: number;
  /** Ga je verder in iets dat je al begonnen was, of begin je aan een nieuw
   * hoofdstuk? Bepaalt of de knop "Lees verder" of "Beginnen" heet. */
  resuming: boolean;
  /** Hoeveel hoofdstukken hiervóór nog niet uit zijn. */
  unread_before: number;
  /** Staat dit al op de NAS? Zo niet, dan haalt de knop het eerst op. Bij een
   * serie die je online volgt is dat de normale situatie. */
  has_file: boolean;
}

export interface LibraryRoot {
  /** Kan BookPal hier zelf iets neerzetten? Zo niet staat de reden in
   * write_problem — in gewone taal, want de oplossing verschilt per oorzaak. */
  writable?: boolean;
  write_problem?: string | null;
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
  /** Gevuld als je precies deze reeks bij deze bron al volgt. */
  subscribed_series_id: number | null;
  /** Gevuld als je hier al een serie van hebt onder (bijna) dezelfde titel;
   * volgen voegt dan een uitgave toe in plaats van een tweede serie te maken. */
  existing_series_id: number | null;
  existing_series_title: string | null;
  /** Rechtstreeks tonen als miniatuur; alleen na koppelen gaat hij door onze
   * eigen cache (zie SourceBadge/imageUrl.seriesCover). */
  cover_url: string | null;
  /** De pagina bij de bron, om te kunnen controleren wat dit is. */
  url: string | null;
  /** In welke talen er vertalingen bestaan. */
  languages: string[];
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
  /** In welke taal je deze reeks volgt; meerdere talen worden uitgaven van één serie. */
  language: string;
  /** Hoe de bron deze reeks noemt — het onderscheid tussen twee uitgaven. */
  source_title: string;
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
  /** Wat de knop in de lezer doet; los van wat er vanzelf gebeurt. */
  button_mode: TranslateMode;
  /** Met welk beeldmodel er ingekleurd wordt; altijd een beeldstand. */
  colour_mode: TranslateMode;
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

export interface ImportResult {
  moved: number;
  downloaded: number;
  skipped: number;
  errors: string[];
}

export interface IntakeFile {
  path: string;
  name: string;
  size: number;
  series: string | null;
  number: string | null;
}

export interface IntakeScan {
  /** Welke intake-mappen er daadwerkelijk bestaan. */
  folders: string[];
  /** Mappen die bestaan maar waaruit niets verplaatst kan worden. */
  unwritable: string[];
  files: IntakeFile[];
}

export interface IntakeImportResult {
  moved: number;
  skipped: number;
  errors: string[];
}

export interface MergeSuggestion {
  keep_id: number;
  keep_title: string;
  keep_books: number;
  absorb_id: number;
  absorb_title: string;
  absorb_books: number;
}

export interface ReadState {
  book_id: number;
  finished: boolean;
  /** Hoeveel uitgaven van deze aflevering het betrof. */
  affected: number;
}

export interface ChapterCount {
  ref: string;
  language: string;
  count: number;
}

export interface HomeItem {
  book_id: number;
  series_id: number;
  series_title: string;
  title: string;
  number: string | null;
  volume: string | null;
  kind: BookKind;
  has_file: boolean;
  extension: string | null;
  page_count: number | null;
  percent: number;
  finished: boolean;
  /** De pagina waar je gebleven was; de lezer opent hier. */
  page: number;
  updated_at: string | null;
  added_at: string;
}

export interface HomeRail {
  key: string;
  title: string;
  items: HomeItem[];
}

export interface Home {
  rails: HomeRail[];
}

export interface SidecarSyncResult {
  written: number;
  skipped: number;
  errors: string[];
}

export interface KoboStatus {
  mount: string | null;
  connected: boolean;
  writable: boolean;
  error: string | null;
  folder: string;
  ahead: number;
  series_ids: number[];
  export_books: boolean;
  write_shelves: boolean;
  read_progress: boolean;
  /** Standaard aan: dit schrijft in de database van je lezer. */
  dry_run: boolean;
}

export interface KoboPlanItem {
  book_id: number;
  series_title: string;
  title: string;
  path: string;
}

export interface KoboSyncResult {
  dry_run: boolean;
  planned: number;
  copied: number;
  skipped: number;
  removed: number;
  shelves_created: string[];
  shelf_entries: number;
  not_imported: number;
  progress_updated: number;
  /** De kopie die vóór het schrijven is gemaakt. */
  backup: string | null;
  errors: string[];
  notes: string[];
}

export interface IntakeUpload {
  path: string;
  name: string;
  size: number;
}

export interface IntakeFetch {
  /** bezig | klaar | mislukt | niets */
  state: string;
  url: string;
  folder: string | null;
  bytes_done: number;
  /** Wat de server zei dat er zou komen; bij een gedeelde map vaak onbekend. */
  bytes_total: number | null;
  saved: string[];
  skipped: number;
  errors: string[];
}

export interface BookAlternative {
  id: number;
  title: string;
  edition_id: number | null;
  edition_name: string | null;
  edition_language: string | null;
  edition_note: string | null;
  has_file: boolean;
}

/**
 * Eén uitgave binnen een serie. `book_count` is wat deze uitgave heeft,
 * `chosen_count` wat je er daadwerkelijk van te zien krijgt — het verschil is
 * wat een hoger gerangschikte uitgave al levert.
 */
export interface Edition {
  id: number;
  series_id: number;
  name: string;
  rank: number;
  note: string | null;
  /** Taal van het abonnement; leeg voor je eigen bestanden. */
  language: string | null;
  subscription_id: number | null;
  folder_path: string | null;
  book_count: number;
  chosen_count: number;
}

export interface MalImportProgress {
  marked: number;
  series: string[];
}

export interface MalListItem {
  mal_id: string;
  title: string;
  status: string;
  chapters: number;
  chapters_read: number;
  score: number;
  /** Gevuld als je deze al in je bibliotheek hebt (harde id-koppeling). */
  series_id: number | null;
  /** Een serie die zó heet maar nog geen id draagt — alleen een voorstel. */
  match_series_id: number | null;
  match_title: string | null;
}

export interface ShelfRow {
  series_id: number;
  title: string;
  author: string | null;
  status: string;
  shelf: string;
  chapters_read: number;
  chapters_total: number;
  percent: number;
  /** Het id bij deze tracker; zonder id kan MyAnimeList niet gepusht worden. */
  remote_id: string | null;
  pushable: boolean;
}

export interface Shelves {
  provider: string;
  /** Hoeveel series er geen id hebben bij deze tracker. */
  without_id: number;
  reading: ShelfRow[];
  to_read: ShelfRow[];
  read: ShelfRow[];
}

export interface GoodreadsStatus {
  /** Chromium wordt pas op verzoek gedownload. */
  browser_ready: boolean;
  browser_note: string;
  connected: boolean;
  last_sync_at: string | null;
}

export interface GoodreadsSyncResult {
  updated: string[];
  errors: string[];
}

export interface MalAuthorize {
  url: string;
  /** Dit adres moet in je MAL-app-registratie staan. */
  redirect_uri: string;
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

/** Wat een klus voor een heel hoofdstuk gaat inhouden, vóór je hem start. */
export interface BatchPlan {
  kind: BatchKind;
  mode: TranslateMode;
  pages: number;
  price_per_page: number;
  total: number;
  /** Batchwerk kost bij Google de helft van een gewone aanroep. */
  batch_factor: number;
}

export type BatchKind = "tekst" | "hertekend" | "kleuren";

export interface BatchStatus {
  kind: BatchKind;
  book_id: number;
  mode: TranslateMode;
  state: "bezig" | "klaar" | "mislukt";
  done: number;
  total: number;
  failed: number;
  error: string | null;
}
