/**
 * A compact ranked table for the "Top …" cards (SPEC §58, slice 095).
 *
 * The three rankings used to be horizontal bar charts, which spent most of a
 * narrow card on bars that said "4, 4, 4, 4, 3" and left the identity — the
 * type's name, who flies it — to a tooltip. A ranking of ten rows is a list,
 * and the figures the owner reads are the names and the count, so this is a
 * plain table: the rows are already sorted by the backend, the count sits in
 * a right-aligned tabular-figure column, and each text cell truncates with
 * its full text on `title`, so a long model or operator name never pushes
 * the card wider than its grid column.
 *
 * Fixed table layout with percentage widths is what makes truncation work:
 * an auto-layout table grows a column to fit its widest cell and the
 * ellipsis never fires.
 */
import type { ReactNode } from "react";

export interface RankingColumn<Row> {
  /** Stable key for React and the header cell. */
  key: string;
  heading: string;
  /** Percentage of the table's width. The columns should sum to 100. */
  width: number;
  align?: "left" | "right";
  render: (row: Row) => ReactNode;
}

export interface RankingTableProps<Row> {
  columns: ReadonlyArray<RankingColumn<Row>>;
  rows: ReadonlyArray<Row>;
  rowKey: (row: Row) => string;
  emptyLabel: string;
  /** Names the table for assistive technology — e.g. "Top aircraft by
   * sightings". */
  ariaLabel: string;
}

/** A single truncating line with the whole text on hover. */
export function Truncated({
  text,
  className = "",
}: {
  text: string;
  className?: string;
}) {
  return (
    <span className={`block truncate ${className}`} title={text}>
      {text}
    </span>
  );
}

export function RankingTable<Row>({
  columns,
  rows,
  rowKey,
  emptyLabel,
  ariaLabel,
}: RankingTableProps<Row>) {
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">{emptyLabel}</p>;
  }
  return (
    <table className="w-full table-fixed text-sm" aria-label={ariaLabel}>
      <colgroup>
        {columns.map((column) => (
          <col key={column.key} style={{ width: `${column.width}%` }} />
        ))}
      </colgroup>
      <thead>
        <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
          {columns.map((column) => (
            <th
              key={column.key}
              scope="col"
              className={`py-1 pr-2 font-semibold last:pr-0 ${
                column.align === "right" ? "text-right" : ""
              }`}
            >
              {column.heading}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={rowKey(row)} className="border-t border-border/60">
            {columns.map((column) => (
              <td
                key={column.key}
                className={`py-1.5 pr-2 align-top last:pr-0 ${
                  column.align === "right"
                    ? "text-right tabular-nums"
                    : "min-w-0"
                }`}
              >
                {column.render(row)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
