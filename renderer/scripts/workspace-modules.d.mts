export declare function workspaceModules(opts: { root: string; library: string; workspace?: string | null }): {
  alias: Record<string, string>;
  rules: object[];
};
