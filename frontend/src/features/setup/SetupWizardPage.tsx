import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import {
  stepAt,
  WIZARD_STEPS,
  type WizardStepId,
} from "@/features/setup/constants";
import { canRequest } from "@/features/notifications/lib/permission";
import { useNotificationPermission } from "@/features/notifications/useNotificationPermission";
import { WizardNav } from "@/features/setup/components/WizardNav";
import { WizardProgress } from "@/features/setup/components/WizardProgress";
import { buildConfigPatch, draftFromConfig } from "@/features/setup/lib/draft";
import { applyServerConfigToMapStore } from "@/features/setup/lib/mapConfigSync";
import { isStepValid } from "@/features/setup/lib/stepValidation";
import { AlertsStep } from "@/features/setup/steps/AlertsStep";
import { DecoderStep } from "@/features/setup/steps/DecoderStep";
import { LocationStep } from "@/features/setup/steps/LocationStep";
import { MetadataStep } from "@/features/setup/steps/MetadataStep";
import { NotificationsStep } from "@/features/setup/steps/NotificationsStep";
import { ReviewStep } from "@/features/setup/steps/ReviewStep";
import { UnitsTimezoneStep } from "@/features/setup/steps/UnitsTimezoneStep";
import { WelcomeStep } from "@/features/setup/steps/WelcomeStep";
import {
  INITIAL_DECODER_TEST_STATE,
  type DecoderTestState,
  type WizardDraft,
} from "@/features/setup/types";
import { useConfigQuery, usePutConfigMutation } from "@/lib/api/config";

const LIVE_MAP_PATH = "/";
const AERODATABOX_KEY_PATH = "enrichment.aerodatabox_api_key";

/**
 * The full-screen setup wizard route (roadmap slice 018, SPEC §31). Lives
 * outside `AppShell`'s sidebar chrome — this is the only route rendered
 * without it (see `src/routes.tsx`). Prefills from the currently-effective
 * config either way, so the exact same component serves a fresh install
 * (server defaults) and a deliberate re-run from Settings (edit mode,
 * slice 019) against a live configuration.
 */
export function SetupWizardPage() {
  const configQuery = useConfigQuery();
  const putConfigMutation = usePutConfigMutation();
  const navigate = useNavigate();
  const notificationPermission = useNotificationPermission();

  const [draft, setDraft] = useState<WizardDraft | null>(null);
  // The config query can refetch in the background (e.g. React Query's
  // window-refocus handling) while the user is mid-wizard; the draft must
  // only ever be seeded once, or their in-progress edits would vanish.
  const initializedRef = useRef(false);

  useEffect(() => {
    if (!initializedRef.current && configQuery.data) {
      setDraft(draftFromConfig(configQuery.data));
      initializedRef.current = true;
    }
  }, [configQuery.data]);

  const [stepIndex, setStepIndex] = useState(0);
  const [furthestStepIndex, setFurthestStepIndex] = useState(0);
  const [decoderTestState, setDecoderTestState] = useState<DecoderTestState>(
    INITIAL_DECODER_TEST_STATE,
  );
  const [submitError, setSubmitError] = useState<string | null>(null);

  const currentStep = stepAt(stepIndex);
  const isFirstStep = stepIndex === 0;
  const isLastStep = stepIndex === WIZARD_STEPS.length - 1;
  const canProceed = draft
    ? isStepValid(currentStep.id, draft, decoderTestState)
    : false;

  function updateDraft(patch: Partial<WizardDraft>) {
    setDraft((current) => (current ? { ...current, ...patch } : current));
  }

  function goToStep(index: number) {
    setStepIndex(index);
    setSubmitError(null);
  }

  function handleStepSelect(id: WizardStepId) {
    const index = WIZARD_STEPS.findIndex((step) => step.id === id);
    if (index !== -1 && index <= furthestStepIndex) {
      goToStep(index);
    }
  }

  function handleBack() {
    if (!isFirstStep) {
      goToStep(stepIndex - 1);
    }
  }

  function handleNext() {
    if (!canProceed) {
      return;
    }
    const nextIndex = Math.min(stepIndex + 1, WIZARD_STEPS.length - 1);
    setFurthestStepIndex((current) => Math.max(current, nextIndex));
    goToStep(nextIndex);
  }

  function handleFinish() {
    if (!draft) {
      return;
    }
    setSubmitError(null);
    // The notifications step (SPEC §45's "do not silently enable every
    // possible notification") records a *preference*; this click is the opt-in
    // `docs/SECURITY.md` §5 requires before the browser may be asked, so the
    // ask happens here — synchronously, inside the handler, because the user
    // activation `requestPermission()` needs does not survive the awaited
    // config save below (`features/notifications/lib/permission.ts`). Its
    // answer is deliberately not awaited: finishing setup must not wait on a
    // browser prompt, and Settings shows and re-asks the permission later
    // whatever the user does with it now.
    if (
      draft.notifications.enabled &&
      canRequest(notificationPermission.permission)
    ) {
      void notificationPermission.request();
    }
    putConfigMutation.mutate(buildConfigPatch(draft), {
      onSuccess: (response) => {
        applyServerConfigToMapStore(response.config);
        navigate(LIVE_MAP_PATH, { replace: true });
      },
      onError: (error) => {
        setSubmitError(
          error instanceof Error
            ? error.message
            : "Could not save configuration.",
        );
      },
    });
  }

  if (!draft) {
    return (
      <WizardChrome>
        {configQuery.isError ? (
          <div className="flex flex-col items-center gap-3 text-center">
            <p className="text-sm text-destructive">
              Could not load the current configuration
              {configQuery.error instanceof Error
                ? `: ${configQuery.error.message}`
                : "."}
            </p>
            <button
              type="button"
              onClick={() => {
                void configQuery.refetch();
              }}
              className="text-sm font-medium text-accent underline"
            >
              Retry
            </button>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Loading configuration…
          </p>
        )}
      </WizardChrome>
    );
  }

  const hasStoredKey =
    configQuery.data?.secrets_set[AERODATABOX_KEY_PATH] ?? false;

  return (
    <div className="flex h-dvh w-full flex-col bg-background text-foreground">
      <header className="border-b border-border px-4 py-4 sm:px-8">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          FlightSite
        </p>
        <h1 className="text-lg font-semibold tracking-tight">Setup wizard</h1>
      </header>

      <WizardProgress
        currentStepId={currentStep.id}
        furthestStepIndex={furthestStepIndex}
        onStepSelect={handleStepSelect}
      />

      <main
        id="main-content"
        className="flex-1 overflow-y-auto px-4 py-6 sm:px-8"
      >
        {currentStep.id === "welcome" && (
          <WelcomeStep
            draft={draft}
            isFirstRun={configQuery.data?.first_run ?? true}
            onChange={updateDraft}
          />
        )}
        {currentStep.id === "location" && (
          <LocationStep draft={draft} onChange={updateDraft} />
        )}
        {currentStep.id === "decoder" && (
          <DecoderStep
            draft={draft}
            onChange={updateDraft}
            testState={decoderTestState}
            onTestStateChange={setDecoderTestState}
          />
        )}
        {currentStep.id === "units-timezone" && (
          <UnitsTimezoneStep draft={draft} onChange={updateDraft} />
        )}
        {currentStep.id === "notifications" && (
          <NotificationsStep draft={draft} onChange={updateDraft} />
        )}
        {currentStep.id === "metadata" && (
          <MetadataStep
            draft={draft}
            hasStoredKey={hasStoredKey}
            onChange={updateDraft}
          />
        )}
        {currentStep.id === "alerts" && (
          <AlertsStep draft={draft} onChange={updateDraft} />
        )}
        {currentStep.id === "review" && (
          <ReviewStep
            draft={draft}
            testState={decoderTestState}
            hasStoredKey={hasStoredKey}
            submitError={submitError}
          />
        )}
      </main>

      <WizardNav
        isFirstStep={isFirstStep}
        isLastStep={isLastStep}
        canProceed={canProceed}
        isSubmitting={putConfigMutation.isPending}
        onBack={handleBack}
        onNext={handleNext}
        onFinish={handleFinish}
      />
    </div>
  );
}

/** Minimal full-screen frame used only while the initial config load is in
 * flight or has failed — the real wizard chrome (header, progress, nav)
 * needs `draft` to exist first. */
function WizardChrome({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-dvh w-full flex-col items-center justify-center gap-4 bg-background px-4 text-foreground">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        FlightSite setup
      </p>
      {children}
    </div>
  );
}
