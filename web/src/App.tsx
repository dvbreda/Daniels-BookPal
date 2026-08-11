import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { LibraryPage } from "./pages/LibraryPage";
import { ReaderPage } from "./pages/ReaderPage";
import { SeriesPage } from "./pages/SeriesPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TabsPage } from "./pages/TabsPage";

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
          <Route path="/" element={<LibraryPage />} />
          <Route path="/serie/:id" element={<SeriesPage />} />
          <Route path="/lezen/:id" element={<ReaderPage />} />
          <Route path="/instellingen" element={<SettingsPage />} />
          <Route path="/tabs" element={<TabsPage />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
