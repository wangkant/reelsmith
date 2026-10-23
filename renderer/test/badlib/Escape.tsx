// Test: a library component reaching outside its folder must fail the bundle.
import React from "react";
import { SANS } from "../../src/fonts";

export default function Escape() {
  return <div style={{ fontFamily: SANS }}>escape</div>;
}
