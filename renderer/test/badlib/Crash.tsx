// Test: a component that throws while rendering must be reported as a crash with its source line.
import React from "react";

export default function Crash({ props }: { props: any }) {
  return <div style={{ fontSize: 60 }}>{props.missing.deep.value}</div>;
}
