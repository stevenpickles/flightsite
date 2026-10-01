/**
 * Copies `text` to the clipboard (roadmap slice 082's Copy link button),
 * preferring the async Clipboard API and falling back to the deprecated
 * `execCommand` path for a browser or context that does not expose it. SPEC
 * §75's no-auth, plain-LAN deployment is exactly the kind of non-HTTPS
 * context where `navigator.clipboard` can be entirely absent — Chromium and
 * most browsers gate it behind a secure context (HTTPS or `localhost`), and
 * a self-hosted receiver at a bare LAN IP is neither.
 *
 * Returns whether the copy is believed to have succeeded; neither path can
 * truly confirm the text landed on the OS clipboard, only that the browser
 * did not report a failure.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (
    typeof navigator !== "undefined" &&
    navigator.clipboard &&
    typeof navigator.clipboard.writeText === "function"
  ) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Falls through to the legacy path below — a permissions-policy block
      // or an insecure context can reject the promise even though the API
      // object is present.
    }
  }

  if (typeof document === "undefined") {
    return false;
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  // Off-screen rather than `display: none` — some browsers refuse to select
  // text in a non-rendered element.
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  textarea.style.pointerEvents = "none";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);

  let succeeded: boolean;
  try {
    succeeded = document.execCommand("copy");
  } catch {
    succeeded = false;
  }
  document.body.removeChild(textarea);
  return succeeded;
}
