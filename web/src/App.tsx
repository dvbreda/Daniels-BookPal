import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { CollectionsPage } from "./pages/CollectionsPage";
import { CollectionViewPage } from "./pages/CollectionViewPage";
import { HomePage } from "./pages/HomePage";
import { ReaderPage } from "./pages/ReaderPage";
import { SeriesPage } from "./pages/SeriesPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SourcesPage } from "./pages/SourcesPage";
import { TabsPage } from "./pages/TabsPage";
import { TrackersPage } from "./pages/TrackersPage";
import { WikiReaderPage } from "./pages/WikiReaderPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // De bibliotheek verandert alleen door een scan, dus refetchen bij elke
      // tabwissel is verspilling — zeker over ZeroTier.
      refetchOnWindowFocus: false,
      staleTime: 30_000,
      retry: 1,
    },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<HomePage />} />
          {/* De oude bibliotheekpagina blijft bereikbaar voor wie hem bookmarkte. */}
          <Route path="/bibliotheek" element={<HomePage />} />
          <Route path="/serie/:id" element={<SeriesPage />} />
          <Route path="/lezen/:id" element={<ReaderPage />} />
          <Route path="/instellingen" element={<SettingsPage />} />
          <Route path="/tabs" element={<TabsPage />} />
          <Route path="/collecties" element={<CollectionsPage />} />
          <Route path="/collectie/:id" element={<CollectionViewPage />} />
          <Route path="/bronnen" element={<SourcesPage />} />
          <Route path="/trackers" element={<TrackersPage />} />
          <Route path="/wiki/:lang/:key" element={<WikiReaderPage />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
