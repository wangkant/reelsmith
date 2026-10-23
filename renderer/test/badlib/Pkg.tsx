// Test: a package outside the allowed list must fail the bundle.
import React from "react";
import { flushSync } from "react-dom";

export default function Pkg() {
  return <div>{typeof flushSync}</div>;
}
