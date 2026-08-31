import { requireNavItem } from "@/components/shell/nav-items";
import { PlaceholderPage } from "@/pages/PlaceholderPage";

const item = requireNavItem("/settings");

export function SettingsPage() {
  return <PlaceholderPage title={item.label} description={item.description} />;
}
