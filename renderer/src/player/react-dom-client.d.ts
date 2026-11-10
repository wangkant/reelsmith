// The part of react-dom/client the player uses (the renderer has no @types/react-dom).
declare module "react-dom/client" {
  import type { ReactNode } from "react";

  type ErrorInfo = { componentStack?: string };
  export type RootOptions = {
    onCaughtError?: (error: unknown, info: ErrorInfo) => void;
    onUncaughtError?: (error: unknown, info: ErrorInfo) => void;
  };
  export type Root = { render(children: ReactNode): void; unmount(): void };
  export function createRoot(container: Element, options?: RootOptions): Root;
}
