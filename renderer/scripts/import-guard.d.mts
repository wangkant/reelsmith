export declare function importGuard(opts: { root: string; library: string; warn?: (msg: string) => void }): {
  apply(compiler: unknown): void;
};
export declare function narrowContexts(folders: Array<{ dir: string; names: string[] }>): { apply(compiler: unknown): void };
