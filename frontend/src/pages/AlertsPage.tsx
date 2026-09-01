import { requireNavItem } from "@/components/shell/nav-items";
import { PlaceholderPage } from "@/pages/PlaceholderPage";

const item = requireNavItem("/alerts");

export function AlertsPage() {
  return <PlaceholderPage title={item.label} description={item.description} />;
}
