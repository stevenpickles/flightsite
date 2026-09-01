"""The curated operator groups (SPEC §38, ``docs/DATA_MODEL.md`` §3.5).

A seed set, not a claim to completeness. It covers the operators a receiver in
North America or Europe actually hears often enough for grouping to be worth
anything — the major passenger carriers, the integrators and freight operators,
the armed services and federal agencies whose aircraft show up on ADS-B, and
the medical and firefighting operators that fly at low level over populated
areas. Everything else keeps its exact operator name and no group, which is
what SPEC §38 means by grouping being **additive**: the group is extra
information, never a replacement for what the source actually said.

Judgement calls made here, so they are argued once rather than re-litigated:

* **The US armed services are one group.** ``docs/API.md`` §3.3's own example
  pairs the operator ``"United States Air Force"`` with the operator group
  ``"US Military"``, and a user filtering for military traffic wants the lot.
  Other nations get one group per service only where the upstream names are
  distinct enough to be worth it.
* **Military is not automatically government.** Armed forces are of course
  state bodies, but SPEC §39 lists ``military`` and ``government`` as separate
  categories, and a user who asks for government aircraft is asking about the
  civil state — agencies, survey flights, heads of state — not about every
  fighter in the pattern. So military groups set ``military`` and leave
  ``government`` alone.
* **Law enforcement is government.** The opposite call, for the opposite
  reason: a sheriff's helicopter genuinely is a government aircraft on any
  reading, and nobody filtering for government traffic would be surprised to
  find it.
* **The US Coast Guard is filed as government and law enforcement, not
  military.** It is legally an armed service, but what it is *doing* overhead
  is search and rescue and maritime law enforcement, and SPEC §39's categories
  are about use. This is a deliberate, arguable call recorded in one place.
* **Callsign designators are listed only where the operator flies under its own
  ICAO code.** A codeshare or a wet-lease files under the operating carrier, so
  a callsign tells you who is flying the aircraft — which is what the group is
  about — and not who sold the ticket.

Group ids are not stored here: they are assigned deterministically from the
slugs (:mod:`flightsite.classification.operators`), so this file never has to
carry a number that a future insertion would disturb.
"""

from __future__ import annotations

from typing import Final

from flightsite.classification.specs import OperatorGroupSpec, OperatorPattern
from flightsite.classification.vocabulary import GroupKind, MissionCategory

_PASSENGER: Final = MissionCategory.COMMERCIAL_PASSENGER
_CARGO: Final = MissionCategory.CARGO

#: Every curated group, in the order a reviewer would want to read them.
OPERATOR_GROUPS: Final[tuple[OperatorGroupSpec, ...]] = (
    # ----------------------------------------------------- passenger, US/CA/MX
    OperatorGroupSpec(
        slug="delta",
        name="Delta Air Lines",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Delta Air Lines", "Delta Air Lines Inc", "Delta"),
        callsigns=("DAL",),
    ),
    OperatorGroupSpec(
        slug="united",
        name="United Airlines",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("United Airlines", "United Air Lines", "United Air Lines Inc"),
        callsigns=("UAL",),
    ),
    OperatorGroupSpec(
        slug="american",
        name="American Airlines",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("American Airlines", "American Airlines Inc"),
        callsigns=("AAL",),
    ),
    OperatorGroupSpec(
        slug="southwest",
        name="Southwest Airlines",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Southwest Airlines", "Southwest Airlines Co"),
        callsigns=("SWA",),
    ),
    OperatorGroupSpec(
        slug="alaska",
        name="Alaska Airlines",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Alaska Airlines", "Alaska Airlines Inc"),
        callsigns=("ASA",),
    ),
    OperatorGroupSpec(
        slug="jetblue",
        name="JetBlue Airways",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("JetBlue Airways", "JetBlue"),
        callsigns=("JBU",),
    ),
    OperatorGroupSpec(
        slug="spirit",
        name="Spirit Airlines",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Spirit Airlines",),
        callsigns=("NKS",),
    ),
    OperatorGroupSpec(
        slug="frontier",
        name="Frontier Airlines",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Frontier Airlines",),
        callsigns=("FFT",),
    ),
    OperatorGroupSpec(
        slug="allegiant",
        name="Allegiant Air",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Allegiant Air",),
        callsigns=("AAY",),
    ),
    OperatorGroupSpec(
        slug="hawaiian",
        name="Hawaiian Airlines",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Hawaiian Airlines",),
        callsigns=("HAL",),
    ),
    OperatorGroupSpec(
        slug="sun-country",
        name="Sun Country Airlines",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Sun Country Airlines",),
        callsigns=("SCX",),
    ),
    OperatorGroupSpec(
        slug="breeze",
        name="Breeze Airways",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Breeze Airways",),
        callsigns=("MXY",),
    ),
    OperatorGroupSpec(
        slug="skywest",
        name="SkyWest Airlines",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("SkyWest Airlines", "SkyWest"),
        callsigns=("SKW",),
    ),
    OperatorGroupSpec(
        slug="republic",
        name="Republic Airways",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Republic Airways", "Republic Airline"),
        callsigns=("RPA",),
    ),
    OperatorGroupSpec(
        slug="envoy",
        name="Envoy Air",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Envoy Air",),
        callsigns=("ENY",),
    ),
    OperatorGroupSpec(
        slug="endeavor",
        name="Endeavor Air",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Endeavor Air",),
        callsigns=("EDV",),
    ),
    OperatorGroupSpec(
        slug="air-canada",
        name="Air Canada",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Air Canada", "Air Canada Rouge", "Air Canada Jazz"),
        callsigns=("ACA", "ROU", "JZA"),
    ),
    OperatorGroupSpec(
        slug="westjet",
        name="WestJet",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("WestJet", "WestJet Airlines"),
        callsigns=("WJA",),
    ),
    OperatorGroupSpec(
        slug="aeromexico",
        name="Aeroméxico",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Aeroméxico", "Aeromexico", "Aerovias de Mexico"),
        callsigns=("AMX",),
    ),
    # -------------------------------------------------------- passenger, EU/UK
    OperatorGroupSpec(
        slug="lufthansa",
        name="Lufthansa",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Lufthansa", "Deutsche Lufthansa AG", "Lufthansa CityLine"),
        callsigns=("DLH", "CLH"),
    ),
    OperatorGroupSpec(
        slug="british-airways",
        name="British Airways",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("British Airways", "British Airways PLC"),
        callsigns=("BAW",),
    ),
    OperatorGroupSpec(
        slug="air-france",
        name="Air France",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Air France", "Air France Hop"),
        callsigns=("AFR",),
    ),
    OperatorGroupSpec(
        slug="klm",
        name="KLM",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("KLM", "KLM Royal Dutch Airlines", "KLM Cityhopper"),
        callsigns=("KLM", "KLC"),
    ),
    OperatorGroupSpec(
        slug="ryanair",
        name="Ryanair",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Ryanair", "Ryanair UK", "Malta Air", "Buzz"),
        callsigns=("RYR", "RUK"),
    ),
    OperatorGroupSpec(
        slug="easyjet",
        name="easyJet",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("easyJet", "easyJet Airline Company Limited", "easyJet Europe"),
        callsigns=("EZY", "EJU"),
    ),
    OperatorGroupSpec(
        slug="wizz-air",
        name="Wizz Air",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Wizz Air", "Wizz Air Hungary", "Wizz Air UK"),
        callsigns=("WZZ", "WUK"),
    ),
    OperatorGroupSpec(
        slug="iberia",
        name="Iberia",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Iberia", "Iberia Express"),
        callsigns=("IBE", "IBS"),
    ),
    OperatorGroupSpec(
        slug="vueling",
        name="Vueling",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Vueling", "Vueling Airlines"),
        callsigns=("VLG",),
    ),
    OperatorGroupSpec(
        slug="swiss",
        name="Swiss International Air Lines",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Swiss", "Swiss International Air Lines"),
        callsigns=("SWR",),
    ),
    OperatorGroupSpec(
        slug="austrian",
        name="Austrian Airlines",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Austrian Airlines", "Austrian"),
        callsigns=("AUA",),
    ),
    OperatorGroupSpec(
        slug="brussels-airlines",
        name="Brussels Airlines",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Brussels Airlines",),
        callsigns=("BEL",),
    ),
    OperatorGroupSpec(
        slug="eurowings",
        name="Eurowings",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Eurowings", "Eurowings Discover"),
        callsigns=("EWG", "OCN"),
    ),
    OperatorGroupSpec(
        slug="sas",
        name="SAS Scandinavian Airlines",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("SAS", "Scandinavian Airlines", "Scandinavian Airlines System"),
        callsigns=("SAS",),
    ),
    OperatorGroupSpec(
        slug="finnair",
        name="Finnair",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Finnair",),
        callsigns=("FIN",),
    ),
    OperatorGroupSpec(
        slug="norwegian",
        name="Norwegian",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Norwegian", "Norwegian Air Shuttle", "Norwegian Air Sweden"),
        callsigns=("NAX", "NOZ"),
    ),
    OperatorGroupSpec(
        slug="tap",
        name="TAP Air Portugal",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("TAP", "TAP Air Portugal", "TAP Portugal"),
        callsigns=("TAP",),
    ),
    OperatorGroupSpec(
        slug="lot",
        name="LOT Polish Airlines",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("LOT", "LOT Polish Airlines"),
        callsigns=("LOT",),
    ),
    OperatorGroupSpec(
        slug="ita-airways",
        name="ITA Airways",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("ITA Airways",),
        callsigns=("ITY",),
    ),
    OperatorGroupSpec(
        slug="aer-lingus",
        name="Aer Lingus",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Aer Lingus",),
        callsigns=("EIN",),
    ),
    OperatorGroupSpec(
        slug="virgin-atlantic",
        name="Virgin Atlantic",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Virgin Atlantic", "Virgin Atlantic Airways"),
        callsigns=("VIR",),
    ),
    OperatorGroupSpec(
        slug="jet2",
        name="Jet2",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Jet2", "Jet2.com"),
        callsigns=("EXS",),
    ),
    OperatorGroupSpec(
        slug="tui-airways",
        name="TUI Airways",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("TUI Airways", "TUI fly"),
        callsigns=("TOM",),
    ),
    OperatorGroupSpec(
        slug="condor",
        name="Condor",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Condor", "Condor Flugdienst"),
        callsigns=("CFG",),
    ),
    OperatorGroupSpec(
        slug="turkish-airlines",
        name="Turkish Airlines",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Turkish Airlines", "Türk Hava Yolları"),
        callsigns=("THY",),
    ),
    # --------------------------------------------------- passenger, long-haul
    OperatorGroupSpec(
        slug="emirates",
        name="Emirates",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Emirates", "Emirates Airline"),
        callsigns=("UAE",),
    ),
    OperatorGroupSpec(
        slug="qatar-airways",
        name="Qatar Airways",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Qatar Airways",),
        callsigns=("QTR",),
    ),
    OperatorGroupSpec(
        slug="etihad",
        name="Etihad Airways",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Etihad Airways", "Etihad"),
        callsigns=("ETD",),
    ),
    OperatorGroupSpec(
        slug="singapore-airlines",
        name="Singapore Airlines",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Singapore Airlines",),
        callsigns=("SIA",),
    ),
    OperatorGroupSpec(
        slug="cathay-pacific",
        name="Cathay Pacific",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Cathay Pacific", "Cathay Pacific Airways"),
        callsigns=("CPA",),
    ),
    OperatorGroupSpec(
        slug="all-nippon-airways",
        name="All Nippon Airways",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("All Nippon Airways", "ANA"),
        callsigns=("ANA",),
    ),
    OperatorGroupSpec(
        slug="japan-airlines",
        name="Japan Airlines",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Japan Airlines",),
        callsigns=("JAL",),
    ),
    OperatorGroupSpec(
        slug="korean-air",
        name="Korean Air",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Korean Air", "Korean Air Lines"),
        callsigns=("KAL",),
    ),
    OperatorGroupSpec(
        slug="qantas",
        name="Qantas",
        kind=GroupKind.PASSENGER,
        mission=_PASSENGER,
        operators=("Qantas", "Qantas Airways"),
        callsigns=("QFA",),
    ),
    # ------------------------------------------------------------------- cargo
    OperatorGroupSpec(
        slug="fedex",
        name="FedEx Express",
        kind=GroupKind.CARGO,
        mission=_CARGO,
        operators=("FedEx", "FedEx Express", "Federal Express", "Federal Express Corp"),
        callsigns=("FDX",),
    ),
    OperatorGroupSpec(
        slug="ups",
        name="UPS Airlines",
        kind=GroupKind.CARGO,
        mission=_CARGO,
        operators=("UPS", "UPS Airlines", "United Parcel Service"),
        callsigns=("UPS",),
    ),
    OperatorGroupSpec(
        slug="dhl",
        name="DHL",
        kind=GroupKind.CARGO,
        mission=_CARGO,
        operators=("DHL", "DHL Air", "DHL Air UK", "European Air Transport"),
        callsigns=("DHK", "BCS"),
    ),
    OperatorGroupSpec(
        slug="atlas-air",
        name="Atlas Air",
        kind=GroupKind.CARGO,
        mission=_CARGO,
        operators=("Atlas Air", "Atlas Air Inc"),
        callsigns=("GTI",),
    ),
    OperatorGroupSpec(
        slug="polar-air-cargo",
        name="Polar Air Cargo",
        kind=GroupKind.CARGO,
        mission=_CARGO,
        operators=("Polar Air Cargo",),
        callsigns=("PAC",),
    ),
    OperatorGroupSpec(
        slug="kalitta",
        name="Kalitta Air",
        kind=GroupKind.CARGO,
        mission=_CARGO,
        operators=("Kalitta Air", "Kalitta Charters"),
        callsigns=("CKS",),
    ),
    OperatorGroupSpec(
        slug="abx-air",
        name="ABX Air",
        kind=GroupKind.CARGO,
        mission=_CARGO,
        operators=("ABX Air",),
        callsigns=("ABX",),
    ),
    OperatorGroupSpec(
        slug="air-transport-international",
        name="Air Transport International",
        kind=GroupKind.CARGO,
        mission=_CARGO,
        operators=("Air Transport International", "Air Transport Intl"),
        callsigns=("ATN",),
    ),
    OperatorGroupSpec(
        slug="cargolux",
        name="Cargolux",
        kind=GroupKind.CARGO,
        mission=_CARGO,
        operators=("Cargolux", "Cargolux Airlines International"),
        callsigns=("CLX",),
    ),
    OperatorGroupSpec(
        slug="western-global",
        name="Western Global Airlines",
        kind=GroupKind.CARGO,
        mission=_CARGO,
        operators=("Western Global Airlines",),
        callsigns=("WGN",),
    ),
    OperatorGroupSpec(
        slug="amerijet",
        name="Amerijet International",
        kind=GroupKind.CARGO,
        mission=_CARGO,
        operators=("Amerijet International", "Amerijet"),
        callsigns=("AJT",),
    ),
    # ---------------------------------------------------------------- military
    OperatorGroupSpec(
        slug="us-military",
        name="US Military",
        kind=GroupKind.MILITARY,
        mission=MissionCategory.MILITARY,
        military=True,
        operators=(
            "United States Air Force",
            "US Air Force",
            "USAF",
            "United States Navy",
            "US Navy",
            "United States Army",
            "US Army",
            "United States Marine Corps",
            "US Marine Corps",
            "United States Air National Guard",
            "Air National Guard",
            "Army National Guard",
        ),
    ),
    OperatorGroupSpec(
        slug="royal-air-force",
        name="Royal Air Force",
        kind=GroupKind.MILITARY,
        mission=MissionCategory.MILITARY,
        military=True,
        operators=("Royal Air Force", "RAF"),
    ),
    OperatorGroupSpec(
        slug="royal-navy",
        name="Royal Navy",
        kind=GroupKind.MILITARY,
        mission=MissionCategory.MILITARY,
        military=True,
        operators=("Royal Navy", "Royal Navy Fleet Air Arm"),
    ),
    OperatorGroupSpec(
        slug="german-air-force",
        name="German Air Force",
        kind=GroupKind.MILITARY,
        mission=MissionCategory.MILITARY,
        military=True,
        operators=("German Air Force", "Luftwaffe", "German Armed Forces"),
    ),
    OperatorGroupSpec(
        slug="french-air-force",
        name="French Air Force",
        kind=GroupKind.MILITARY,
        mission=MissionCategory.MILITARY,
        military=True,
        operators=("French Air Force", "Armee de l'Air", "Armée de l'Air"),
    ),
    OperatorGroupSpec(
        slug="royal-canadian-air-force",
        name="Royal Canadian Air Force",
        kind=GroupKind.MILITARY,
        mission=MissionCategory.MILITARY,
        military=True,
        operators=("Royal Canadian Air Force", "Canadian Armed Forces"),
    ),
    OperatorGroupSpec(
        slug="royal-australian-air-force",
        name="Royal Australian Air Force",
        kind=GroupKind.MILITARY,
        mission=MissionCategory.MILITARY,
        military=True,
        operators=("Royal Australian Air Force",),
    ),
    OperatorGroupSpec(
        slug="nato",
        name="NATO",
        kind=GroupKind.MILITARY,
        mission=MissionCategory.MILITARY,
        military=True,
        operators=("NATO", "NATO Airborne Early Warning Force"),
    ),
    # -------------------------------------------------------------- government
    OperatorGroupSpec(
        slug="nasa",
        name="NASA",
        kind=GroupKind.GOVERNMENT,
        mission=MissionCategory.GOVERNMENT,
        government=True,
        operators=("NASA", "National Aeronautics and Space Administration"),
    ),
    OperatorGroupSpec(
        slug="faa",
        name="Federal Aviation Administration",
        kind=GroupKind.GOVERNMENT,
        mission=MissionCategory.GOVERNMENT,
        government=True,
        operators=("Federal Aviation Administration", "FAA"),
    ),
    OperatorGroupSpec(
        slug="noaa",
        name="NOAA",
        kind=GroupKind.GOVERNMENT,
        mission=MissionCategory.GOVERNMENT,
        government=True,
        operators=("NOAA", "National Oceanic and Atmospheric Administration"),
    ),
    OperatorGroupSpec(
        slug="civil-air-patrol",
        name="Civil Air Patrol",
        kind=GroupKind.GOVERNMENT,
        mission=MissionCategory.GOVERNMENT,
        government=True,
        operators=("Civil Air Patrol",),
    ),
    OperatorGroupSpec(
        slug="us-coast-guard",
        name="US Coast Guard",
        kind=GroupKind.GOVERNMENT,
        mission=MissionCategory.GOVERNMENT,
        government=True,
        law_enforcement=True,
        operators=("United States Coast Guard", "US Coast Guard", "USCG", "Coast Guard"),
    ),
    OperatorGroupSpec(
        slug="government-agency",
        name="Government Agency",
        kind=GroupKind.GOVERNMENT,
        mission=MissionCategory.GOVERNMENT,
        government=True,
    ),
    # --------------------------------------------------------- law enforcement
    OperatorGroupSpec(
        slug="us-customs-border-protection",
        name="US Customs and Border Protection",
        kind=GroupKind.LAW_ENFORCEMENT,
        mission=MissionCategory.LAW_ENFORCEMENT,
        government=True,
        law_enforcement=True,
        operators=(
            "US Customs and Border Protection",
            "United States Customs and Border Protection",
            "Customs and Border Protection",
            "Department of Homeland Security",
            "US Department of Homeland Security",
        ),
    ),
    OperatorGroupSpec(
        slug="us-federal-law-enforcement",
        name="US Federal Law Enforcement",
        kind=GroupKind.LAW_ENFORCEMENT,
        mission=MissionCategory.LAW_ENFORCEMENT,
        government=True,
        law_enforcement=True,
        operators=(
            "Federal Bureau of Investigation",
            "FBI",
            "Drug Enforcement Administration",
            "US Marshals Service",
            "United States Marshals Service",
            "Bureau of Alcohol Tobacco Firearms and Explosives",
        ),
    ),
    OperatorGroupSpec(
        slug="police",
        name="Police / Law Enforcement",
        kind=GroupKind.LAW_ENFORCEMENT,
        mission=MissionCategory.LAW_ENFORCEMENT,
        government=True,
        law_enforcement=True,
        operators=("National Police Air Service", "Metropolitan Police"),
    ),
    # ----------------------------------------------------------------- medical
    OperatorGroupSpec(
        slug="air-methods",
        name="Air Methods",
        kind=GroupKind.MEDICAL,
        mission=MissionCategory.MEDICAL,
        operators=("Air Methods", "Air Methods Corporation", "Air Methods Corp"),
    ),
    OperatorGroupSpec(
        slug="phi-air-medical",
        name="PHI Air Medical",
        kind=GroupKind.MEDICAL,
        mission=MissionCategory.MEDICAL,
        operators=("PHI Air Medical", "PHI Health"),
    ),
    OperatorGroupSpec(
        slug="air-evac-lifeteam",
        name="Air Evac Lifeteam",
        kind=GroupKind.MEDICAL,
        mission=MissionCategory.MEDICAL,
        operators=("Air Evac Lifeteam", "Air Evac EMS"),
    ),
    OperatorGroupSpec(
        slug="metro-aviation",
        name="Metro Aviation",
        kind=GroupKind.MEDICAL,
        mission=MissionCategory.MEDICAL,
        operators=("Metro Aviation", "Metro Aviation Inc"),
    ),
    OperatorGroupSpec(
        slug="air-ambulance",
        name="Air Ambulance",
        kind=GroupKind.MEDICAL,
        mission=MissionCategory.MEDICAL,
    ),
    # ------------------------------------------------------------ firefighting
    OperatorGroupSpec(
        slug="us-forest-service",
        name="US Forest Service",
        kind=GroupKind.FIREFIGHTING,
        mission=MissionCategory.FIREFIGHTING,
        government=True,
        operators=("United States Forest Service", "US Forest Service", "Forest Service"),
    ),
    OperatorGroupSpec(
        slug="cal-fire",
        name="CAL FIRE",
        kind=GroupKind.FIREFIGHTING,
        mission=MissionCategory.FIREFIGHTING,
        government=True,
        operators=(
            "CAL FIRE",
            "California Department of Forestry and Fire Protection",
        ),
    ),
    OperatorGroupSpec(
        slug="coulson-aviation",
        name="Coulson Aviation",
        kind=GroupKind.FIREFIGHTING,
        mission=MissionCategory.FIREFIGHTING,
        operators=("Coulson Aviation", "Coulson Aviation USA"),
    ),
    OperatorGroupSpec(
        slug="neptune-aviation",
        name="Neptune Aviation Services",
        kind=GroupKind.FIREFIGHTING,
        mission=MissionCategory.FIREFIGHTING,
        operators=("Neptune Aviation Services", "Neptune Aviation"),
    ),
    OperatorGroupSpec(
        slug="aerial-firefighting",
        name="Aerial Firefighting",
        kind=GroupKind.FIREFIGHTING,
        mission=MissionCategory.FIREFIGHTING,
    ),
    # ------------------------------------------------------- business aviation
    OperatorGroupSpec(
        slug="netjets",
        name="NetJets",
        kind=GroupKind.OTHER,
        mission=MissionCategory.BUSINESS_AVIATION,
        operators=("NetJets", "NetJets Aviation", "NetJets Europe"),
        callsigns=("EJA", "NJE"),
    ),
    OperatorGroupSpec(
        slug="flexjet",
        name="Flexjet",
        kind=GroupKind.OTHER,
        mission=MissionCategory.BUSINESS_AVIATION,
        operators=("Flexjet",),
        callsigns=("LXJ",),
    ),
    OperatorGroupSpec(
        slug="vistajet",
        name="VistaJet",
        kind=GroupKind.OTHER,
        mission=MissionCategory.BUSINESS_AVIATION,
        operators=("VistaJet",),
        callsigns=("VJT",),
    ),
    # ---------------------------------------------------------------- training
    OperatorGroupSpec(
        slug="flight-training",
        name="Flight Training",
        kind=GroupKind.OTHER,
        mission=MissionCategory.TRAINING,
    ),
)

#: Phrases that identify a group without naming an operator. Ordered: the first
#: match wins, so the more specific phrase must come first where two could
#: both apply to one name.
OPERATOR_PATTERNS: Final[tuple[OperatorPattern, ...]] = (
    # Law enforcement. Never inferred from a callsign — only from a name that
    # says so in words (see the engine's rules).
    OperatorPattern("border protection", "us-customs-border-protection"),
    OperatorPattern("border patrol", "us-customs-border-protection"),
    OperatorPattern("police", "police"),
    OperatorPattern("sheriff", "police"),
    OperatorPattern("state patrol", "police"),
    OperatorPattern("highway patrol", "police"),
    OperatorPattern("constabulary", "police"),
    OperatorPattern("gendarmerie", "police"),
    OperatorPattern("polizei", "police"),
    # Medical.
    OperatorPattern("air ambulance", "air-ambulance"),
    OperatorPattern("air medical", "air-ambulance"),
    OperatorPattern("life flight", "air-ambulance"),
    OperatorPattern("lifeflight", "air-ambulance"),
    OperatorPattern("medevac", "air-ambulance"),
    OperatorPattern("med flight", "air-ambulance"),
    OperatorPattern("medical center", "air-ambulance"),
    OperatorPattern("lifenet", "air-ambulance"),
    # Firefighting.
    OperatorPattern("forest service", "us-forest-service"),
    OperatorPattern("fire department", "aerial-firefighting"),
    OperatorPattern("fire district", "aerial-firefighting"),
    OperatorPattern("fire rescue", "aerial-firefighting"),
    OperatorPattern("air tanker", "aerial-firefighting"),
    OperatorPattern("aerial firefighting", "aerial-firefighting"),
    # Government.
    OperatorPattern("department of transportation", "government-agency"),
    OperatorPattern("department of natural resources", "government-agency"),
    OperatorPattern("geological survey", "government-agency"),
    # Training.
    OperatorPattern("flight school", "flight-training"),
    OperatorPattern("flight training", "flight-training"),
    OperatorPattern("flight academy", "flight-training"),
    OperatorPattern("aviation academy", "flight-training"),
)

__all__ = ["OPERATOR_GROUPS", "OPERATOR_PATTERNS"]
