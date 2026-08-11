import type {
  BookDetail,
  Collection,
  CollectionIn,
  Health,
  ImageProfile,
  LibraryRoot,
  Paginated,
  Progress,
  ScanResult,
  Series,
  SeriesDetail,
  SeriesQuery,
  Tab,
  TabIn,
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
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
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
  seriesDetail: (id: number) => request<SeriesDetail>(`/api/series/${id}`),
  setOrigin: (id: number, body: { origin_region: string; origin_country?: string | null }) =>
    request<Series>(`/api/series/${id}/origin`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  book: (id: number) => request<BookDetail>(`/api/books/${id}`),

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
};

/** URL's naar beeld. Geen fetch: de browser laadt en cachet deze zelf. */
export const imageUrl = {
  cover: (bookId: number, profile = "cover") =>
    `/api/books/${bookId}/cover${queryString({ profile })}`,
  page: (bookId: number, index: number, profile: string) =>
    `/api/books/${bookId}/pages/${index}${queryString({ profile })}`,
  file: (bookId: number) => `/api/books/${bookId}/file`,
};
