import { requireNavItem } from "@/components/shell/nav-items";
import { PlaceholderPage } from "@/pages/PlaceholderPage";

const item = requireNavItem("/aircraft");

export function AircraftPage() {
  return <PlaceholderPage title={item.label} description={item.description} />;
}
