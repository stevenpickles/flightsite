/**
 * Whether keyboard shortcuts should be suspended because `target` is where
 * someone is typing (roadmap slice 082, SPEC §80's keyboard-navigation
 * baseline). A bare `L` keystroke toggling the Layers card while it is
 * actually the fourth letter typed into the live-search field would corrupt
 * what the user is typing, not drive the map.
 */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  if (target.isContentEditable) {
    return true;
  }
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}
