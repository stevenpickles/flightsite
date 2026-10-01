import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import type { UnitSystem } from "@/lib/api/config";
import {
  useReceiverCoverageQuery,
  type ReceiverCoverage,
  type ReceiverCoverageBand,
  type ReceiverCoverageBandKey,
  type ReceiverCoverageWindow,
} from "@/lib/api/receiverStats";
import { EChart } from "@/features/analytics/components/EChart";
import type { ChartTheme } from "@/features/analytics/lib/chartTheme";
import { ChartCard } from "@/features/receiver/components/ChartCard";
import {
  COVERAGE_WINDOWS,
  COVERAGE_WINDOW_LABEL,
  bandButtonLabel,
  bandPhrase,
  buildCoverageChart,
  findingSentence,
  formatHeight,
  type CoverageSectorPoint,
} from "@/features/receiver/lib/coverage";
import {
  distanceAxisValue,
  distanceUnitLabel,
  formatCount,
  formatDistance,
} from "@/features/receiver/lib/format";

const TITLE_ID = "receiver-chart-coverage";
const TITLE = "Coverage by altitude";
const POLAR_HEIGHT = 360;
/** The band a first visit shows: the high band is the one whose horizon is
 * furthest out, so it is where an obstruction shows up most plainly. */
const DEFAULT_BAND: ReceiverCoverageBandKey = "above_25k";
const DEFAULT_WINDOW: ReceiverCoverageWindow = "30d";

function hasAnyData(coverage: ReceiverCoverage): boolean {
  return coverage.bands.some((band) =>
    band.sectors.some((sector) => sector.max_range_nm !== null),
  );
}

/**
 * Roadmap slice 087's coverage analysis (issue #230): how far the receiver
 * hears in each direction at each altitude band, against the radio horizon
 * an antenna of the configured height *could* reach, and the sectors that
 * fall well short of it.
 *
 * A Receiver-page chart, not a map layer — SPEC §33 keeps map overlays to
 * airports, airspace and range rings.
 *
 * Degrades in the open: an endpoint that fails (or does not exist, as in a
 * recorded fixture made before this slice) is the card's error state with a
 * Retry; an install with no banded data yet says it is still learning; an
 * unset antenna height still draws what was heard, and says what to set to
 * see the horizon.
 */
export function CoverageChart({ units }: { units: UnitSystem }) {
  const [timeWindow, setTimeWindow] =
    useState<ReceiverCoverageWindow>(DEFAULT_WINDOW);
  const [bandKey, setBandKey] = useState<ReceiverCoverageBandKey>(DEFAULT_BAND);
  const { data, isLoading, isError, refetch } =
    useReceiverCoverageQuery(timeWindow);

  const band: ReceiverCoverageBand | undefined = data?.bands.find(
    (candidate) => candidate.key === bandKey,
  );
  const unitLabel = distanceUnitLabel(units);

  const sectors: CoverageSectorPoint[] = useMemo(
    () =>
      (band?.sectors ?? []).map((sector) => ({
        bearing_deg: sector.bearing_deg,
        value:
          sector.max_range_nm === null
            ? null
            : distanceAxisValue(sector.max_range_nm, units),
      })),
    [band?.sectors, units],
  );
  const horizonNm = band?.horizon_nm ?? null;
  const horizon =
    horizonNm === null ? null : distanceAxisValue(horizonNm, units);
  const bandLabel = band === undefined ? "" : bandButtonLabel(band, units);

  const chart = useMemo(
    () =>
      buildCoverageChart({
        sectors,
        horizon,
        bandLabel,
        unitLabel,
        formatValue: (value) => `${value} ${unitLabel}`,
      }),
    [sectors, horizon, bandLabel, unitLabel],
  );
  const buildOption = useCallback(
    (theme: ChartTheme) => chart.buildOption(theme),
    [chart],
  );

  const findings = (data?.findings ?? []).filter(
    (finding) => finding.band === bandKey,
  );
  const otherBandFindings = (data?.findings.length ?? 0) - findings.length;

  return (
    <ChartCard
      titleId={TITLE_ID}
      title={TITLE}
      isLoading={isLoading}
      error={
        isError
          ? "Coverage analysis is unavailable right now. The other Receiver charts are unaffected."
          : undefined
      }
      onRetry={() => void refetch()}
    >
      {data !== undefined && (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">
            The furthest aircraft heard in each 5° direction, by altitude,
            against the radio horizon — how far an aircraft at that altitude
            could be heard over the curve of the Earth.
          </p>

          <div className="flex flex-wrap items-center justify-between gap-2">
            <div
              role="group"
              aria-label="Altitude band"
              className="flex flex-wrap items-center gap-1"
            >
              {data.bands.map((candidate) => (
                <Button
                  key={candidate.key}
                  type="button"
                  size="sm"
                  variant={candidate.key === bandKey ? "default" : "outline"}
                  aria-pressed={candidate.key === bandKey}
                  onClick={() => setBandKey(candidate.key)}
                >
                  {bandButtonLabel(candidate, units)}
                </Button>
              ))}
            </div>
            <div
              role="group"
              aria-label="Coverage window"
              className="flex items-center gap-1"
            >
              {COVERAGE_WINDOWS.map((option) => (
                <Button
                  key={option}
                  type="button"
                  size="sm"
                  variant={option === timeWindow ? "default" : "outline"}
                  aria-pressed={option === timeWindow}
                  onClick={() => setTimeWindow(option)}
                >
                  {COVERAGE_WINDOW_LABEL[option]}
                </Button>
              ))}
            </div>
          </div>

          {data.antenna_height_ft === null && (
            <p role="note" className="text-sm text-muted-foreground">
              <Link
                to="/settings#settings-receiver"
                className="font-medium text-foreground underline underline-offset-2"
              >
                Set the antenna height in Settings
              </Link>{" "}
              to see the radio horizon.
            </p>
          )}

          {!hasAnyData(data) ? (
            <p
              role="status"
              className="py-8 text-center text-sm text-muted-foreground"
            >
              No coverage data yet. It builds up as aircraft with a known
              altitude are heard; a direction is only judged once it has{" "}
              {data.criteria.min_samples} samples on {data.criteria.min_days}{" "}
              different days.
            </p>
          ) : (
            <EChart
              buildOption={buildOption}
              ariaLabel={`${TITLE}, ${bandLabel}, polar chart`}
              summary={chart.summary}
              height={POLAR_HEIGHT}
            />
          )}

          {band !== undefined && horizonNm !== null && (
            <p className="text-xs text-muted-foreground">
              Radio horizon {formatDistance(horizonNm, units)} for an antenna{" "}
              {formatHeight(data.antenna_height_ft ?? 0, units)} above ground
              and aircraft at {formatHeight(band.reference_ft, units)} — a
              4/3-Earth estimate that ignores the site&apos;s own elevation.
            </p>
          )}

          {horizonNm !== null && band !== undefined && (
            <section aria-labelledby="receiver-coverage-findings">
              <h4
                id="receiver-coverage-findings"
                className="mb-1 text-sm font-medium"
              >
                Likely obstructions {bandPhrase(band, units)}
              </h4>
              {findings.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  None found. A direction is listed when it reaches under{" "}
                  {Math.round(data.criteria.share_below * 100)} % of the radio
                  horizon with at least {data.criteria.min_samples} samples on{" "}
                  {data.criteria.min_days} days.
                  {otherBandFindings > 0 &&
                    ` Other bands have ${otherBandFindings}.`}
                </p>
              ) : (
                <ul className="flex flex-col gap-1.5">
                  {findings.map((finding) => (
                    <li
                      key={`${finding.band}-${finding.start_deg}`}
                      className="text-sm"
                    >
                      <span>{findingSentence(finding, band, units)}</span>
                      <span className="block text-xs text-muted-foreground">
                        Furthest {formatDistance(finding.max_range_nm, units)}{" "}
                        of {formatDistance(finding.horizon_nm, units)} ·{" "}
                        {formatCount(finding.samples)} samples · at least{" "}
                        {finding.days} days
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}
        </div>
      )}
    </ChartCard>
  );
}
