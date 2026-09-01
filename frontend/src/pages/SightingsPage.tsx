import { requireNavItem } from "@/components/shell/nav-items";
import { PlaceholderPage } from "@/pages/PlaceholderPage";

const item = requireNavItem("/sightings");

export function SightingsPage() {
  return <PlaceholderPage title={item.label} description={item.description} />;
}
