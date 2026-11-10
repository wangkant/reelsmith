// Test: "react/../.." must not reach other installed packages.
import React from "react";
import * as RD from "react/../../react-dom/server.browser";

export default function DotDot() {
  return <div>{typeof RD}</div>;
}
