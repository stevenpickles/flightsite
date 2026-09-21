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
import { latestDataUpdatedAt } from "@/features/analytics/lib/format";
import { formatReceiverLocalClock } from "@/features/receiver/lib/format";

const item = requireNavItem("/analytics");

function queryErrorMessage(
  isError: boolean,
  error: Error | null,
  fallback: string,
): string | undefined {
  if (!isError) {
    return undefined;
  }
  return error?.message ?? fallback;
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

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
        <TopAircraftCard
          window={topAircraftQuery.data?.window}
          rows={topAircraftQuery.data?.items ?? []}
          isLoading={topAircraftQuery.isPending}
          error={queryErrorMessage(
            topAircraftQuery.isError,
            topAircraftQuery.error,
            "Could not load top aircraft.",
          )}
          onRetry={() => void topAircraftQuery.refetch()}
        />

        <TopGroupCard
          title="Top types"
          ariaLabel="Top types by sightings, horizontal bar chart"
          emptyLabel="No types sighted in this window."
          window={topTypesQuery.data?.window}
          rows={topTypesQuery.data?.items ?? []}
          isLoading={topTypesQuery.isPending}
          error={queryErrorMessage(
            topTypesQuery.isError,
            topTypesQuery.error,
            "Could not load top types.",
          )}
          onRetry={() => void topTypesQuery.refetch()}
        />

        <TopGroupCard
          title="Top operators"
          ariaLabel="Top operators by sightings, horizontal bar chart"
          emptyLabel="No operators sighted in this window."
          window={topOperatorsQuery.data?.window}
          rows={topOperatorsQuery.data?.items ?? []}
          isLoading={topOperatorsQuery.isPending}
          error={queryErrorMessage(
            topOperatorsQuery.isError,
            topOperatorsQuery.error,
            "Could not load top operators.",
          )}
          onRetry={() => void topOperatorsQuery.refetch()}
        />

        <ClassificationActivityCard
          window={classificationQuery.data?.window}
          series={classificationQuery.data?.series ?? []}
          isLoading={classificationQuery.isPending}
          error={queryErrorMessage(
            classificationQuery.isError,
            classificationQuery.error,
            "Could not load classification activity.",
          )}
          onRetry={() => void classificationQuery.refetch()}
        />

        <DailyCountsCard
          window={dailyQuery.data?.window}
          items={dailyQuery.data?.items ?? []}
          isLoading={dailyQuery.isPending}
          error={queryErrorMessage(
            dailyQuery.isError,
            dailyQuery.error,
            "Could not load daily counts.",
          )}
          onRetry={() => void dailyQuery.refetch()}
        />

        <MaxDistanceCard
          window={dailyQuery.data?.window}
          items={dailyQuery.data?.items ?? []}
          units={units}
          isLoading={dailyQuery.isPending}
          error={queryErrorMessage(
            dailyQuery.isError,
            dailyQuery.error,
            "Could not load maximum detection distance.",
          )}
          onRetry={() => void dailyQuery.refetch()}
        />

        <ReceiverActivityCard
          window={dailyQuery.data?.window}
          items={dailyQuery.data?.items ?? []}
          isLoading={dailyQuery.isPending}
          error={queryErrorMessage(
            dailyQuery.isError,
            dailyQuery.error,
            "Could not load receiver activity.",
          )}
          onRetry={() => void dailyQuery.refetch()}
        />

        <NeverSeenBeforeCard
          window={dailyQuery.data?.window}
          items={dailyQuery.data?.items ?? []}
          isLoading={dailyQuery.isPending}
          error={queryErrorMessage(
            dailyQuery.isError,
            dailyQuery.error,
            "Could not load new-aircraft counts.",
          )}
          onRetry={() => void dailyQuery.refetch()}
        />

        <RarityListsCard
          window={rarityQuery.data?.window}
          neverSeenBefore={rarityQuery.data?.never_seen_before ?? 0}
          rareMaxSightings={rarityQuery.data?.rare_max_sightings ?? 0}
          rareAircraft={rarityQuery.data?.rare_aircraft ?? []}
          rareTypes={rarityQuery.data?.rare_types ?? []}
          isLoading={rarityQuery.isPending}
          error={queryErrorMessage(
            rarityQuery.isError,
            rarityQuery.error,
            "Could not load rarity data.",
          )}
          onRetry={() => void rarityQuery.refetch()}
        />
      </div>
    </div>
  );
}
