import type { ReactNode } from 'react';
import { cn } from '../utils';

export interface DataTableColumn<T> {
  readonly key: string;
  readonly header: string;
  readonly width?: string;
  readonly render: (row: T) => ReactNode;
  readonly align?: 'left' | 'right' | 'center';
}

interface DataTableProps<T> {
  readonly rows: readonly T[];
  readonly columns: readonly DataTableColumn<T>[];
  readonly rowKey: (row: T) => string;
  readonly onRowClick?: (row: T) => void;
  readonly emptyLabel?: string;
  readonly className?: string;
}

/**
 * Dense forensic table.
 *
 * The caller is responsible for deterministic ordering of `rows` — typically
 * via the `chronological` / `stableSortBy` helpers in `@operious/shared`.
 * We never sort here implicitly.
 */
export const DataTable = <T,>({
  rows,
  columns,
  rowKey,
  onRowClick,
  emptyLabel = 'No records observed.',
  className,
}: DataTableProps<T>) => (
  <div className={cn('overflow-x-auto rounded-md border border-line', className)}>
    <table className="min-w-full text-sm">
      <thead className="bg-bg-inset border-b border-line">
        <tr>
          {columns.map((col) => (
            <th
              key={col.key}
              scope="col"
              style={col.width ? { width: col.width } : undefined}
              className={cn(
                'px-3 py-2 text-left font-mono text-2xs uppercase tracking-wider text-fg-subtle',
                col.align === 'right' && 'text-right',
                col.align === 'center' && 'text-center',
              )}
            >
              {col.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr>
            <td
              colSpan={columns.length}
              className="px-3 py-6 text-center text-fg-subtle text-mono"
            >
              {emptyLabel}
            </td>
          </tr>
        ) : (
          rows.map((row) => {
            const key = rowKey(row);
            const baseRowClasses =
              'border-b border-line/60 hover:bg-bg-raised/60 transition-colors';
            const rowProps = onRowClick
              ? {
                  role: 'button' as const,
                  tabIndex: 0,
                  onClick: () => onRowClick(row),
                  onKeyDown: (event: React.KeyboardEvent<HTMLTableRowElement>) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      onRowClick(row);
                    }
                  },
                  className: cn(baseRowClasses, 'cursor-pointer'),
                }
              : { className: baseRowClasses };
            return (
              <tr key={key} {...rowProps}>
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={cn(
                      'px-3 py-2 align-top text-fg',
                      col.align === 'right' && 'text-right',
                      col.align === 'center' && 'text-center',
                    )}
                  >
                    {col.render(row)}
                  </td>
                ))}
              </tr>
            );
          })
        )}
      </tbody>
    </table>
  </div>
);
