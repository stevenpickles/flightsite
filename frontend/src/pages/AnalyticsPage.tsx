import { requireNavItem } from "@/components/shell/nav-items";
import { PlaceholderPage } from "@/pages/PlaceholderPage";

const item = requireNavItem("/analytics");

export function AnalyticsPage() {
  return <PlaceholderPage title={item.label} description={item.description} />;
}
