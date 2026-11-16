// Points traced on AssetGrid previews of the pictures, in their own pixels.
import type { Pt } from "@reelsmith/kit";

// valley.webp and inside.webp: 1024 x 1536
export const PLATE: [number, number] = [1024, 1536];
export const PAD = 0.06;

// the near treetops and the meadow below them: drawn again in front of the balloon
export const TREES: Pt[] = [
  [0, 830], [40, 822], [100, 822], [150, 835], [190, 850], [230, 835], [270, 822], [330, 818], [380, 830], [420, 845],
  [450, 870], [490, 858], [540, 855], [580, 880], [630, 862], [680, 850], [730, 848], [780, 858], [830, 880], [850, 900],
  [880, 845], [930, 830], [980, 828], [1024, 840], [1024, 1536], [0, 1536],
];
// where the meadow's tall grass begins (it sways), and the sun just outside the top right
export const GRASS_Y = 1150;
export const SUN: Pt = [1010, 300];
// the mist band over the valley floor
export const MIST: [number, number] = [640, 835];

// balloon.webp: 560 x 807, the basket at the bottom
export const BALLOON: [number, number] = [560, 807];
export const ENVELOPE: Pt = [280, 300];       // centre of the envelope
export const ENVELOPE_R: [number, number] = [272, 305];
export const CROWN: Pt = [280, 6];
export const MOUTH: Pt = [281, 612];

// inside.webp: the burner coil's top, the crown's daylight circle
export const BURNER: Pt = [512, 905];
export const VENT: Pt = [512, 245];
