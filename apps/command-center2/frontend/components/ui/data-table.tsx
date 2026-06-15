import { Fragment, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export type DataTableColumn<T> = {
  key: string;
  header: string;
  /** Tailwind width class, e.g. "w-[160px]" or "min-w-[260px] flex-1". */
  width?: string;
  align?: "left" | "right" | "center";
  /** Right-aligns and applies tabular figures for numeric/ID-like values. */
  numeric?: boolean;
  render: (row: T) => ReactNode;
};

/**
 * Reusable table shell for the calm dashboard design system. Renders an
 * Inter-typeface `cc-table` with consistent column widths and an optional
 * numeric/tabular treatment per column, so individual screens only need to
 * describe their columns and rows.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  className,
  minWidth = "720px",
  expandedRowId,
  renderExpanded,
}: {
  columns: DataTableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  className?: string;
  minWidth?: string;
  /** Key of the row currently expanded via `renderExpanded`, if any. */
  expandedRowId?: string | null;
  /** Renders an inline detail panel (e.g. a technical-details disclosure) below the matching row. */
  renderExpanded?: (row: T) => ReactNode;
}) {
  return (
    <div className={cn("overflow-x-auto", className)}>
      <table className="cc-table" style={{ minWidth }}>
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                className={cn(
                  column.width,
                  column.align === "right" && "text-right",
                  column.align === "center" && "text-center"
                )}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const key = rowKey(row);
            const isExpanded = renderExpanded && expandedRowId === key;
            return (
              <Fragment key={key}>
                <tr>
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      className={cn(
                        column.width,
                        column.numeric && "tabular",
                        (column.align === "right" || column.numeric) && "text-right",
                        column.align === "center" && "text-center"
                      )}
                    >
                      {column.render(row)}
                    </td>
                  ))}
                </tr>
                {isExpanded && (
                  <tr>
                    <td colSpan={columns.length} className="bg-surface-raised">
                      {renderExpanded(row)}
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
