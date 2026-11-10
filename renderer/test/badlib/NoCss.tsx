// Test: a stylesheet that is not there is left out of the player, not the whole build.
import React from "react";
import "./missing.css";

export default function NoCss() {
  return <div>no css</div>;
}
