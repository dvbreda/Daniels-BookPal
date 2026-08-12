import type {
  BookDetail,
  Collection,
  ContinueInfo,
  CollectionIn,
  Health,
  ImageProfile,
  ImportResult,
  IntakeImportResult,
  IntakeFetch,
  IntakeScan,
  IntakeUpload,
  GoodreadsStatus,
  GoodreadsSyncResult,
  LibraryRoot,
  MalAuthorize,
  Edition,
  MalImportProgress,
  MalListItem,
  MergeCandidate,
  MergeSuggestion,
  NextChapter,
  PageTranslation,
  Paginated,
  Progress,
  ReadState,
  PushReport,
  RunReport,
  ScanResult,
  SearchHit,
  Series,
  SeriesDetail,
  SeriesRenamed,
  SyncCoversResult,
  SeriesQuery,
  Shelves,
  SourceRow,
  SubscribeResult,
  SubscriptionPolicy,
  SubscriptionRow,
  Tab,
  TabIn,
  TrackerAccountRow,
  TranslateBookResult,
  TranslateMode,
  TranslateModeInfo,
  TranslationStatus,
  WikiHit,
} from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // Bij een upload moet de browser zelf de Content-Type zetten: multipart heeft
  // een boundary die wij hier niet kennen, en een handmatige header maakt het
  // verzoek onleesbaar voor de server.
  const isFormData = init?.body instanceof FormData;
  const response = await fetch(path, {
    ...init,
    headers: isFormData
      ? { ...init?.headers }
      : { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    // De server geeft in `detail` een uitleg in gewone taal mee; die willen we
    // aan de gebruiker kunnen tonen in plaats van "500".
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* geen JSON-body */
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function queryString(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  health: () => request<Health>("/api/health"),
  profiles: () => request<ImageProfile[]>("/api/profiles"),

  libraries: () => request<LibraryRoot[]>("/api/libraries"),
  addLibrary: (body: {
    name: string;
    path: string;
    default_origin_region?: string | null;
  }) => request<LibraryRoot>("/api/libraries", { method: "POST", body: JSON.stringify(body) }),
  deleteLibrary: (id: number) =>
    request<void>(`/api/libraries/${id}`, { method: "DELETE" }),
  scanLibrary: (id: number, force = false) =>
    request<ScanResult>(`/api/libraries/${id}/scan${queryString({ force })}`, {
      method: "POST",
    }),
  scanAll: () => request<ScanResult[]>("/api/libraries/scan", { method: "POST" }),

  series: (query: SeriesQuery = {}) =>
    request<Paginated<Series>>(`/api/series${queryString({ ...query })}`),
  seriesDetail: (id: number, allEditions = false) =>
    request<SeriesDetail>(`/api/series/${id}${queryString({ all_editions: allEditions || undefined })}`),
  orderEditions: (seriesId: number, editionIds: number[]) =>
    request<Edition[]>(`/api/series/${seriesId}/editions/order`, {
      method: "POST",
      body: JSON.stringify({ edition_ids: editionIds }),
    }),
  renameEdition: (seriesId: number, editionId: number, body: { name?: string; note?: string }) =>
    request<Edition>(`/api/series/${seriesId}/editions/${editionId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  bindSlot: (seriesId: number, bookIds: number[]) =>
    request<SeriesDetail>(`/api/series/${seriesId}/slots`, {
      method: "POST",
      body: JSON.stringify({ book_ids: bookIds }),
    }),
  unbindSlot: (seriesId: number, bookIds: number[]) =>
    request<SeriesDetail>(`/api/series/${seriesId}/slots/unbind`, {
      method: "POST",
      body: JSON.stringify({ book_ids: bookIds }),
    }),
  importSeries: (id: number, body: { root_id: number; download_missing?: boolean }) =>
    request<ImportResult>(`/api/series/${id}/import`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  similarSeries: (id: number) => request<MergeCandidate[]>(`/api/series/${id}/similar`),
  syncCovers: (id: number) =>
    request<SyncCoversResult>(`/api/series/${id}/covers`, { method: "POST" }),
  renameSeries: (id: number, title: string) =>
    request<SeriesRenamed>(`/api/series/${id}/title`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  setOrigin: (id: number, body: { origin_region: string; origin_country?: string | null }) =>
    request<Series>(`/api/series/${id}/origin`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  attachCover: (id: number, body: { source_id: number; ref: string }) =>
    request<Series>(`/api/series/${id}/cover`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  setCoverPage: (id: number, pageIndex: number | null) =>
    request<Series>(`/api/series/${id}/cover-page`, {
      method: "PATCH",
      body: JSON.stringify({ page_index: pageIndex }),
    }),

  continueReading: (seriesId: number) =>
    request<ContinueInfo>(`/api/series/${seriesId}/continue`),
  markReadBefore: (seriesId: number, bookId: number) =>
    request<{ marked: number }>(`/api/series/${seriesId}/mark-read-before/${bookId}`, {
      method: "POST",
    }),

  wikiSearch: (q: string, lang = "nl") =>
    request<WikiHit[]>(`/api/wiki/search${queryString({ q, lang })}`),
  wikiArticleUrl: (key: string, lang = "nl") =>
    `/api/wiki/article.epub${queryString({ key, lang })}`,

  book: (id: number) => request<BookDetail>(`/api/books/${id}`),
  nextChapter: (id: number) => request<NextChapter>(`/api/books/${id}/next`),

  progress: () => request<Progress[]>("/api/progress"),
  setProgress: (body: {
    book_id: number;
    position?: Record<string, unknown>;
    percent: number;
    finished?: boolean;
    device?: string;
  }) => request<Progress>("/api/progress", { method: "PUT", body: JSON.stringify(body) }),

  tabs: () => request<Tab[]>("/api/tabs"),
  createTab: (body: TabIn) =>
    request<Tab>("/api/tabs", { method: "POST", body: JSON.stringify(body) }),
  updateTab: (id: number, body: TabIn) =>
    request<Tab>(`/api/tabs/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteTab: (id: number) => request<void>(`/api/tabs/${id}`, { method: "DELETE" }),
  tabSeries: (id: number, query: { search?: string; offset?: number; limit?: number } = {}) =>
    request<Paginated<Series>>(`/api/tabs/${id}/series${queryString({ ...query })}`),

  collections: () => request<Collection[]>("/api/collections"),
  collection: (id: number) => request<Collection>(`/api/collections/${id}`),
  createCollection: (body: CollectionIn) =>
    request<Collection>("/api/collections", { method: "POST", body: JSON.stringify(body) }),
  updateCollection: (id: number, body: CollectionIn) =>
    request<Collection>(`/api/collections/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteCollection: (id: number) =>
    request<void>(`/api/collections/${id}`, { method: "DELETE" }),
  collectionSeries: (id: number, query: { offset?: number; limit?: number } = {}) =>
    request<Paginated<Series>>(`/api/collections/${id}/series${queryString({ ...query })}`),

  sourceTypes: () => request<string[]>("/api/sources/types"),
  sources: () => request<SourceRow[]>("/api/sources"),
  addSource: (body: { type: string; name: string }) =>
    request<SourceRow>("/api/sources", { method: "POST", body: JSON.stringify(body) }),
  deleteSource: (id: number) => request<void>(`/api/sources/${id}`, { method: "DELETE" }),
  searchSource: (id: number, q: string, limit = 20) =>
    request<SearchHit[]>(`/api/sources/${id}/search${queryString({ q, limit })}`),
  subscribe: (
    sourceId: number,
    body: {
      ref: string;
      policy?: SubscriptionPolicy;
      readahead_n?: number;
      ttl_days?: number;
      language?: string;
    },
  ) =>
    request<SubscribeResult>(`/api/sources/${sourceId}/subscribe`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  subscriptions: () => request<SubscriptionRow[]>("/api/sources/subscriptions/all"),
  // Een lijst: een serie kan meerdere abonnementen hebben (een vertaling naast
  // het origineel), en de vertaalgroep kies je per abonnement.
  subscriptionsForSeries: (seriesId: number) =>
    request<SubscriptionRow[]>(`/api/sources/subscriptions/by-series/${seriesId}`),
  updateSubscription: (
    id: number,
    body: {
      preferred_group_id?: string | null;
      policy?: SubscriptionPolicy;
      readahead_n?: number;
      ttl_days?: number;
    },
  ) =>
    request<SubscribeResult>(`/api/sources/subscriptions/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  refreshSubscription: (id: number) =>
    request<SubscribeResult>(`/api/sources/subscriptions/${id}/refresh`, { method: "POST" }),
  unsubscribe: (id: number) =>
    request<void>(`/api/sources/subscriptions/${id}`, { method: "DELETE" }),
  downloadChapter: (bookId: number, body: { temporary?: boolean; ttl_days?: number } = {}) =>
    request<{ book_id: number; has_file: boolean; expires_at: string | null }>(
      `/api/sources/books/${bookId}/download`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  runSources: () => request<RunReport>("/api/sources/run", { method: "POST" }),

  trackers: () => request<TrackerAccountRow[]>("/api/trackers"),
  addTracker: (body: { provider: string; client_id?: string; client_secret?: string }) =>
    request<TrackerAccountRow>("/api/trackers", { method: "POST", body: JSON.stringify(body) }),
  updateTracker: (id: number, body: { enabled?: boolean; dry_run?: boolean }) =>
    request<TrackerAccountRow>(`/api/trackers/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteTracker: (id: number) => request<void>(`/api/trackers/${id}`, { method: "DELETE" }),
  malAuthorizeUrl: (id: number) =>
    request<MalAuthorize>(`/api/trackers/${id}/mal/authorize-url`),
  malCallback: (id: number, code: string) =>
    request<TrackerAccountRow>(`/api/trackers/${id}/mal/callback`, {
      method: "POST",
      body: JSON.stringify({ code }),
    }),
  runTracker: (id: number) => request<PushReport>(`/api/trackers/${id}/run`, { method: "POST" }),
  goodreadsExportUrl: () => "/api/trackers/goodreads/export.csv",
  intakeScan: () => request<IntakeScan>("/api/intake"),
  intakeImport: (body: { paths: string[]; root_id: number; folder?: string | null }) =>
    request<IntakeImportResult>("/api/intake/import", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  intakeUpload: (file: File) => {
    // Bewust FormData en geen JSON: een boek van een paar honderd MB als
    // base64 door een JSON-body duwen kost geheugen en tijd die nergens toe
    // dienen. De browser zet zelf de juiste Content-Type met boundary.
    const body = new FormData();
    body.append("file", file);
    return request<IntakeUpload>("/api/intake/upload", { method: "POST", body });
  },
  intakeFetch: (url: string, folder?: string) =>
    request<IntakeFetch>("/api/intake/fetch", {
      method: "POST",
      body: JSON.stringify({ url, folder: folder || null }),
    }),
  setReadState: (bookId: number, finished: boolean) =>
    request<ReadState>(`/api/books/${bookId}/read-state`, {
      method: "POST",
      body: JSON.stringify({ finished }),
    }),
  mergeSuggestions: () => request<MergeSuggestion[]>("/api/series/merge/suggestions"),
  mergeSeries: (keepId: number, absorbId: number) =>
    request<SeriesDetail>(`/api/series/${keepId}/merge`, {
      method: "POST",
      body: JSON.stringify({ absorb_id: absorbId }),
    }),
  malLink: (accountId: number, seriesId: number, malId: string) =>
    request<MalListItem>(`/api/trackers/${accountId}/mal/link`, {
      method: "POST",
      body: JSON.stringify({ series_id: seriesId, mal_id: malId }),
    }),
  malImportProgress: (accountId: number, seriesId?: number) =>
    request<MalImportProgress>(`/api/trackers/${accountId}/mal/import-progress`, {
      method: "POST",
      body: JSON.stringify({ series_id: seriesId ?? null }),
    }),
  malList: (accountId: number, status?: string) =>
    request<MalListItem[]>(`/api/trackers/${accountId}/mal/list${queryString({ status })}`),
  shelves: (provider = "goodreads") =>
    request<Shelves>(`/api/trackers/shelves${queryString({ provider })}`),
  goodreadsStatus: () => request<GoodreadsStatus>("/api/trackers/goodreads/status"),
  goodreadsInstallBrowser: () =>
    request<GoodreadsStatus>("/api/trackers/goodreads/install-browser", { method: "POST" }),
  goodreadsLogin: (email: string, password: string) =>
    request<GoodreadsStatus>("/api/trackers/goodreads/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  goodreadsLogout: () =>
    request<void>("/api/trackers/goodreads/login", { method: "DELETE" }),
  goodreadsSync: () =>
    request<GoodreadsSyncResult>("/api/trackers/goodreads/sync", { method: "POST" }),

  pageTranslation: (bookId: number, index: number, lang?: string) =>
    request<PageTranslation>(
      `/api/books/${bookId}/pages/${index}/translation${queryString({ lang })}`,
    ),
  makePageTranslation: (bookId: number, index: number, lang?: string) =>
    request<PageTranslation>(
      `/api/books/${bookId}/pages/${index}/translation${queryString({ lang })}`,
      { method: "POST" },
    ),
  translateBook: (bookId: number, body: { lang?: string; from_page?: number } = {}) =>
    request<TranslateBookResult>(`/api/books/${bookId}/translate`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  translationStatus: (bookId: number, lang?: string) =>
    request<TranslationStatus>(
      `/api/books/${bookId}/translation-status${queryString({ lang })}`,
    ),
  translateMode: () => request<TranslateModeInfo>("/api/translate/mode"),
  setTranslateMode: (mode: TranslateMode) =>
    request<TranslateModeInfo>("/api/translate/mode", {
      method: "PUT",
      body: JSON.stringify({ mode }),
    }),
  translatePageFully: (
    bookId: number,
    index: number,
    body: { mode: TranslateMode; lang?: string; force?: boolean },
  ) =>
    request<PageTranslation>(`/api/books/${bookId}/pages/${index}/full`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

/** URL's naar beeld. Geen fetch: de browser laadt en cachet deze zelf. */
export const imageUrl = {
  cover: (bookId: number, profile = "cover") =>
    `/api/books/${bookId}/cover${queryString({ profile })}`,
  /** De officiële omslag van een bron — alleen zinvol als has_cover_url. */
  seriesCover: (seriesId: number, profile = "cover") =>
    `/api/series/${seriesId}/cover${queryString({ profile })}`,
  page: (
    bookId: number,
    index: number,
    profile: string,
    adjust: { crop?: boolean; contrast?: number } = {},
  ) =>
    `/api/books/${bookId}/pages/${index}${queryString({
      profile,
      // Alleen meesturen als ze afwijken: anders krijgt elke pagina een
      // andere URL dan de gecachete standaardversie.
      crop: adjust.crop ? true : undefined,
      contrast: adjust.contrast && adjust.contrast !== 100 ? adjust.contrast : undefined,
    })}`,
  file: (bookId: number) => `/api/books/${bookId}/file`,
  /** De hele pagina hertekend mét vertaling (beeldstanden, M8). */
  fullTranslation: (bookId: number, index: number, lang?: string) =>
    `/api/books/${bookId}/pages/${index}/full${queryString({ lang })}`,
};
