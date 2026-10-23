// Test: a node built-in must be refused by name, not with a webpack resolve trace.
import React from "react";
import fs from "fs";

export default function UsesFs() {
  return <div>{typeof fs}</div>;
}
