/**
 * The hierarchical icon resolver: **type → category → emitter → generic**
 * (SPEC §34), and beside it the palette: who flies the aircraft.
 *
 * Roadmap slice 014 built the chain as plumbing with empty tables; slices
 * 021–024 started supplying `aircraft_type` and `classification`; slice 086
 * added the aircraft's own ADS-B emitter category as the fallback for an
 * airframe no registry describes; slice 094 drew the silhouettes and filled
 * the tables in. Each level is a declarative lookup:
 *
 * 1. **Type** — the ICAO type designator the metadata registries resolved
 *    (`"C172"`, `"K35R"`), through {@link TYPE_ICON_SHAPES}. The most specific
 *    statement available, so it wins outright: a `K35R` is a tanker whatever
 *    the classification engine filed it under.
 * 2. **Category** — `classification.icon_category`, the backend's own
 *    summary of the airframe (`docs/API.md` §2.8), through
 *    {@link CATEGORY_ICON_SHAPES}.
 * 3. **Emitter** — `emitter_category`, what the transponder says it is
 *    (`A1` light, `A7` rotorcraft …), through
 *    {@link EMITTER_CATEGORY_ICON_SHAPES}. Consulted only when metadata has
 *    no opinion at all — no type silhouette, and no `icon_category` beyond
 *    `null` / `"unknown"` — so a registry saying "airliner" outranks a
 *    transmitter saying "rotorcraft".
 * 4. **Generic** — the swept-wing fallback, or its ground form.
 *
 * **No heuristics.** The resolver reads those three fields and nothing else.
 * Guessing "rotorcraft" from a low ground speed, say, would invent a
 * classification the data does not support, and SPEC §39 requires
 * classification to carry provenance and not claim certainty on weak evidence.
 * The same holds for the palette: {@link resolveIconPalette} reads the three
 * published classification booleans and nothing else.
 */

import type {
  AircraftIconShape,
  IconPalette,
} from "@/features/map/aircraft/icons/silhouettes";
import { iconImageId } from "@/features/map/aircraft/icons/silhouettes";
import type { Classification, LiveAircraft } from "@/lib/api/live";

/** Which level of the hierarchy produced the icon. Exposed because it is the
 * thing worth asserting on: the fallback chain is the behaviour, the shape is
 * just today's consequence of it. */
export type IconResolutionLevel = "type" | "category" | "emitter" | "generic";

export interface IconResolution {
  shape: AircraftIconShape;
  level: IconResolutionLevel;
}

function table(
  shape: AircraftIconShape,
  designators: string,
): Record<string, AircraftIconShape> {
  return Object.fromEntries(designators.split(/\s+/).map((code) => [code, shape]));
}

/**
 * ICAO type designator → silhouette. Keys are upper-case ICAO Doc 8643
 * designators, grouped by the shape they draw.
 *
 * The tables are generous where the planform is certain and silent where it
 * is not: a designator missing here falls through to the category and
 * emitter levels, which is the honest outcome, whereas a designator filed
 * under the wrong shape draws a confident lie. Two consequences worth
 * knowing:
 *
 * - Rotorcraft are **not** listed. The backend's own rotorcraft table already
 *   yields `icon_category: helicopter`, and duplicating it here would be a
 *   second list to keep honest. Only the tiltrotor and the tandem-rotor
 *   types appear, because the backend files them as military transport and
 *   helicopter respectively and the drawing says otherwise.
 * - Military airframes that *are* an airliner (the P-8 is a 737-800, the
 *   E-3 and RC-135 are 707s, a KC-10 carries the `DC10` designator) keep the
 *   airliner planform; the military palette says the rest.
 */
export const TYPE_ICON_SHAPES: Readonly<Record<string, AircraftIconShape>> = {
  ...table(
    "light-high-wing",
    "C150 C152 C162 C170 C172 C175 C177 C180 C182 C185 C206 C210 C72R C77R C208 PA18",
  ),
  ...table("light-cirrus", "SR20 SR22 S22T"),
  ...table(
    "light-low-wing",
    "P28A P28B P28R P28T PA24 PA32 PA46 P46T BE23 BE33 BE35 BE36 M20P M20T " +
      "DA20 DA40 AA5 TOBA DR40 GLAS RV7 RV8 PC12 TBM7 TBM9",
  ),
  ...table("light-twin", "BE55 BE58 DA42 DA62 PA31 PA34 C310"),
  ...table(
    "turboprop-twin",
    "DH8A DH8B DH8C DH8D AT43 AT72 AT75 AT76 SF34 E120 B350 BE20 BE30 DHC6 JS41 C2",
  ),
  ...table(
    "business-jet",
    "GLF2 GLF3 GLF4 GLF5 GLF6 GL5T GL7T GLEX G280 GALX " +
      "C25A C25B C25C C500 C510 C525 C550 C560 C56X C650 C680 C68A C700 C750 " +
      "CL30 CL35 CL60 CL64 E50P E55P E545 E550 F2TH F900 F9EX FA7X FA8X FA50 " +
      "H25B H25C LJ31 LJ35 LJ40 LJ45 LJ60 LJ75 PC24 BE40 HDJT EA50 SF50",
  ),
  ...table(
    "narrowbody",
    "A318 A319 A320 A321 A19N A20N A21N B737 B738 B739 B38M B39M B752 B753 " +
      "BCS1 BCS3 E170 E175 E75S E75L E190 E195 E290 E295 E135 E145 " +
      "CRJ2 CRJ7 CRJ9 CRJX SU95 MD82 MD83 MD88 MD90 B712 B722 P8",
  ),
  ...table(
    "widebody-twin",
    "B762 B763 B764 B772 B773 B77L B77W B788 B789 B78X " +
      "A306 A310 A332 A333 A338 A339 A359 A35K",
  ),
  ...table(
    "widebody-quad",
    "B741 B742 B743 B744 B748 B74S A388 A342 A343 A345 A346 MD11 DC10 L101 IL96 " +
      "E3TF E3CF E6 R135",
  ),
  ...table("fighter", "F15 F16 F18 F22 F35 A10 AV8B EUFI RFAL TOR T38 F5 F14 HAWK GRIP"),
  ...table("bomber", "B1 B2 B52 TU95"),
  ...table("tanker", "K35R K35E"),
  ...table("military-transport", "C17 C5M C130 C30J C27J C160 C295 A400 IL76 A124"),
  ...table("patrol", "P3 E2"),
  ...table("tiltrotor", "V22 A609"),
  ...table("tandem-rotor", "H47 H46"),
  ...table("uav", "MQ9 RQ4"),
  ...table("glider", "DISC VENT DUOD DG80 LS8"),
};

/**
 * Icon category → silhouette, keyed by lower-case
 * `classification.icon_category` (`docs/API.md` §2.8).
 *
 * `military`, `government`, `law_enforcement`, `medical` and `firefighting`
 * are deliberately absent: they say who flies the aircraft, not what it is,
 * and the palette already carries that. They fall through to the emitter
 * level like any other category with no shape of its own. `light_aircraft`
 * draws the high-wing trainer because it is the commonest light aeroplane —
 * a category→shape mapping, not an inference about the airframe.
 */
export const CATEGORY_ICON_SHAPES: Readonly<Record<string, AircraftIconShape>> =
  {
    airliner: "narrowbody",
    cargo: "narrowbody",
    business_jet: "business-jet",
    light_aircraft: "light-high-wing",
    helicopter: "rotorcraft",
    rotorcraft: "rotorcraft",
    gyrocopter: "rotorcraft",
    military_jet: "fighter",
    military_transport: "military-transport",
  };

/**
 * ADS-B emitter category → silhouette (roadmap slice 086), the fallback for
 * an aircraft metadata says nothing about. Keyed by the upper-case code.
 *
 * | Category | Silhouette |
 * |---|---|
 * | `A1` light (< 15 500 lb) | light high-wing |
 * | `A2` small, `A3` large | narrowbody |
 * | `A4` high-vortex large, `A5` heavy | widebody twin |
 * | `A6` high performance | fighter |
 * | `A7` rotorcraft | rotorcraft |
 * | `B1` glider / sailplane, `B4` ultralight | glider |
 * | `B6` UAV | UAV |
 * | `B2` balloon, `B3` parachutist, `B7` space | generic |
 * | `C*` surface vehicles / obstacles, `D*`, `A0`/`B0`/`C0` | generic |
 */
export const EMITTER_CATEGORY_ICON_SHAPES: Readonly<
  Record<string, AircraftIconShape>
> = {
  A1: "light-high-wing",
  A2: "narrowbody",
  A3: "narrowbody",
  A4: "widebody-twin",
  A5: "widebody-twin",
  A6: "fighter",
  A7: "rotorcraft",
  B1: "glider",
  B4: "glider",
  B6: "uav",
};

/** The end of the chain: an aircraft with no usable metadata, airborne. */
export const GENERIC_ICON_SHAPE: AircraftIconShape = "generic";

/** The end of the chain for an aircraft the decoder reports as on the ground. */
export const GROUND_ICON_SHAPE: AircraftIconShape = "ground";

function normalize(value: string | null | undefined): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/** The fields the resolver reads — a structural subset of {@link LiveAircraft},
 * so callers can resolve an icon without constructing a whole payload. */
export type IconResolverInput = Pick<
  LiveAircraft,
  "aircraft_type" | "classification" | "on_ground" | "emitter_category"
>;

/**
 * Resolves the silhouette for one aircraft.
 *
 * The `on_ground` variant applies at the **generic level only**: it is the
 * fallback's own ground form, not a level of the hierarchy. A known type or
 * category is a stronger statement about what the aircraft *is* than the
 * decoder's ground flag is about how it should be drawn, so a metadata-resolved
 * silhouette keeps its shape while taxiing — and so does an emitter-category
 * one: a helicopter on a pad is still a helicopter.
 */
export function resolveAircraftIcon(
  aircraft: IconResolverInput,
): IconResolution {
  const type = normalize(aircraft.aircraft_type)?.toUpperCase();
  const byType = type === undefined ? undefined : TYPE_ICON_SHAPES[type];
  if (byType) {
    return { shape: byType, level: "type" };
  }

  const category = normalize(
    aircraft.classification?.icon_category,
  )?.toLowerCase();
  const byCategory =
    category === undefined ? undefined : CATEGORY_ICON_SHAPES[category];
  if (byCategory) {
    return { shape: byCategory, level: "category" };
  }

  // Only when metadata has no opinion at all: a stated category outranks the
  // transmitter even when its own shape is the generic one (module comment).
  if (category === undefined || category === "unknown") {
    const emitter = normalize(aircraft.emitter_category)?.toUpperCase();
    if (
      emitter !== undefined &&
      Object.hasOwn(EMITTER_CATEGORY_ICON_SHAPES, emitter)
    ) {
      const byEmitter = EMITTER_CATEGORY_ICON_SHAPES[emitter];
      if (byEmitter) {
        return { shape: byEmitter, level: "emitter" };
      }
    }
  }

  return {
    shape: aircraft.on_ground === true ? GROUND_ICON_SHAPE : GENERIC_ICON_SHAPE,
    level: "generic",
  };
}

/**
 * The palette for one aircraft: `military` over `government` (which also
 * covers law enforcement) over `civil`, read from the three published
 * classification booleans and nothing else — not `mission`, not
 * `icon_category`, and never kinematics.
 *
 * The tint is a **secondary** cue (SPEC §36). The silhouette is the primary
 * statement about the aircraft, and the classification the palette reflects
 * is always also surfaced as text — the detail panel, the category filters,
 * the label's indicator — so nothing is communicated by colour alone. That
 * is what makes it acceptable for a P-8 and a 737-800 to share a planform
 * and differ only in tint.
 */
export function resolveIconPalette(
  classification: Classification | null | undefined,
): IconPalette {
  if (classification?.military === true) {
    return "military";
  }
  if (
    classification?.government === true ||
    classification?.law_enforcement === true
  ) {
    return "government";
  }
  return "civil";
}

/** The registered image id for one aircraft: its silhouette in its palette. */
export function resolveAircraftIconImageId(aircraft: IconResolverInput): string {
  return iconImageId(
    resolveAircraftIcon(aircraft).shape,
    resolveIconPalette(aircraft.classification),
  );
}
