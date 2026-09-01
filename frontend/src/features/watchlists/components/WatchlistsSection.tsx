import { CreateWatchlistForm } from "@/features/watchlists/components/CreateWatchlistForm";
import { WatchlistCard } from "@/features/watchlists/components/WatchlistCard";
import { useLiveWatchlistCounts } from "@/features/watchlists/lib/liveMatchCounts";
import { useWatchlistsQuery } from "@/lib/api/watchlists";

/**
 * Watchlist management (SPEC §42, roadmap slice 037): create/rename/delete
 * watchlists, add/remove kind-specific entries, and see how many live
 * aircraft each one currently flags. Rendered inside the Alerts page's
 * "Watchlists" tab (`@/pages/AlertsPage`); slice 041 adds an alert-rules
 * area alongside it.
 */
export function WatchlistsSection() {
  const watchlistsQuery = useWatchlistsQuery();
  const liveMatchCounts = useLiveWatchlistCounts();

  return (
    <div className="flex flex-col gap-4">
      <CreateWatchlistForm />

      {watchlistsQuery.isPending && (
        <p className="text-sm text-muted-foreground">Loading watchlists…</p>
      )}

      {watchlistsQuery.isError && (
        <p role="alert" className="text-sm text-destructive">
          Could not load watchlists
          {watchlistsQuery.error instanceof Error
            ? `: ${watchlistsQuery.error.message}`
            : "."}
        </p>
      )}

      {watchlistsQuery.data && watchlistsQuery.data.watchlists.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No watchlists yet. Create one above to start flagging aircraft on the
          live map.
        </p>
      )}

      {watchlistsQuery.data && watchlistsQuery.data.watchlists.length > 0 && (
        <ul className="flex flex-col gap-3">
          {watchlistsQuery.data.watchlists.map((watchlist) => (
            <li key={watchlist.id}>
              <WatchlistCard
                watchlist={watchlist}
                liveMatchCount={liveMatchCounts[watchlist.name] ?? 0}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
