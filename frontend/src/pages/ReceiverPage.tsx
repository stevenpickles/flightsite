import { requireNavItem } from "@/components/shell/nav-items";
import { PlaceholderPage } from "@/pages/PlaceholderPage";

const item = requireNavItem("/receiver");

export function ReceiverPage() {
  return <PlaceholderPage title={item.label} description={item.description} />;
}
