/**
 * Copy link / `navigator.share` / QR popover — the sharing surface roadmap
 * slice 082 adds to the aircraft detail route, the sighting detail route,
 * and the Live Map's aircraft detail panel (where the URL already carries
 * `?selected=`, kept in sync by `useSelectionUrlSync`). One component, three
 * call sites, so "share" means the same three actions and the same copy
 * everywhere a view can be shared, and a copied or scanned link reopens
 * exactly the view it was copied from (the acceptance criterion issue #225
 * states) — `url` is simply whatever the caller's own `useCurrentUrl` call
 * already resolved to.
 *
 * The QR popover mirrors `ConfirmDangerDialog`'s hand-rolled overlay shape
 * (this project ships no dialog primitive): `role="dialog"`, a non-modal
 * focus move via `useDialogFocus`, and Escape scoped to the panel itself via
 * `onKeyDown` + `stopPropagation` — never a `window` listener, which would
 * also reach `AircraftDetailPanel`'s own Escape handler and deselect the
 * aircraft this popover is busy showing a QR code for.
 */
import { Check, Copy, QrCode as QrCodeIcon, Share2 } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { useDialogFocus } from "@/lib/a11y/useDialogFocus";
import { copyToClipboard } from "@/lib/share/clipboard";
import { QrCode } from "@/lib/share/QrCode";
import { cn } from "@/lib/utils";

export interface ShareControlsProps {
  /** The absolute URL to share — see `useCurrentUrl`. */
  url: string;
  /** Passed to `navigator.share` and shown as the QR popover's heading. */
  title: string;
  className?: string;
}

type CopyStatus = "idle" | "copied" | "failed";

/** How long "Copied" (or the failure notice) stays announced before
 * resetting to idle — long enough to read, short enough that a second copy
 * moments later is not mistaken for a stale announcement. */
const STATUS_RESET_MS = 2000;

function supportsWebShare(): boolean {
  return (
    typeof navigator !== "undefined" && typeof navigator.share === "function"
  );
}

export function ShareControls({ url, title, className }: ShareControlsProps) {
  const [copyStatus, setCopyStatus] = useState<CopyStatus>("idle");
  const [qrOpen, setQrOpen] = useState(false);
  const resetTimeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const headingId = useId();
  // Non-modal: this is a small popover next to its own trigger button, not a
  // page-blocking dialog — the map or page behind it stays interactive.
  const panelRef = useDialogFocus<HTMLDivElement>({ open: qrOpen });

  useEffect(() => {
    return () => {
      if (resetTimeoutRef.current !== undefined) {
        clearTimeout(resetTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (qrOpen) {
      panelRef.current?.focus();
    }
  }, [qrOpen, panelRef]);

  async function handleCopy() {
    const succeeded = await copyToClipboard(url);
    setCopyStatus(succeeded ? "copied" : "failed");
    if (resetTimeoutRef.current !== undefined) {
      clearTimeout(resetTimeoutRef.current);
    }
    resetTimeoutRef.current = setTimeout(() => {
      setCopyStatus("idle");
    }, STATUS_RESET_MS);
  }

  function handleShare() {
    // `navigator.share` rejects with `AbortError` when the user cancels the
    // OS share sheet — a normal outcome, not a failure worth surfacing.
    navigator.share({ title, url }).catch(() => {});
  }

  return (
    <div className={cn("relative inline-flex items-center gap-1", className)}>
      <button
        type="button"
        onClick={() => void handleCopy()}
        className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs font-medium text-muted-foreground outline-none transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        {copyStatus === "copied" ? (
          <Check className="size-3.5" aria-hidden="true" />
        ) : (
          <Copy className="size-3.5" aria-hidden="true" />
        )}
        Copy link
      </button>
      {/* Announced, not shown as separate text — the icon swap above already
       * carries the state visually (SPEC §80: text/icon, not colour alone). */}
      <span role="status" aria-live="polite" className="sr-only">
        {copyStatus === "copied" && "Link copied"}
        {copyStatus === "failed" &&
          "Could not copy the link automatically — copy it from the address bar instead."}
      </span>

      {supportsWebShare() && (
        <button
          type="button"
          onClick={handleShare}
          className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs font-medium text-muted-foreground outline-none transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          <Share2 className="size-3.5" aria-hidden="true" />
          Share
        </button>
      )}

      <button
        type="button"
        onClick={() => setQrOpen((open) => !open)}
        aria-expanded={qrOpen}
        aria-controls={qrOpen ? headingId : undefined}
        className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs font-medium text-muted-foreground outline-none transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        <QrCodeIcon className="size-3.5" aria-hidden="true" />
        QR code
      </button>

      {qrOpen && (
        <div
          ref={panelRef}
          id={headingId}
          role="dialog"
          aria-modal="false"
          aria-label={`QR code for ${title}`}
          tabIndex={-1}
          className="absolute right-0 top-full z-30 mt-1 flex flex-col items-center gap-2 rounded-lg border border-border bg-card p-3 text-card-foreground shadow-lg outline-none"
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.stopPropagation();
              setQrOpen(false);
            }
          }}
        >
          <QrCode value={url} />
          <p className="max-w-[11rem] text-center text-[11px] text-muted-foreground">
            Scan to open this view on another device.
          </p>
          <button
            type="button"
            onClick={() => setQrOpen(false)}
            className="text-xs font-medium text-accent outline-none hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            Close
          </button>
        </div>
      )}
    </div>
  );
}
