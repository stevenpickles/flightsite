/**
 * Component-level axe checks (roadmap slice 048, SPEC §80).
 *
 * The CI-gated sweep over the main flows lives in the E2E suite
 * (`e2e/tests/05-accessibility.spec.ts`), which is where contrast can
 * actually be measured — jsdom has no layout or real cascade, so axe skips
 * the color rules here. This file covers the complement: component states
 * that are awkward to drive from a full-stack E2E run (an open modal, a
 * save bar mid-error) and the specific components slice 048 changed, so an
 * ARIA or labelling regression fails fast in the unit suite rather than
 * waiting on a Docker stack.
 */
import { render } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import { PresetSelector } from "@/features/analytics/components/PresetSelector";
import { BasemapSwitcher } from "@/features/map/BasemapSwitcher";
import { ClosureReasonTooltip } from "@/features/sightings/components/ClosureReasonTooltip";
import { ConfirmDangerDialog } from "@/features/settings/components/ConfirmDangerDialog";
import { SectionSaveBar } from "@/features/settings/components/SectionSaveBar";

/** axe's own async work plus jsdom is slower than the 5s default. */
const AXE_TIMEOUT = 20_000;

/**
 * Asserts a clean axe run, reporting the rule id and the offending selectors
 * on failure.
 *
 * Deliberately not `vitest-axe`'s `toHaveNoViolations` matcher: that ships a
 * `declare global { namespace Vi }` augmentation for an older Vitest
 * assertion interface, which this project's Vitest 4 no longer resolves
 * (`tsc` rejects the matcher as unknown). Comparing the violation list
 * directly needs no type augmentation and prints the same detail.
 */
async function expectNoViolations(container: HTMLElement): Promise<void> {
  const results = await axe(container);
  const summary = results.violations.map((violation) => ({
    id: violation.id,
    help: violation.help,
    nodes: violation.nodes.map((node) => node.target.join(" ")),
  }));
  expect(summary).toEqual([]);
}

describe("component accessibility", () => {
  it(
    "the analytics preset selector is a well-formed radiogroup",
    async () => {
      const { container } = render(
        <PresetSelector preset="7d" onChange={() => {}} />,
      );
      await expectNoViolations(container);
    },
    AXE_TIMEOUT,
  );

  it(
    "the basemap switcher is a well-formed radiogroup",
    async () => {
      const { container } = render(<BasemapSwitcher />);
      await expectNoViolations(container);
    },
    AXE_TIMEOUT,
  );

  it(
    "the settings save bar is accessible in its error state",
    async () => {
      const { container } = render(
        <SectionSaveBar
          isDirty
          isPending={false}
          justSaved={false}
          errorMessage="Could not save the section."
          hasBlockingError={false}
          onSave={() => {}}
        />,
      );
      await expectNoViolations(container);
    },
    AXE_TIMEOUT,
  );

  it(
    "the settings save bar is accessible in its saved state",
    async () => {
      const { container } = render(
        <SectionSaveBar
          isDirty={false}
          isPending={false}
          justSaved
          errorMessage={null}
          hasBlockingError={false}
          onSave={() => {}}
        />,
      );
      await expectNoViolations(container);
    },
    AXE_TIMEOUT,
  );

  it(
    "the open danger-confirmation dialog is accessible",
    async () => {
      const { container } = render(
        <ConfirmDangerDialog
          open
          onClose={() => {}}
          title="Clear Metadata Cache"
          confirmPhrase="CLEAR METADATA"
          confirmLabel="Clear Metadata Cache"
          pendingLabel="Clearing…"
          isPending={false}
          onConfirm={() => {}}
        >
          <p>This removes every cached metadata row.</p>
        </ConfirmDangerDialog>,
      );
      await expectNoViolations(container);
    },
    AXE_TIMEOUT,
  );

  it(
    "the closure-reason tooltip trigger is a properly-roled control",
    async () => {
      const { container } = render(
        <TooltipProvider>
          <ClosureReasonTooltip reason="gap_timeout" />
        </TooltipProvider>,
      );
      await expectNoViolations(container);
    },
    AXE_TIMEOUT,
  );
});
