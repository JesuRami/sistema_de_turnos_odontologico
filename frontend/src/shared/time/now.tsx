/** Reloj inyectable para la UI: los tests fijan "ahora" sin tocar el reloj global. */
import { createContext, useContext, type ReactNode } from "react";

export type Clock = () => Date;

const NowContext = createContext<Clock>(() => new Date());

export function NowProvider({ clock, children }: { clock: Clock; children: ReactNode }): JSX.Element {
  return <NowContext.Provider value={clock}>{children}</NowContext.Provider>;
}

export function useClock(): Clock {
  return useContext(NowContext);
}
