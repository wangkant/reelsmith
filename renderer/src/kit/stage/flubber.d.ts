// The part of flubber the kit uses (the package ships no types).
declare module "flubber" {
  export function interpolate(from: string, to: string, options?: { maxSegmentLength?: number; string?: boolean }): (t: number) => string;
}
