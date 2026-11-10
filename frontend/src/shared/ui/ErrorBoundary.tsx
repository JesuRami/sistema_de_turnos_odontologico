/**
 * Límite de errores de render de la app (C-14, D11): un bug en una pantalla no deja la SPA en
 * blanco. Muestra un mensaje genérico (nunca el stack ni datos del paciente) y ofrece recargar.
 */
import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** Para tests: qué hacer al pedir recargar (por defecto, `location.reload`). */
  onReload?: () => void;
  onError?: (error: Error, info: ErrorInfo) => void;
}

interface State {
  failed: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Solo el tipo: el mensaje de un error de render puede traer datos de la pantalla.
    this.props.onError?.(error, info);
    console.error(`render_error ${error.name}`);
  }

  private reload = (): void => {
    if (this.props.onReload !== undefined) {
      this.props.onReload();
      return;
    }
    window.location.reload();
  };

  render(): ReactNode {
    if (!this.state.failed) {
      return this.props.children;
    }
    return (
      <div role="alert" className="mx-auto mt-16 max-w-md rounded-lg border border-rose-300 bg-rose-50 p-6 text-rose-900">
        <h1 className="text-lg font-semibold">Algo salió mal</h1>
        <p className="mt-2 text-sm">
          La pantalla tuvo un error inesperado. Tus datos están guardados en el servidor; recargá para seguir.
        </p>
        <button
          type="button"
          onClick={this.reload}
          className="mt-4 rounded bg-rose-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-rose-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-700"
        >
          Recargar
        </button>
      </div>
    );
  }
}
