import type { ReactNode } from "react";

import { EmptyState } from "../pages/EmptyState";

type PageStateProps = {
  loading: boolean;
  error: string | null;
  empty: boolean;
  emptyTitle: string;
  onRefresh: () => void;
  children: ReactNode;
};

export function PageState({
  loading,
  error,
  empty,
  emptyTitle,
  onRefresh,
  children
}: PageStateProps) {
  if (loading) {
    return <div className="state-box">Cargando datos...</div>;
  }

  if (error) {
    return (
      <div className="state-box error">
        <strong>No se pudieron cargar los datos</strong>
        <span>{error}</span>
        <button type="button" className="secondary-button" onClick={onRefresh}>
          Reintentar
        </button>
      </div>
    );
  }

  if (empty) {
    return <EmptyState title={emptyTitle} />;
  }

  return <>{children}</>;
}
