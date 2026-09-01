/**
 * The rule builder's working model: one editable draft per condition, and
 * the two conversions between a list of drafts and the flat
 * `AlertRuleConditions` document the API stores (docs/DATA_MODEL.md §4.2).
 *
 * Why drafts rather than the document itself
 * ------------------------------------------
 *
 * The stored document is a *flat record* of optional conditions combined with
 * `AND` (SPEC §43 gives v1 no nested boolean trees). That is the right shape
 * to store and the wrong shape to edit: a form bound directly to it would
 * have to render every condition kind at once, most of them empty, and could
 * not distinguish "no distance condition" from "a distance condition I have
 * not finished typing". A list of drafts the user adds and removes is what
 * makes the builder visual, and it makes the flatness enforceable — a kind
 * already in the list is not offered again, because a second `type_code`
 * has nowhere to go in the document.
 *
 * Two kinds here are one condition apiece but two document fields:
 * `distance` writes `min_distance_nm`/`max_distance_nm` and `altitude`
 * writes `min_alt_ft`/`max_alt_ft`. They are paired deliberately — a window
 * is one idea to a user, and the backend validates the pair together
 * (an inverted window can never match, so it is refused at write time). Two
 * separate rows would put those halves where the inverted-window check
 * cannot be shown against either of them.
 *
 * Validation mirrors, and does not replace, the backend
 * ----------------------------------------------------
 *
 * Every bound below is the bound `flightsite.alerts.model` enforces, so a
 * rule the builder accepts is one the API accepts and the roadmap's "builder
 * prevents invalid rules" holds before a round trip is spent on it. The
 * backend stays authoritative: its rejection is surfaced the same way a
 * local one is, and this module is never consulted about a rule that already
 * exists.
 */
import type {
  AlertMissionCategory,
  AlertRuleConditions,
} from "@/lib/api/alertRules";

/** Longest a rule name may be — `MAX_NAME_LENGTH` in `alerts/model.py`. */
export const MAX_NAME_LENGTH = 120;
/** Longest a rule description may be — `MAX_DESCRIPTION_LENGTH`. */
export const MAX_DESCRIPTION_LENGTH = 500;
/** Longest an ICAO type designator may be — `RuleConditions.type_code`. */
export const MAX_TYPE_CODE_LENGTH = 16;
/** Longest a model substring may be — `RuleConditions.model`. */
export const MAX_MODEL_LENGTH = 120;
/** Upper bound on a rarity threshold — `MAX_RARITY_THRESHOLD`. A
 * receiver-relative "rare" count in the thousands is not rarity, it is every
 * aircraft. */
export const MAX_RARITY_THRESHOLD = 1000;
/** Upper bound on a distance condition, in nautical miles —
 * `MAX_DISTANCE_NM`. */
export const MAX_DISTANCE_NM = 10000;
/** Bounds on an altitude condition, in feet — `MIN_ALTITUDE_FT` /
 * `MAX_ALTITUDE_FT`. Both exist to catch a typo (a user meaning metres, or a
 * stray digit) rather than to express a real aviation limit. */
export const MIN_ALTITUDE_FT = -2000;
export const MAX_ALTITUDE_FT = 100000;

/**
 * The condition kinds the builder offers, which together cover every member
 * of the v1 document.
 *
 * `watchlist` and `watchlist_any` are separate kinds because they are
 * separate document fields answering different questions — "on *this* list"
 * versus "on any list at all" — and a first-run template can only ask the
 * second, having no list to name yet.
 */
export type ConditionKind =
  | "classification"
  | "type_code"
  | "model"
  | "watchlist"
  | "watchlist_any"
  | "rare_aircraft"
  | "rare_type"
  | "distance"
  | "altitude";

export interface ClassificationConditionDraft {
  kind: "classification";
  military: boolean;
  government: boolean;
  lawEnforcement: boolean;
  /** `""` for "no mission requirement". */
  mission: AlertMissionCategory | "";
}

export interface TextConditionDraft {
  kind: "type_code" | "model";
  text: string;
}

export interface WatchlistConditionDraft {
  kind: "watchlist";
  /** The chosen watchlist's id as a string, `""` while none is chosen — a
   * `<select>`'s value is always a string. */
  watchlistId: string;
}

export interface WatchlistAnyConditionDraft {
  kind: "watchlist_any";
}

export interface RarityConditionDraft {
  kind: "rare_aircraft" | "rare_type";
  maxSightings: string;
}

/** A `distance` (nm) or `altitude` (ft) window. Either bound may be left
 * blank for an open-ended one; both blank is not a condition. */
export interface RangeConditionDraft {
  kind: "distance" | "altitude";
  min: string;
  max: string;
}

export type ConditionDraft =
  | ClassificationConditionDraft
  | TextConditionDraft
  | WatchlistConditionDraft
  | WatchlistAnyConditionDraft
  | RarityConditionDraft
  | RangeConditionDraft;

export interface ConditionKindMeta {
  kind: ConditionKind;
  /** The name the "Add condition" picker and the condition's own legend
   * show. */
  label: string;
  /** One line saying what the condition asks, shown under the legend so the
   * builder explains itself without a manual. */
  summary: string;
}

/** Every kind, in the order the builder offers and re-renders them. Broadly
 * "what the aircraft is" before "where it is", which is the order the
 * conditions read in as a sentence. */
export const CONDITION_KINDS: ConditionKindMeta[] = [
  {
    kind: "classification",
    label: "Classification",
    summary:
      "Require what the aircraft is: military, government, law enforcement, or a mission category (SPEC §39).",
  },
  {
    kind: "type_code",
    label: "Type code",
    summary:
      "Match one ICAO type designator exactly, ignoring case — for example C17.",
  },
  {
    kind: "model",
    label: "Model",
    summary:
      "Match part of the model name, ignoring case — 'Globemaster' matches 'Boeing C-17A Globemaster III'.",
  },
  {
    kind: "watchlist",
    label: "On a watchlist",
    summary: "Require membership of one specific watchlist.",
  },
  {
    kind: "watchlist_any",
    label: "On any watchlist",
    summary: "Require membership of any watchlist at all.",
  },
  {
    kind: "rare_aircraft",
    label: "Rare airframe",
    summary:
      "Require that this receiver has recorded the airframe at most this many times, the current sighting included. 1 means never seen here before.",
  },
  {
    kind: "rare_type",
    label: "Rare type",
    summary:
      "Require that this receiver has recorded the aircraft's type on at most this many different airframes.",
  },
  {
    kind: "distance",
    label: "Distance",
    summary:
      "Require the aircraft to be within a distance window of the receiver, in nautical miles.",
  },
  {
    kind: "altitude",
    label: "Altitude",
    summary: "Require the aircraft to be in an altitude window, in feet.",
  },
];

const KIND_META: Record<ConditionKind, ConditionKindMeta> = Object.fromEntries(
  CONDITION_KINDS.map((meta) => [meta.kind, meta]),
) as Record<ConditionKind, ConditionKindMeta>;

export function conditionKindMeta(kind: ConditionKind): ConditionKindMeta {
  return KIND_META[kind];
}

/** A blank draft of `kind`, as the "Add condition" button produces it. */
export function emptyCondition(kind: ConditionKind): ConditionDraft {
  switch (kind) {
    case "classification":
      return {
        kind,
        military: false,
        government: false,
        lawEnforcement: false,
        mission: "",
      };
    case "type_code":
    case "model":
      return { kind, text: "" };
    case "watchlist":
      return { kind, watchlistId: "" };
    case "watchlist_any":
      return { kind };
    case "rare_aircraft":
    case "rare_type":
      return { kind, maxSightings: "" };
    case "distance":
    case "altitude":
      return { kind, min: "", max: "" };
  }
}

/**
 * The kinds not yet used, in catalogue order.
 *
 * The document is flat, so each kind can appear at most once — this is what
 * makes that visible in the UI rather than discovered when a second
 * `type_code` silently overwrites the first.
 */
export function availableKinds(
  drafts: readonly ConditionDraft[],
): ConditionKindMeta[] {
  const used = new Set(drafts.map((draft) => draft.kind));
  return CONDITION_KINDS.filter((meta) => !used.has(meta.kind));
}

/** `null` for a blank field, `NaN` for something that is not a number, the
 * number otherwise — so a caller can tell "not filled in" from "filled in
 * wrongly" and say something different about each. */
function parseNumeric(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed.length === 0) {
    return null;
  }
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : Number.NaN;
}

function validateRarity(raw: string): string | null {
  const value = parseNumeric(raw);
  if (value === null) {
    return "Enter a threshold.";
  }
  if (Number.isNaN(value) || !Number.isInteger(value)) {
    return "Enter a whole number.";
  }
  if (value < 1 || value > MAX_RARITY_THRESHOLD) {
    return `Enter a threshold between 1 and ${MAX_RARITY_THRESHOLD}.`;
  }
  return null;
}

function validateDistance(draft: RangeConditionDraft): string | null {
  const min = parseNumeric(draft.min);
  const max = parseNumeric(draft.max);
  if (min === null && max === null) {
    return "Enter a minimum, a maximum, or both.";
  }
  if (Number.isNaN(min) || Number.isNaN(max)) {
    return "Enter distances in nautical miles.";
  }
  if (min !== null && (min < 0 || min > MAX_DISTANCE_NM)) {
    return `A minimum distance must be between 0 and ${MAX_DISTANCE_NM} nm.`;
  }
  if (max !== null && (max <= 0 || max > MAX_DISTANCE_NM)) {
    return `A maximum distance must be above 0 and at most ${MAX_DISTANCE_NM} nm.`;
  }
  if (min !== null && max !== null && min >= max) {
    return "The minimum must be below the maximum, or the rule can never match.";
  }
  return null;
}

function validateAltitude(draft: RangeConditionDraft): string | null {
  const min = parseNumeric(draft.min);
  const max = parseNumeric(draft.max);
  if (min === null && max === null) {
    return "Enter a floor, a ceiling, or both.";
  }
  if (Number.isNaN(min) || Number.isNaN(max)) {
    return "Enter altitudes in feet.";
  }
  const outOfRange = (value: number): boolean =>
    value < MIN_ALTITUDE_FT || value > MAX_ALTITUDE_FT;
  if ((min !== null && outOfRange(min)) || (max !== null && outOfRange(max))) {
    return `Altitudes must be between ${MIN_ALTITUDE_FT} and ${MAX_ALTITUDE_FT} ft.`;
  }
  if (min !== null && max !== null && min >= max) {
    return "The floor must be below the ceiling, or the rule can never match.";
  }
  return null;
}

/** What is wrong with one condition, or `null` when it is ready to send. */
export function validateCondition(draft: ConditionDraft): string | null {
  switch (draft.kind) {
    case "classification":
      if (
        !draft.military &&
        !draft.government &&
        !draft.lawEnforcement &&
        draft.mission === ""
      ) {
        return "Require at least one of military, government, law enforcement, or a mission.";
      }
      return null;
    case "type_code": {
      const text = draft.text.trim();
      if (text.length === 0) {
        return "Enter a type designator.";
      }
      if (text.length > MAX_TYPE_CODE_LENGTH) {
        return `A type designator is at most ${MAX_TYPE_CODE_LENGTH} characters.`;
      }
      return null;
    }
    case "model": {
      const text = draft.text.trim();
      if (text.length === 0) {
        return "Enter part of a model name.";
      }
      if (text.length > MAX_MODEL_LENGTH) {
        return `A model substring is at most ${MAX_MODEL_LENGTH} characters.`;
      }
      return null;
    }
    case "watchlist":
      return draft.watchlistId === "" ? "Choose a watchlist." : null;
    case "watchlist_any":
      return null;
    case "rare_aircraft":
    case "rare_type":
      return validateRarity(draft.maxSightings);
    case "distance":
      return validateDistance(draft);
    case "altitude":
      return validateAltitude(draft);
  }
}

/** What is wrong with the rule's name, or `null`. */
export function validateRuleName(raw: string): string | null {
  const name = raw.trim();
  if (name.length === 0) {
    return "Enter a name.";
  }
  if (name.length > MAX_NAME_LENGTH) {
    return `A name is at most ${MAX_NAME_LENGTH} characters.`;
  }
  return null;
}

/** What is wrong with the rule's description, or `null`. */
export function validateRuleDescription(raw: string): string | null {
  return raw.trim().length > MAX_DESCRIPTION_LENGTH
    ? `A description is at most ${MAX_DESCRIPTION_LENGTH} characters.`
    : null;
}

/**
 * Why the condition list as a whole cannot be sent, or `null`.
 *
 * The empty case is a rule, not a nitpick: a condition set that constrains
 * nothing would match every aircraft in the sky at whatever severity it
 * declared, which is the one configuration a user can never have meant. The
 * backend refuses it for the same reason.
 */
export function validateConditionList(
  drafts: readonly ConditionDraft[],
): string | null {
  return drafts.length === 0
    ? "Add at least one condition. A rule with none would match every aircraft."
    : null;
}

/** Whether every part of the rule is ready to send. */
export function isRuleDraftValid(
  name: string,
  description: string,
  drafts: readonly ConditionDraft[],
): boolean {
  return (
    validateRuleName(name) === null &&
    validateRuleDescription(description) === null &&
    validateConditionList(drafts) === null &&
    drafts.every((draft) => validateCondition(draft) === null)
  );
}

/** A numeric field's value for the document: the parsed number, or
 * `undefined` when the field was left blank. Assumes the draft has passed
 * {@link validateCondition}. */
function numberOrUndefined(raw: string): number | undefined {
  const value = parseNumeric(raw);
  return value === null || Number.isNaN(value) ? undefined : value;
}

/**
 * The stored document these drafts describe.
 *
 * Only the conditions the user actually added appear: an unset condition is
 * an absent key, never a `null` or a zero, so adding a condition kind in a
 * later document version cannot change what an existing rule means.
 */
export function conditionsToDocument(
  drafts: readonly ConditionDraft[],
  appliesOnGround: boolean,
): AlertRuleConditions {
  const document: AlertRuleConditions = { version: 1 };
  for (const draft of drafts) {
    switch (draft.kind) {
      case "classification":
        document.classification = {
          military: draft.military,
          government: draft.government,
          law_enforcement: draft.lawEnforcement,
          ...(draft.mission === "" ? {} : { mission: draft.mission }),
        };
        break;
      case "type_code":
        document.type_code = draft.text.trim();
        break;
      case "model":
        document.model = draft.text.trim();
        break;
      case "watchlist":
        document.watchlist_id = Number(draft.watchlistId);
        break;
      case "watchlist_any":
        document.watchlist_any = true;
        break;
      case "rare_aircraft":
        document.rare_aircraft = { max_sightings: Number(draft.maxSightings) };
        break;
      case "rare_type":
        document.rare_type = { max_sightings: Number(draft.maxSightings) };
        break;
      case "distance":
        document.min_distance_nm = numberOrUndefined(draft.min);
        document.max_distance_nm = numberOrUndefined(draft.max);
        break;
      case "altitude":
        document.min_alt_ft = numberOrUndefined(draft.min);
        document.max_alt_ft = numberOrUndefined(draft.max);
        break;
    }
  }
  if (appliesOnGround) {
    document.applies_on_ground = true;
  }
  return document;
}

function numericText(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

/**
 * The drafts a stored document describes, for editing an existing rule.
 *
 * The inverse of {@link conditionsToDocument} over every document this build
 * can write, which is what lets a rule be opened, changed in one place and
 * saved without the untouched conditions being reworded on the way through.
 * Drafts come back in {@link CONDITION_KINDS} order rather than in whatever
 * order the JSON happened to serialize, so the same rule always presents the
 * same way.
 */
export function documentToConditions(conditions: AlertRuleConditions): {
  drafts: ConditionDraft[];
  appliesOnGround: boolean;
} {
  const drafts: ConditionDraft[] = [];
  const classification = conditions.classification;
  if (classification) {
    drafts.push({
      kind: "classification",
      military: classification.military,
      government: classification.government,
      lawEnforcement: classification.law_enforcement,
      mission: classification.mission ?? "",
    });
  }
  if (conditions.type_code != null) {
    drafts.push({ kind: "type_code", text: conditions.type_code });
  }
  if (conditions.model != null) {
    drafts.push({ kind: "model", text: conditions.model });
  }
  if (conditions.watchlist_id != null) {
    drafts.push({
      kind: "watchlist",
      watchlistId: String(conditions.watchlist_id),
    });
  }
  if (conditions.watchlist_any === true) {
    drafts.push({ kind: "watchlist_any" });
  }
  if (conditions.rare_aircraft) {
    drafts.push({
      kind: "rare_aircraft",
      maxSightings: String(conditions.rare_aircraft.max_sightings),
    });
  }
  if (conditions.rare_type) {
    drafts.push({
      kind: "rare_type",
      maxSightings: String(conditions.rare_type.max_sightings),
    });
  }
  if (conditions.min_distance_nm != null || conditions.max_distance_nm != null) {
    drafts.push({
      kind: "distance",
      min: numericText(conditions.min_distance_nm),
      max: numericText(conditions.max_distance_nm),
    });
  }
  if (conditions.min_alt_ft != null || conditions.max_alt_ft != null) {
    drafts.push({
      kind: "altitude",
      min: numericText(conditions.min_alt_ft),
      max: numericText(conditions.max_alt_ft),
    });
  }
  return { drafts, appliesOnGround: conditions.applies_on_ground === true };
}
