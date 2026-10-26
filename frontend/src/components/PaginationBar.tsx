type PaginationBarProps = {
  total: number;
  limit: number;
  offset: number;
  onPageChange: (offset: number, limit?: number) => void;
  noun: string;
};

export function PaginationBar({ total, limit, offset, onPageChange, noun }: PaginationBarProps) {
  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + limit, total);
  return (
    <div className="pagination-bar">
      <span>{first}–{last} de {total} {noun}</span>
      <label>Por página <select className="text-input page-size-select" value={limit} onChange={(event) => onPageChange(0, Number(event.target.value))}><option value={25}>25</option><option value={50}>50</option></select></label>
      <div className="header-actions">
        <button type="button" className="secondary-button" disabled={offset === 0} onClick={() => onPageChange(Math.max(0, offset - limit))}>Anterior</button>
        <button type="button" className="secondary-button" disabled={offset + limit >= total} onClick={() => onPageChange(offset + limit)}>Siguiente</button>
      </div>
    </div>
  );
}
