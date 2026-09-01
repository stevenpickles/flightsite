/**
 * The five entry kinds (SPEC §42), their form labels/placeholders, and the
 * category picklist — mirroring
 * `backend/src/flightsite/watchlists/vocabulary.py` so the form only ever
 * offers a value the backend will actually accept.
 */
import type { WatchlistEntryKind } from "@/lib/api/watchlists";

export interface EntryKindMeta {
  kind: WatchlistEntryKind;
  label: string;
  placeholder: string;
  /** Shown under the input as guidance, not a validation message. */
  hint: string;
}

/** Keyed by kind rather than a plain array, so looking one up
 * (`entryKindMeta`) never has to fall back to a default — every
 * `WatchlistEntryKind` is a key by construction. */
const ENTRY_KIND_META: Record<WatchlistEntryKind, EntryKindMeta> = {
  icao24: {
    kind: "icao24",
    label: "ICAO hex",
    placeholder: "ae1463",
    hint: "Six hex digits — the aircraft's fixed 24-bit address.",
  },
  registration: {
    kind: "registration",
    label: "Registration",
    placeholder: "N12345",
    hint: "Tail number, e.g. N12345 or G-ABCD.",
  },
  type_code: {
    kind: "type_code",
    label: "Aircraft type",
    placeholder: "B738",
    hint: "ICAO type designator, e.g. B738 or A320.",
  },
  operator: {
    kind: "operator",
    label: "Operator",
    placeholder: "Delta Air Lines",
    hint: "Matched against the resolved operator name, case-insensitively.",
  },
  category: {
    kind: "category",
    label: "Category",
    placeholder: "",
    hint: "Matched against the aircraft's classification.",
  },
};

/** Every kind's metadata, in the order a kind selector should list them. */
export const ENTRY_KINDS: EntryKindMeta[] = Object.values(ENTRY_KIND_META);

export function entryKindMeta(kind: WatchlistEntryKind): EntryKindMeta {
  return ENTRY_KIND_META[kind];
}

/** SPEC §39's mission categories, minus `unknown` — see
 * `flightsite.watchlists.vocabulary`'s module docstring for why watchlisting
 * "every unclassified aircraft" is not offered as a category. */
export const CATEGORY_OPTIONS: { value: string; label: string }[] = [
  { value: "commercial_passenger", label: "Commercial passenger" },
  { value: "cargo", label: "Cargo" },
  { value: "general_aviation", label: "General aviation" },
  { value: "business_aviation", label: "Business aviation" },
  { value: "military", label: "Military" },
  { value: "government", label: "Government" },
  { value: "law_enforcement", label: "Law enforcement" },
  { value: "medical", label: "Medical" },
  { value: "firefighting", label: "Firefighting" },
  { value: "training", label: "Training" },
  { value: "helicopter", label: "Helicopter" },
];
