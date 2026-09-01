/**
 * Typed client for `/api/internal/alert-rules*` and `/alert-templates*`
 * (docs/API.md §5, roadmap slices 038/041). Shapes mirror the payloads
 * `backend/src/flightsite/api/alert_rules.py` builds — see its
 * `_rule_payload` / `_template_payload`.
 *
 * The condition document is the part worth reading carefully. The backend
 * validates it with the very model the *stored* document is parsed with
 * (`flightsite.alerts.model.RuleConditions`), so a document this client sends
 * and one it reads back are the same shape, and a rule the API accepts is by
 * construction one the engine can evaluate. That is what makes slice 041's
 * round-trip property ("rules created in the UI evaluate identically to
 * API-created rules") hold without this file re-deriving any of it.
 *
 * Optional members are written `?: T | null` rather than `?: T` because the
 * backend dumps with `exclude_none=True`: an unset condition is an *absent*
 * key on the way out, and either an absent key or an explicit `null` is
 * accepted on the way in.
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type { AlertSeverity } from "@/lib/api/sightings";

/** The mission categories a classification condition may require, spelled
 * exactly as `flightsite.classification.vocabulary.MissionCategory` does.
 * `unknown` is deliberately absent: the backend refuses it, because a rule
 * matching every airframe no metadata source has heard of would be a rule
 * about FlightSite's ignorance rather than about aircraft. */
export type AlertMissionCategory =
  | "commercial_passenger"
  | "cargo"
  | "general_aviation"
  | "business_aviation"
  | "military"
  | "government"
  | "law_enforcement"
  | "medical"
  | "firefighting"
  | "training"
  | "helicopter";

/** SPEC §39 classification requirements. The three flags are requirements,
 * never negations — `military: true` means "must be military" and
 * `military: false` means "do not care". There is no way to say "must not
 * be", because that is a boolean `NOT` and SPEC §43 limits v1 to `AND` over
 * positive conditions. */
export interface AlertClassificationCondition {
  military: boolean;
  government: boolean;
  law_enforcement: boolean;
  mission?: AlertMissionCategory | null;
}

/** A receiver-relative rarity threshold (SPEC §44). `max_sightings` is
 * inclusive, so `1` is exactly "never seen here before". */
export interface AlertRarityCondition {
  max_sightings: number;
}

/**
 * One rule's `AND`-combined condition set (docs/DATA_MODEL.md §4.2).
 *
 * Flat, with every member optional, because SPEC §43 gives v1 no nested
 * boolean trees: every condition present must hold. `version` is the
 * document's forward door and this build reads and writes `1` only.
 */
export interface AlertRuleConditions {
  version: 1;
  classification?: AlertClassificationCondition | null;
  /** Exact match on the resolved ICAO type designator, case-insensitively. */
  type_code?: string | null;
  /** Case-insensitive *substring* of the resolved model name — the stored
   * value is registry prose ("Boeing C-17A Globemaster III"), so a user
   * means "Globemaster", not that string character for character. */
  model?: string | null;
  /** Membership of one specific watchlist, by id. */
  watchlist_id?: number | null;
  /** Membership of *any* watchlist. Exists beside `watchlist_id` because a
   * template instantiated at first run has no watchlist to name yet. */
  watchlist_any?: boolean;
  rare_aircraft?: AlertRarityCondition | null;
  rare_type?: AlertRarityCondition | null;
  max_distance_nm?: number | null;
  min_distance_nm?: number | null;
  max_alt_ft?: number | null;
  min_alt_ft?: number | null;
  /** Whether the rule also applies to aircraft the decoder reports on the
   * ground. `false` — the default — is SPEC §40's "excluded from relevant
   * alerts". Not itself a condition: a rule that says only this matches
   * nothing, and the backend refuses it. */
  applies_on_ground?: boolean;
}

export interface AlertRule {
  id: number;
  name: string;
  description: string | null;
  severity: AlertSeverity;
  enabled: boolean;
  /** `null` for a user-written rule; the shipped template's key for one that
   * came from the gallery or from first-run instantiation. Provenance is not
   * replaceable — tuning a shipped rule does not make it stop having been
   * shipped. */
  template_key: string | null;
  conditions: AlertRuleConditions;
  /** The rule stated in prose, one phrase per condition, composed by the
   * backend's `RuleConditions.describe()`. Rendered as-is so every client
   * says the same thing about a rule rather than re-implementing it. */
  describes: string[];
  created_at: string;
  updated_at: string;
}

/** One shipped template (SPEC §45). `builtin` is the field that matters: a
 * built-in template describes behaviour that is already on and cannot be
 * turned off (SPEC §47's emergency squawks), so its `conditions` are `null`
 * because there is no rule to create. */
export interface AlertTemplate {
  key: string;
  name: string;
  description: string;
  severity: AlertSeverity;
  builtin: boolean;
  conditions: AlertRuleConditions | null;
}

export interface AlertRulesListResponse {
  rules: AlertRule[];
}

export interface AlertTemplatesListResponse {
  templates: AlertTemplate[];
}

/** `POST` and `PUT` body. One shape for both, because `PUT` is a full
 * replace rather than a patch — a partial update of an `AND` condition set
 * is ambiguous about whether an omitted condition was meant to be removed. */
export interface AlertRuleWriteInput {
  name: string;
  description: string | null;
  severity: AlertSeverity;
  conditions: AlertRuleConditions;
  enabled: boolean;
}

const RULES_PATH = "/api/internal/alert-rules";
const TEMPLATES_PATH = "/api/internal/alert-templates";

const JSON_HEADERS = { "Content-Type": "application/json" };

export function getAlertRules(): Promise<AlertRulesListResponse> {
  return apiFetch<AlertRulesListResponse>(RULES_PATH);
}

export function getAlertTemplates(): Promise<AlertTemplatesListResponse> {
  return apiFetch<AlertTemplatesListResponse>(TEMPLATES_PATH);
}

export function createAlertRule(input: AlertRuleWriteInput): Promise<AlertRule> {
  return apiFetch<AlertRule>(RULES_PATH, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(input),
  });
}

export function updateAlertRule(
  ruleId: number,
  input: AlertRuleWriteInput,
): Promise<AlertRule> {
  return apiFetch<AlertRule>(`${RULES_PATH}/${ruleId}`, {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify(input),
  });
}

export function deleteAlertRule(ruleId: number): Promise<void> {
  return apiFetch<void>(`${RULES_PATH}/${ruleId}`, { method: "DELETE" });
}

/** Turns one shipped template into a rule carrying its `template_key`. The
 * body is empty on purpose: the conditions and severity come from the
 * backend's catalogue, never from here, so provenance stays a statement the
 * server makes rather than a claim a client attaches. */
export function instantiateAlertTemplate(key: string): Promise<AlertRule> {
  return apiFetch<AlertRule>(`${TEMPLATES_PATH}/${key}/rules`, {
    method: "POST",
  });
}

/** Query key for the rule list. */
export const alertRulesQueryKey = ["alert-rules"] as const;

/** Query key for the shipped-template catalogue. */
export const alertTemplatesQueryKey = ["alert-templates"] as const;

export function useAlertRulesQuery(): UseQueryResult<AlertRulesListResponse> {
  return useQuery({ queryKey: alertRulesQueryKey, queryFn: getAlertRules });
}

/** The shipped catalogue is static data compiled into the backend — it
 * cannot change while the app is running — so it is never refetched for
 * staleness. What *does* change is which templates have been instantiated,
 * and that is read from the rule list's `template_key`, not from here. */
export function useAlertTemplatesQuery(): UseQueryResult<AlertTemplatesListResponse> {
  return useQuery({
    queryKey: alertTemplatesQueryKey,
    queryFn: getAlertTemplates,
    staleTime: Infinity,
  });
}

/** Every rule mutation invalidates the rule list, so no consumer has to
 * remember to refetch: the list is what the rules tab renders *and* what the
 * template gallery reads to decide which templates are already instantiated. */
function invalidateAlertRules(
  queryClient: ReturnType<typeof useQueryClient>,
): void {
  void queryClient.invalidateQueries({ queryKey: alertRulesQueryKey });
}

export function useCreateAlertRuleMutation(): UseMutationResult<
  AlertRule,
  Error,
  AlertRuleWriteInput
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createAlertRule,
    onSuccess: () => {
      invalidateAlertRules(queryClient);
    },
  });
}

export function useUpdateAlertRuleMutation(): UseMutationResult<
  AlertRule,
  Error,
  { ruleId: number; input: AlertRuleWriteInput }
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ ruleId, input }) => updateAlertRule(ruleId, input),
    onSuccess: () => {
      invalidateAlertRules(queryClient);
    },
  });
}

export function useDeleteAlertRuleMutation(): UseMutationResult<
  void,
  Error,
  number
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteAlertRule,
    onSuccess: () => {
      invalidateAlertRules(queryClient);
    },
  });
}

export function useInstantiateAlertTemplateMutation(): UseMutationResult<
  AlertRule,
  Error,
  string
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: instantiateAlertTemplate,
    onSuccess: () => {
      invalidateAlertRules(queryClient);
    },
  });
}
