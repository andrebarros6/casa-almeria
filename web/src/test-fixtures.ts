import type { Listing, Reaction } from "./logic";

// Shared test data builders (imported by the *.test.ts files).

export function listing(over: Partial<Listing> = {}): Listing {
  return {
    id: "pisos:1",
    source: "pisos",
    source_id: "1",
    url: "https://www.pisos.com/x/",
    title: "Piso en Zapillo",
    description: "",
    price_eur: 850,
    bedrooms: 3,
    bathrooms: 1,
    area_m2: 95,
    floor: 4,
    property_type: "flat",
    municipality: "Almería",
    neighbourhood: "Zapillo",
    area_key: "almeria_city",
    lat: 36.83,
    lng: -2.44,
    photos: ["https://img/1.jpg"],
    features: ["elevator", "ac"],
    published_at: null,
    is_temporary: false,
    features_known: true,
    first_seen: "2026-11-24T07:00:00Z",
    last_seen: "2026-11-25T07:00:00Z",
    gone: false,
    group_id: "pisos:1",
    rejected_reason: null,
    price_history: [{ at: "2026-11-24T07:00:00Z", price_eur: 850 }],
    commute_min: null,
    ...over,
  };
}

export function reaction(over: Partial<Reaction> = {}): Reaction {
  return {
    group_id: "pisos:1",
    user_email: "me@x.pt",
    reaction: "like",
    note: null,
    updated_at: "2026-11-25T08:00:00Z",
    ...over,
  };
}
