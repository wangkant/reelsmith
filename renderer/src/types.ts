// The renderer's input: build/resolved.json (contract section 7). Times are frames unless a field says seconds.

export type Box = { x: number; y: number; w: number; h: number };

export type Theme = {
  paper: string;
  ink: string;
  night: string;
  snow: string;
  accent: string;
  gold: string;
  good: string;
  bad: string;
  muted: string;
  name?: string;
};

export type Ease = "linear" | "in" | "out" | "inOut" | "spring" | "step";

/** `f`: frames from the clip's start. The ease shapes the move INTO this keyframe from the previous one. */
export type Keyframe = { f: number; v: number; ease?: Ease | null };

export type KeyframeProp =
  | "x" | "y" | "w" | "h" | "opacity" | "rotate" | "scale" | "blur" | "brightness" | "zoom" | "pan_x" | "pan_y" | "progress";

export type Preset = "fade" | "rise" | "drop" | "pop" | "wipe_left" | "wipe_up" | "zoom";

export type Transition = { preset: Preset; dur: number };

export type CutType = "crossfade" | "dip_black" | "dip_white" | "wipe_left" | "wipe_right" | "wipe_up" | "slide_left" | "zoom";

/** The clip's transition in from the clip before it on its track, over its first `dur` frames (it paints on top). */
export type CutIn = { type: CutType; dur: number; from: string | null };

/** The same transition seen from the clip it leaves: it starts `at` frames into this clip. */
export type CutOut = { type: CutType; dur: number; at: number; to: string };

export type FilterSpec = { blur?: number; brightness?: number; contrast?: number; saturate?: number; grayscale?: number };

export type ClipStyle = {
  opacity?: number;
  rotate?: number;
  scale?: number;
  origin?: string;
  radius?: number;
  blend?: string;
  filter?: FilterSpec | null;
  shadow?: boolean | string | null;
};

export type Run = { text: string; accent?: boolean };

/** A run as the text elements draw it: `o` is an opacity (captions in "build" mode hide words not said yet). */
export type DrawnRun = Run & { o?: number };

export type TextStyle = {
  font: string;
  size: number | "fit";
  max_size: number;
  min_size: number;
  weight: number;
  color: string | null;
  accent: string | null;
  align: "left" | "center" | "right";
  valign: "top" | "middle" | "bottom";
  line_height: number;
  letter_spacing: number;
  wrap: boolean;
  balance: boolean;
  stroke: { color?: string; width?: number } | null;
  shadow: boolean | string;
  bg: { color?: string; radius?: number; pad?: number } | null;
};

/** `dur` is in seconds (passed through from project.json). */
export type Reveal = { mode: "chars" | "words" | "lines" | "none"; dur?: number | null };

/** An asset as components receive it (contract 3.3) and as media elements take it. */
export type MediaRef = {
  src: string;
  kind?: string;
  size?: [number, number] | null;
  box?: [number, number, number, number] | null;
  site?: string;
  duration?: number | null;
};

export type ImageContent = { src: string; size?: [number, number] | null; fit?: "cover" | "contain"; focus?: [number, number] | null };

export type VideoContent = {
  src: string;
  duration?: number | null;
  trimIn?: number;
  rate?: number;
  loop?: boolean;
  fit?: "cover" | "contain";
  focus?: [number, number] | null;
  volume?: number;
  /** a volume curve (frames from the clip start) replacing `volume`; crossfade ramps in frames */
  volumeKeys?: Keyframe[] | null;
  fadeIn?: number;
  fadeOut?: number;
};

export type TextContent = { runs: Run[]; style?: Partial<TextStyle> | null; reveal?: Reveal | null };

export type ShapeContent = {
  shape: "rect" | "ellipse" | "line" | "arrow" | "path";
  fill?: string | null;
  stroke?: string | null;
  stroke_width?: number | null;
  d?: string | null;
  draw?: boolean;
};

export type Highlight = { at?: number | null; dur?: number | null; color?: string | null };

export type EvidenceContent = {
  src: string;
  size?: [number, number] | null;
  box?: [number, number, number, number] | null;
  site?: string;
  highlight?: Highlight | null;
};

export type ComponentContent = { name: string; props?: Record<string, unknown> };

export type ClipType = "image" | "video" | "text" | "shape" | "evidence" | "component";

export type RClip = {
  id: string;
  type: ClipType;
  track: string;
  from: number;
  dur: number;
  box: Box;
  style?: ClipStyle | null;
  keyframes?: Partial<Record<KeyframeProp, Keyframe[]>> | null;
  enter?: Transition | null;
  exit?: Transition | null;
  transition?: CutIn | null;
  transitionOut?: CutOut | null;
  // the shape depends on `type` (see the *Content types above)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  content: any;
};

export type VisualTrack = { id: string; kind: "visual"; hidden?: boolean; clips: RClip[] };

/** A word of a caption item: frames (absolute, like the item's) and its code-point span in the item's text. */
export type CaptionWord = { from: number; to: number; chars: [number, number] };

export type CaptionItem = { from: number; to: number; runs: Run[]; words?: CaptionWord[] };

/** phrase: each item whole; words: the word being said takes the accent colour; build: words appear as said. */
export type CaptionMode = "phrase" | "words" | "build";

export type CaptionTrack = {
  id: string;
  kind: "captions";
  hidden?: boolean;
  box?: Box | null;
  mode?: CaptionMode;
  style?: Partial<TextStyle> | null;
  items: CaptionItem[];
};

export type Track = VisualTrack | CaptionTrack | { id: string; kind: "audio"; hidden?: boolean };

/** Frames from the item start where the duck's target sounds: the gain is `level` inside, eased over `fade` frames
 *  before `start` and after `end`. */
export type DuckRange = { start: number; end: number; level: number; fade: number };

export type AudioItem = {
  id: string;
  src: string;
  from: number;
  dur: number;
  trimIn?: number;
  volume?: number;
  fadeIn?: number;
  fadeOut?: number;
  /** repeat the asset (from trimIn) until the clip ends */
  loop?: boolean;
  /** a volume curve (frames from the item start) replacing `volume` */
  volumeKeys?: Keyframe[] | null;
  duck?: DuckRange[] | null;
};

/** A face of the workspace's library/fonts: `src` is project-relative (resolve.py links it into build/fonts). */
export type WorkspaceFont = { family: string; src: string; weight?: string; style?: string };

export type Resolved = {
  version: number;
  fps: number;
  width: number;
  height: number;
  durationInFrames: number;
  safe: Box;
  theme: Theme;
  fonts?: WorkspaceFont[];
  tracks: Track[];
  audio?: AudioItem[];
  inspect?: boolean;
};

/** film, stills, inspect: a missing or crashing component fails the call; studio: it draws a red error box. */
export type RenderMode = "film" | "stills" | "inspect" | "studio";

export type FilmProps = { resolved: Resolved; mode?: RenderMode };

/** One @@inspect item (contract section 12). Text items add their computed font-size (px) and CSS colour. */
export type InspectItem = {
  clip: string;
  track: string;
  kind: "clip" | "text";
  rect: [number, number, number, number];
  opacity: number;
  text?: string;
  size?: number;
  color?: string;
};
