// Map view (Leaflet + OpenStreetMap tiles). Loaded only when the map is opened.

import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { type Card, esc, facts, formatPrice, place, safeUrl } from "./logic";
import { COPY } from "./view";

let map: L.Map | null = null;
let layer: L.LayerGroup | null = null;

export function renderMap(container: HTMLElement, cards: Card[]): void {
  if (!map || !container.contains(map.getContainer())) {
    container.innerHTML = `<div id="map" class="map"></div>`;
    map = L.map("map", { zoomControl: true }).setView([36.84, -2.46], 11);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "© OpenStreetMap",
    }).addTo(map);
    layer = L.layerGroup().addTo(map);
  }
  layer?.clearLayers();
  const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
  const points: L.LatLngExpression[] = [];
  for (const card of cards) {
    if (!card.point) continue;
    const [lat, lng] = card.point;
    points.push([lat, lng]);
    L.circleMarker([lat, lng], {
      radius: 8,
      color: "#fff",
      weight: 2,
      fillColor: accent || "#b4431c",
      fillOpacity: 0.9,
    })
      .bindPopup(
        `<b class="price">${formatPrice(card.main.price_eur)}</b><br>${esc(facts(card.main))}<br>` +
          `${esc(place(card.main))}<br><a href="${safeUrl(card.main.url)}" target="_blank" ` +
          `rel="noopener noreferrer">${COPY.openListing} →</a>`,
      )
      .addTo(layer as L.LayerGroup);
  }
  if (points.length) map.fitBounds(L.latLngBounds(points), { padding: [24, 24], maxZoom: 14 });
}
