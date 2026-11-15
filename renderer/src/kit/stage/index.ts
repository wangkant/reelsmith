// The stage kit: performance scenes in which drawn things and torn photo cut-outs act the narration out.
export {
  backOut, boil, clamp01, cues, in2, inOut, lerp, out3, prog, spr, step, swing, useCues, win, wob,
} from "./time";
export type { CueLine, Cues } from "./time";
export { along, bbox, blob, circle, fibre, mixColor, rect, roughRect, seedInt, smooth, smoothClosed, torn } from "./geom";
export type { Pt } from "./geom";
export { PALETTE, PaletteContext, shades, shadowCss, useFilters, usePalette, useUnit } from "./palette";
export type { Palette } from "./palette";
export { camAt, Grain, Layer, Stage, useStage } from "./Stage";
export type { Cam, Key, StageProps } from "./Stage";
export { KraftGround, TableTop, WallGround } from "./grounds";
export type { TableTopProps, WallGroundProps } from "./grounds";
export { Actor, Cut, Loupe, Magnifier, toCanvas } from "./actors";
export type { ActorProps, CutProps, Entrance, Exit, LoupeProps, MagnifierProps, Placed } from "./actors";
export { Card, Label, Stamp, Tag, Tape } from "./paper";
export type { CardProps, LabelProps, StampProps, TagProps } from "./paper";
export { ArrowInk, CircleIt, Highlighter, Marker, Stroke } from "./ink";
export type { ArrowInkProps, CircleItProps, MarkerProps, StrokeProps } from "./ink";
export { Drips, Mist, Sparks, Wisps } from "./fx";
export type { DripsProps, MistProps, SparksProps, WispsProps } from "./fx";
export { Car, Doc, Hand, Note, Parcel, Phone, Shelf, shelfBoards, Sign, Slab, Wheel } from "./things";
export type { CarProps, DocProps, HandPose, HandProps, NoteProps, ParcelProps, PhoneProps, ShelfProps, SignProps, SlabProps, WheelProps } from "./things";
