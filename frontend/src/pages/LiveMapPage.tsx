import { requireNavItem } from "@/components/shell/nav-items";
import { PlaceholderPage } from "@/pages/PlaceholderPage";

const item = requireNavItem("/");

export function LiveMapPage() {
  return <PlaceholderPage title={item.label} description={item.description} />;
}
