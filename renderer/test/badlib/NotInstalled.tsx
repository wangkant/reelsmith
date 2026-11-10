// Test: an allowed scope whose package is not installed is left out of the player, not the whole build.
import React from "react";
import x from "@remotion/not-installed";

export default function NotInstalled() {
  return <div>{String(x)}</div>;
}
