/**
 * The Analytics page (roadmap slice 032, SPEC §58): a preset time-range
 * selector plus a responsive grid of cards, each rendering one of the
 * `/api/v1/analytics/*` endpoints slice 031 shipped (`docs/API.md` §3.7).
 * Six of the seven endpoints feed a card here; `/analytics/summary` is a
 * separate today-at-a-glance widget (SPEC §59), out of this slice's scope.
 *
 * Every query is driven by the same URL-persisted preset
 * (`useAnalyticsPresetState`), so switching presets refetches every card at
 * once and the choice survives a reload or a shared link.
 */
import {
  ANALYTICS_REFETCH_INTERVAL_MS,
  useAnalyticsClassificationActivityQuery,
  useAnalyticsDailyQuery,
  useAnalyticsRarityQuery,
  useAnalyticsTopAircraftQuery,
  useAnalyticsTopOperatorsQuery,
  useAnalyticsTopTypesQuery,
} from "@/lib/api/analytics";
import { useReceiverQuery } from "@/lib/api/receiver";

import { requireNavItem } from "@/components/shell/nav-items";
import { AnalyticsErrorBanner } from "@/features/analytics/components/AnalyticsErrorBanner";
import { ClassificationActivityCard } from "@/features/analytics/components/cards/ClassificationActivityCard";
import { DailyCountsCard } from "@/features/analytics/components/cards/DailyCountsCard";
import { MaxDistanceCard } from "@/features/analytics/components/cards/MaxDistanceCard";
import { NeverSeenBeforeCard } from "@/features/analytics/components/cards/NeverSeenBeforeCard";
import { RarityListsCard } from "@/features/analytics/components/cards/RarityListsCard";
import { ReceiverActivityCard } from "@/features/analytics/components/cards/ReceiverActivityCard";
import { TopAircraftCard } from "@/features/analytics/components/cards/TopAircraftCard";
import { TopGroupCard } from "@/features/analytics/components/cards/TopGroupCard";
import { PresetSelector } from "@/features/analytics/components/PresetSelector";
import { useAnalyticsPresetState } from "@/features/analytics/hooks/useAnalyticsPresetState";
import {
  describeError,
  latestDataUpdatedAt,
} from "@/features/analytics/lib/format";
import { formatReceiverLocalClock } from "@/features/receiver/lib/format";

const item = requireNavItem("/analytics");

/** `/analytics/daily` alone backs four cards (Daily counts, Maximum
 * detection distance, Receiver activity, Never seen before) — R3-08's
 * "same error printed four times" case. */
const DAILY_ERROR_MESSAGE = "Could not load daily activity data.";
/** Shown on a card whose own failure is already explained, with a Retry, by
 * the page-level banner (R3-08) — never the banner's message duplicated
 * card-by-card, and never a raw backend string. */
const SUPPRESSED_CARD_MESSAGE = "Could not load — see notice above.";

interface AnalyticsQueryLike {
  isError: boolean;
  error: Error | null;
  refetch: () => unknown;
}

/** Error/detail/retry props for a card whose query is *not* shared with any
 * other card. Suppressed to a short pointer, with no Retry of its own, when
 * every analytics query has failed at once (R3-08's "nine identical 'Failed
 * to fetch' paragraphs" case) — the page banner already explains that and
 * retries everything. */
function independentCardProps(
  query: AnalyticsQueryLike,
  fallback: string,
  allFailed: boolean,
): { error?: string; errorDetail?: string; onRetry?: () => void } {
  if (!query.isError) {
    return {};
  }
  if (allFailed) {
    return { error: SUPPRESSED_CARD_MESSAGE };
  }
  const described = describeError(true, query.error, fallback);
  return {
    error: described?.message,
    errorDetail: described?.detail ?? undefined,
    onRetry: () => void query.refetch(),
  };
}

export function AnalyticsPage() {
  const { preset, setPreset } = useAnalyticsPresetState();
  const receiverQuery = useReceiverQuery();
  const units = receiverQuery.data?.units ?? "aviation";
  const timezone = receiverQuery.data?.timezone ?? "UTC";

  const dailyQuery = useAnalyticsDailyQuery({ preset });
  const classificationQuery = useAnalyticsClassificationActivityQuery({
    preset,
  });
  const topAircraftQuery = useAnalyticsTopAircraftQuery({ preset });
  const topTypesQuery = useAnalyticsTopTypesQuery({ preset });
  const topOperatorsQuery = useAnalyticsTopOperatorsQuery({ preset });
  const rarityQuery = useAnalyticsRarityQuery({ preset });

  // R3-08: every analytics query failing at once (an unreachable API) gets
  // one banner instead of nine identical "Failed to fetch" paragraphs.
  const allFailed =
    dailyQuery.isError &&
    classificationQuery.isError &&
    topAircraftQuery.isError &&
    topTypesQuery.isError &&
    topOperatorsQuery.isError &&
    rarityQuery.isError;

  function retryAll() {
    void dailyQuery.refetch();
    void classificationQuery.refetch();
    void topAircraftQuery.refetch();
    void topTypesQuery.refetch();
    void topOperatorsQuery.refetch();
    void rarityQuery.refetch();
  }

  // `/analytics/daily` alone backs four cards — R3-08 dedupes its failure
  // into one banner (below) with one Retry, rather than the same message
  // printed once per card; the four cards themselves fall back to a short
  // pointer rather than repeating it.
  const dailyCardError = dailyQuery.isError
    ? { error: SUPPRESSED_CARD_MESSAGE }
    : {};
  const dailyDescribed = allFailed
    ? undefined
    : describeError(dailyQuery.isError, dailyQuery.error, DAILY_ERROR_MESSAGE);

  // R3-06: one freshness caption for the whole page rather than per card —
  // every card either shares `dailyQuery` or refreshes on the same 60 s
  // interval, so the most recent of the six is what "the page" is as of.
  const dataAsOf = latestDataUpdatedAt([
    dailyQuery.dataUpdatedAt,
    classificationQuery.dataUpdatedAt,
    topAircraftQuery.dataUpdatedAt,
    topTypesQuery.dataUpdatedAt,
    topOperatorsQuery.dataUpdatedAt,
    rarityQuery.dataUpdatedAt,
  ]);

  return (
    <div className="flex h-full flex-col gap-4 px-4 py-6 md:px-8">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {item.label}
          </h1>
          <p className="text-sm text-muted-foreground">{item.description}</p>
          {dataAsOf !== undefined && (
            <p className="mt-1 text-xs text-muted-foreground">
              Data as of{" "}
              {formatReceiverLocalClock(
                new Date(dataAsOf).toISOString(),
                timezone,
              )}{" "}
              · refreshes every{" "}
              {Math.round(ANALYTICS_REFETCH_INTERVAL_MS / 1000)} s
            </p>
          )}
        </div>
        <PresetSelector preset={preset} onChange={setPreset} />
      </header>

      {allFailed ? (
        <AnalyticsErrorBanner
          message="FlightSite can't reach the API."
          onRetry={retryAll}
        />
      ) : (
        dailyDescribed !== undefined && (
          <AnalyticsErrorBanner
            message={dailyDescribed.message}
            detail={dailyDescribed.detail ?? undefined}
            onRetry={() => void dailyQuery.refetch()}
          />
        )
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
        <TopAircraftCard
          window={topAircraftQuery.data?.window}
          rows={topAircraftQuery.data?.items ?? []}
          isLoading={topAircraftQuery.isPending}
          {...independentCardProps(
            topAircraftQuery,
            "Could not load top aircraft.",
            allFailed,
          )}
        />

        <TopGroupCard
          title="Top types"
          ariaLabel="Top types by sightings, horizontal bar chart"
          emptyLabel="No types sighted in this window."
          window={topTypesQuery.data?.window}
          rows={topTypesQuery.data?.items ?? []}
          isLoading={topTypesQuery.isPending}
          {...independentCardProps(
            topTypesQuery,
            "Could not load top types.",
            allFailed,
          )}
        />

        <TopGroupCard
          title="Top operators"
          ariaLabel="Top operators by sightings, horizontal bar chart"
          emptyLabel="No operators sighted in this window."
          window={topOperatorsQuery.data?.window}
          rows={topOperatorsQuery.data?.items ?? []}
          isLoading={topOperatorsQuery.isPending}
          {...independentCardProps(
            topOperatorsQuery,
            "Could not load top operators.",
            allFailed,
          )}
        />

        <ClassificationActivityCard
          window={classificationQuery.data?.window}
          series={classificationQuery.data?.series ?? []}
          isLoading={classificationQuery.isPending}
          {...independentCardProps(
            classificationQuery,
            "Could not load classification activity.",
            allFailed,
          )}
        />

        <DailyCountsCard
          window={dailyQuery.data?.window}
          items={dailyQuery.data?.items ?? []}
          isLoading={dailyQuery.isPending}
          {...dailyCardError}
        />

        <MaxDistanceCard
          window={dailyQuery.data?.window}
          items={dailyQuery.data?.items ?? []}
          units={units}
          isLoading={dailyQuery.isPending}
          {...dailyCardError}
        />

        <ReceiverActivityCard
          window={dailyQuery.data?.window}
          items={dailyQuery.data?.items ?? []}
          isLoading={dailyQuery.isPending}
          {...dailyCardError}
        />

        <NeverSeenBeforeCard
          window={dailyQuery.data?.window}
          items={dailyQuery.data?.items ?? []}
          isLoading={dailyQuery.isPending}
          {...dailyCardError}
        />

        <RarityListsCard
          window={rarityQuery.data?.window}
          neverSeenBefore={rarityQuery.data?.never_seen_before ?? 0}
          rareMaxSightings={rarityQuery.data?.rare_max_sightings ?? 0}
          rareAircraft={rarityQuery.data?.rare_aircraft ?? []}
          rareTypes={rarityQuery.data?.rare_types ?? []}
          isLoading={rarityQuery.isPending}
          {...independentCardProps(
            rarityQuery,
            "Could not load rarity data.",
            allFailed,
          )}
        />
      </div>
    </div>
  );
}
