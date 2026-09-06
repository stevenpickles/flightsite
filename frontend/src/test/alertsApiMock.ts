import { vi } from "vitest";

import type {
  AlertRule,
  AlertRuleConditions,
  AlertTemplate,
} from "@/lib/api/alertRules";
import type { AlertMatch } from "@/lib/api/alertMatches";
import type { Watchlist } from "@/lib/api/watchlists";
import { defaultFlightSiteConfig } from "@/test/configApiMock";

/** An `AlertRule`, defaulting to a user-written military rule — override
 * just the fields a test cares about. */
export function alertRule(overrides: Partial<AlertRule> = {}): AlertRule {
  const conditions: AlertRuleConditions = overrides.conditions ?? {
    version: 1,
    classification: {
      military: true,
      government: false,
      law_enforcement: false,
    },
  };
  return {
    id: 1,
    name: "Military aircraft",
    description: null,
    severity: "high",
    enabled: true,
    template_key: null,
    describes: describeConditions(conditions),
    created_at: "2026-08-31T00:00:00.000Z",
    updated_at: "2026-08-31T00:00:00.000Z",
    ...overrides,
    conditions,
  };
}

export function alertTemplate(
  overrides: Partial<AlertTemplate> = {},
): AlertTemplate {
  return {
    key: "military",
    name: "Military aircraft",
    description: "Any aircraft classified as military (SPEC §39).",
    severity: "high",
    builtin: false,
    conditions: {
      version: 1,
      classification: {
        military: true,
        government: false,
        law_enforcement: false,
      },
    },
    ...overrides,
  };
}

export function alertMatch(overrides: Partial<AlertMatch> = {}): AlertMatch {
  return {
    id: 1,
    at: "2026-08-31T12:00:00.000Z",
    severity: "high",
    reason: "Rule: Military aircraft",
    icao: "ae1463",
    sighting_id: 42,
    rule: { id: 1, name: "Military aircraft" },
    builtin_key: null,
    notified: false,
    ...overrides,
  };
}

/**
 * The catalogue the real backend ships (SPEC §45), in `SHIPPED_TEMPLATES`
 * order — including the built-in emergency entry, which has no conditions
 * because SPEC §47 gives it no rule to create.
 */
export const SHIPPED_TEMPLATE_FIXTURES: AlertTemplate[] = [
  alertTemplate(),
  alertTemplate({
    key: "government",
    name: "Government aircraft",
    description: "Any aircraft classified as a government operator.",
    conditions: {
      version: 1,
      classification: {
        military: false,
        government: true,
        law_enforcement: false,
      },
    },
  }),
  alertTemplate({
    key: "emergency_squawk",
    name: "Emergency squawk",
    description:
      "Squawk 7500, 7600 or 7700. Built in and always on: SPEC §47 requires emergency squawks to alert without a rule.",
    severity: "critical",
    builtin: true,
    conditions: null,
  }),
  alertTemplate({
    key: "first_ever",
    name: "First-ever aircraft",
    description: "An airframe this receiver has never recorded before.",
    severity: "info",
    conditions: { version: 1, rare_aircraft: { max_sightings: 1 } },
  }),
  alertTemplate({
    key: "watchlist",
    name: "Watchlist match",
    description: "Any aircraft on any watchlist (SPEC §42).",
    severity: "interesting",
    conditions: { version: 1, watchlist_any: true },
  }),
];

/**
 * The prose the backend's `RuleConditions.describe()` produces, mirrored so
 * a rule created through this mock renders the same phrases a real one
 * would. Mirroring backend output is precisely a mock's job; nothing outside
 * `src/test` may depend on it.
 */
function describeConditions(conditions: AlertRuleConditions): string[] {
  const phrases: string[] = [];
  const classification = conditions.classification;
  if (classification) {
    const parts: string[] = [];
    if (classification.military) parts.push("military");
    if (classification.government) parts.push("government");
    if (classification.law_enforcement) parts.push("law enforcement");
    if (classification.mission) parts.push(`mission ${classification.mission}`);
    phrases.push(parts.join(" and "));
  }
  if (conditions.type_code != null) {
    phrases.push(`type ${conditions.type_code}`);
  }
  if (conditions.model != null) {
    phrases.push(`model containing '${conditions.model}'`);
  }
  if (conditions.watchlist_id != null) {
    phrases.push(`on watchlist ${conditions.watchlist_id}`);
  }
  if (conditions.watchlist_any === true) {
    phrases.push("on any watchlist");
  }
  if (conditions.rare_aircraft) {
    phrases.push(
      `seen at most ${conditions.rare_aircraft.max_sightings} time(s) here`,
    );
  }
  if (conditions.rare_type) {
    phrases.push(
      `type seen on at most ${conditions.rare_type.max_sightings} airframe(s) here`,
    );
  }
  if (conditions.min_distance_nm != null) {
    phrases.push(`at least ${conditions.min_distance_nm} nm away`);
  }
  if (conditions.max_distance_nm != null) {
    phrases.push(`within ${conditions.max_distance_nm} nm`);
  }
  if (conditions.min_alt_ft != null) {
    phrases.push(`at or above ${conditions.min_alt_ft} ft`);
  }
  if (conditions.max_alt_ft != null) {
    phrases.push(`at or below ${conditions.max_alt_ft} ft`);
  }
  return phrases;
}

function jsonResponse(body: unknown, status = 200): Response {
  if (status === 204) {
    return new Response(null, { status });
  }
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** The `/api/v1` error envelope (§2.5), which the match history reads. */
function v1Error(status: number, message: string): Response {
  return jsonResponse({ error: { code: "error", message } }, status);
}

function parseBody(
  init: RequestInit | undefined,
): Record<string, unknown> | undefined {
  if (!init?.body) {
    return undefined;
  }
  return JSON.parse(init.body as string) as Record<string, unknown>;
}

export interface InstallAlertsApiMockOptions {
  rules?: AlertRule[];
  templates?: AlertTemplate[];
  matches?: AlertMatch[];
  /** Served on `GET /api/internal/watchlists`, which the rule builder reads
   * to offer a "on a watchlist" condition its choices. */
  watchlists?: Watchlist[];
  timezone?: string;
}

/**
 * Installs a stateful `global.fetch` stub over an in-memory store serving
 * every endpoint the Alerts page touches: alert-rule CRUD and template
 * instantiation (`/api/internal`, docs/API.md §5), the match history
 * (`GET /api/v1/alerts/matches`, §3.9), plus the watchlist list and config
 * document the rule builder and the history read for their own reasons.
 *
 * Stateful rather than scripted, the way `watchlistsApiMock` is, so a test
 * exercises the real `lib/api/alertRules` client and its mutations end to
 * end — build a rule in the UI, see it appear in the list with the
 * conditions the builder composed — instead of asserting against a single
 * canned response. The status codes the backend actually returns are served
 * too (`404` for an unknown key, `409` for a template that is built in or
 * already instantiated), so `ApiError` round-trips are exercised as well.
 */
export function installAlertsApiMock(
  options: InstallAlertsApiMockOptions = {},
) {
  let rules = [...(options.rules ?? [])];
  const templates = options.templates ?? SHIPPED_TEMPLATE_FIXTURES;
  const matches = [...(options.matches ?? [])];
  const watchlists = [...(options.watchlists ?? [])];
  const timezone = options.timezone ?? "UTC";
  let nextRuleId = Math.max(0, ...rules.map((rule) => rule.id)) + 1;

  function ruleFromBody(
    body: Record<string, unknown> | undefined,
    base: Partial<AlertRule>,
  ): AlertRule {
    const conditions = (body?.conditions ?? {
      version: 1,
    }) as AlertRuleConditions;
    return {
      id: base.id ?? nextRuleId++,
      name: String(body?.name ?? ""),
      description: (body?.description as string | null) ?? null,
      severity: (body?.severity as AlertRule["severity"]) ?? "interesting",
      enabled: body?.enabled !== false,
      template_key: base.template_key ?? null,
      conditions,
      describes: describeConditions(conditions),
      created_at: base.created_at ?? "2026-08-31T00:00:00.000Z",
      updated_at: "2026-08-31T00:00:00.000Z",
    };
  }

  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const raw = typeof input === "string" ? input : input.toString();
      const [path = "", search = ""] = raw.split("?");
      const method = (init?.method ?? "GET").toUpperCase();
      const body = parseBody(init);

      if (path === "/api/internal/config" && method === "GET") {
        return jsonResponse({
          first_run: false,
          config: defaultFlightSiteConfig({ timezone }),
          secrets_set: {},
        });
      }

      if (path === "/api/internal/watchlists" && method === "GET") {
        return jsonResponse({ watchlists });
      }

      if (path === "/api/internal/alert-templates" && method === "GET") {
        return jsonResponse({ templates });
      }

      const instantiateMatch =
        /^\/api\/internal\/alert-templates\/([^/]+)\/rules$/.exec(path);
      if (instantiateMatch && method === "POST") {
        const key = instantiateMatch[1] as string;
        const template = templates.find((entry) => entry.key === key);
        if (!template) {
          return jsonResponse(
            { detail: `no alert template with key '${key}'` },
            404,
          );
        }
        if (template.builtin || template.conditions === null) {
          return jsonResponse(
            {
              detail: `template '${key}' is built in and always on: it has no rule to create`,
            },
            409,
          );
        }
        if (rules.some((rule) => rule.template_key === key)) {
          return jsonResponse(
            { detail: `template '${key}' already has a rule` },
            409,
          );
        }
        const created = alertRule({
          id: nextRuleId++,
          name: template.name,
          description: template.description,
          severity: template.severity,
          template_key: key,
          conditions: template.conditions,
        });
        rules = [...rules, created];
        return jsonResponse(created, 201);
      }

      const ruleMatch = /^\/api\/internal\/alert-rules(?:\/(\d+))?$/.exec(path);
      if (ruleMatch) {
        const ruleId =
          ruleMatch[1] === undefined ? undefined : Number(ruleMatch[1]);

        if (method === "GET" && ruleId === undefined) {
          return jsonResponse({ rules });
        }
        if (method === "POST" && ruleId === undefined) {
          if (String(body?.name ?? "").trim().length === 0) {
            return jsonResponse({ detail: "rule name must not be blank" }, 422);
          }
          const created = ruleFromBody(body, {});
          rules = [...rules, created];
          return jsonResponse(created, 201);
        }
        if (method === "PUT" && ruleId !== undefined) {
          const target = rules.find((rule) => rule.id === ruleId);
          if (!target) {
            return jsonResponse(
              { detail: `no alert rule with id ${ruleId}` },
              404,
            );
          }
          if (String(body?.name ?? "").trim().length === 0) {
            return jsonResponse({ detail: "rule name must not be blank" }, 422);
          }
          // Provenance is not replaceable: tuning a shipped rule does not
          // make it stop having been shipped.
          const updated = ruleFromBody(body, {
            id: target.id,
            template_key: target.template_key,
            created_at: target.created_at,
          });
          rules = rules.map((rule) => (rule.id === ruleId ? updated : rule));
          return jsonResponse(updated);
        }
        if (method === "DELETE" && ruleId !== undefined) {
          if (!rules.some((rule) => rule.id === ruleId)) {
            return jsonResponse(
              { detail: `no alert rule with id ${ruleId}` },
              404,
            );
          }
          rules = rules.filter((rule) => rule.id !== ruleId);
          return jsonResponse(undefined, 204);
        }
      }

      if (path === "/api/v1/alerts/matches" && method === "GET") {
        const params = new URLSearchParams(search);
        const severity = params.get("severity");
        const icao = params.get("icao");
        if (icao !== null && !/^[0-9a-f]{6}$/.test(icao)) {
          return v1Error(422, "icao must be six lower-case hex digits");
        }
        // An id no rule owns is not an error: it simply matches nothing, the
        // same answer a rule that never fired gets (issue #98).
        const ruleFilter = params.get("rule_id");
        const limit = Number(params.get("limit") ?? "50");
        const offset = Number(params.get("offset") ?? "0");
        const filtered = matches.filter(
          (match) =>
            (severity === null || match.severity === severity) &&
            (icao === null || match.icao === icao) &&
            (ruleFilter === null || match.rule?.id === Number(ruleFilter)),
        );
        return jsonResponse({
          items: filtered.slice(offset, offset + limit),
          total: null,
          limit,
          offset,
        });
      }

      throw new Error(`Unhandled fetch in test: ${method} ${raw}`);
    },
  );

  vi.stubGlobal("fetch", fetchMock);

  return { fetchMock };
}
