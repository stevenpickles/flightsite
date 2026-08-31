import type { WizardStepId } from "@/features/setup/constants";
import {
  validateAntennaHeight,
  validateHost,
  validateLatitude,
  validateLongitude,
  validatePath,
  validatePollInterval,
  validatePort,
  validateSiteName,
} from "@/features/setup/lib/validation";
import type { DecoderTestState, WizardDraft } from "@/features/setup/types";

/** Whether `stepId` may be advanced past, given the current draft (and,
 * for the decoder step, the last connection-test outcome). Centralized so
 * `WizardNav`'s Next/Finish button and each step's own inline errors agree
 * on the same rule. */
export function isStepValid(
  stepId: WizardStepId,
  draft: WizardDraft,
  decoderTestState: DecoderTestState,
): boolean {
  // No `default` branch: every `WizardStepId` member has an explicit case
  // below, so a forgotten step id is a compile error, not a silent
  // fallthrough.
  switch (stepId) {
    case "welcome":
      return validateSiteName(draft.siteName) === null;
    case "location":
      return (
        validateLatitude(draft.latitude) === null &&
        validateLongitude(draft.longitude) === null &&
        validateAntennaHeight(draft.antennaHeightFt) === null
      );
    case "decoder":
      return (
        validateHost(draft.receiverHost) === null &&
        validatePort(draft.receiverPort) === null &&
        validatePath(draft.receiverPath) === null &&
        validatePollInterval(draft.pollIntervalS) === null &&
        (decoderTestState.status === "success" || decoderTestState.skipped)
      );
    case "units-timezone":
      return draft.timezone.trim().length > 0;
    case "notifications":
    case "metadata":
    case "alerts":
    case "review":
      return true;
  }
}
