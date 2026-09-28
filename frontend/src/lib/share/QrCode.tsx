/**
 * A QR code of `value` (roadmap slice 082's "moving a view from a wall
 * screen to a phone"), drawn as inline SVG from `qrcode-generator`
 * (MIT-licensed, zero runtime dependencies — see `docs/LICENSES.md`) rather
 * than that package's own `createSvgTag`/`createImgTag` string builders, so
 * the markup stays real React elements with a proper `role="img"` and
 * `aria-label` instead of `dangerouslySetInnerHTML`.
 *
 * Always rendered black-on-white regardless of the app's own theme — the
 * one place FlightSite deliberately ignores dark mode, since a dark-mode
 * inverted code is harder for some phone cameras to lock onto and there is
 * no benefit to matching the surrounding chrome for something meant to be
 * photographed.
 */
import qrcode from "qrcode-generator";
import { useMemo } from "react";

export interface QrCodeProps {
  value: string;
  /** Rendered size in CSS pixels (square). */
  size?: number;
  className?: string;
}

const DEFAULT_SIZE = 176;

export function QrCode({ value, size = DEFAULT_SIZE, className }: QrCodeProps) {
  const { moduleCount, isDark } = useMemo(() => {
    // Type number 0 lets the library pick the smallest version that fits
    // `value`; "M" (~15% error correction) is the library's own documented
    // default and plenty for a URL this short.
    const code = qrcode(0, "M");
    code.addData(value);
    code.make();
    return { moduleCount: code.getModuleCount(), isDark: code.isDark };
  }, [value]);

  const modules: { row: number; col: number }[] = [];
  for (let row = 0; row < moduleCount; row += 1) {
    for (let col = 0; col < moduleCount; col += 1) {
      if (isDark(row, col)) {
        modules.push({ row, col });
      }
    }
  }

  return (
    <svg
      role="img"
      aria-label={`QR code encoding ${value}`}
      viewBox={`0 0 ${moduleCount} ${moduleCount}`}
      width={size}
      height={size}
      className={className}
      style={{ backgroundColor: "#fff" }}
    >
      <rect x={0} y={0} width={moduleCount} height={moduleCount} fill="#fff" />
      <g fill="#000">
        {modules.map(({ row, col }) => (
          <rect key={`${row}-${col}`} x={col} y={row} width={1} height={1} />
        ))}
      </g>
    </svg>
  );
}
