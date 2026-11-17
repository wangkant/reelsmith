// The stage kit: performance scenes in which drawn things and torn photo cut-outs act the narration out.
export {
  backOut, boil, clamp01, cues, in2, inOut, lerp, out3, prog, spr, step, swing, useCues, win, wob,
} from "./time";
export type { CueLine, Cues } from "./time";
export { along, bbox, blob, circle, fibre, mixColor, rect, roughRect, seedInt, smooth, smoothClosed, torn } from "./geom";
export type { Pt } from "./geom";
export { PALETTE, PaletteContext, shades, shadowCss, useFilters, usePalette, useUnit } from "./palette";
export type { Palette } from "./palette";
export { camAt, Grain, Layer, Stage, useDepth, useStage } from "./Stage";
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
export { breathe, drop, follow, pendulum, shake, stations } from "./motion";
export type { Drop, DropOptions, StationOptions, Stop } from "./motion";
export { Canvas, Gloss, Shadow, Solid } from "./material";
export type { Box, GlossProps, ShadowProps, SolidProps } from "./material";
export { Clouds, Leaves, PendantLamp, Desk, Outdoors, Room, Street, useSet } from "./sets";
export type { DeskProps, OutdoorsProps, RoomProps, SetInfo, SetProps, StreetProps } from "./sets";
export {
  castMatrix, coverFit, distanceAt, dofBlur, filmFrame, handheld, hazeBand, joinAt, lookAt, onScreen, pointAt, punchAt, punchView, shadeRamp, swayAngle,
  travelAt,
} from "./optics";
export type { Ease, FilmTiming, Fit, Light, Punch, TravelOptions, TravelState, View } from "./optics";
export { Hold, lightMatrix, Photo, PictureContext, pictureSize, SvgImage, Travel, useLight, usePicture, wipeBand } from "./photo";
export type { PhotoProps, Picture, TravelProps, Wipe } from "./photo";
export { Droplet, Embers, Glow, Pour, Vapor } from "./matter";
export type { DropletProps, EmbersProps, GlowProps, PourProps, VaporProps } from "./matter";
export { quadMatrix, Surface } from "./surface";
export type { SurfaceProps } from "./surface";
export { Occluder, Plate, usePlate } from "./plate";
export type { OccluderProps, PlateProps, Sway } from "./plate";
export { FilmFrame, Footage, isFilm } from "./footage";
export type { Film, FootageProps } from "./footage";
export { Haze, Motes, Rays } from "./air";
export type { HazeProps, MotesProps, RaysProps } from "./air";
export { Refract, softEllipse, softRing, Warp } from "./warp";
export type { Area, RefractProps, WarpProps } from "./warp";
export { Pane, Streak } from "./glass";
export type { PaneProps, StreakProps } from "./glass";
export { Lens, useLens } from "./lens";
export type { Grade, Kick, LensProps, LensState } from "./lens";
export { Join } from "./join";
export type { JoinProps } from "./join";
export {
  actAt, beatAt, blinkAt, Burst, checkTwins, Cracks, DustPuff, faceAt, Framing, framingAt, LineStyle, mouthAt, Performer, PopMark, poseBox,
  PoseSheet, Splash, SpeedLines, SteamCurls, SweatDrop, talkAt, toss, ToonStar, useLineStyle, useVoiceLevel,
} from "./drawn";
export type {
  Act, ActOptions, Beat, BurstProps, CracksProps, DustPuffProps, FramingCut, FramingProps, LineStyleValue, Mouth, MouthOptions, Nudge,
  PerformerProps, PopMarkProps, Pose, PoseSheetProps, SplashProps,
  SpeedLinesProps, SteamCurlsProps, SweatDropProps, Toss, ToonStarProps,
} from "./drawn";
export {
  bakedAt, Boil, boilSeed, Brush, brushPressure, Morph, morphAt, partOf, posesFrom, ramp, sampleLine, Smear, smearAt, useBaked, usePoses,
  walkAt, Walker,
} from "./craft";
export type { BoilProps, BrushProps, MorphProps, PoseSpec, SmearOptions, SmearProps, Twin, WalkerProps, WalkOptions } from "./craft";
export {
  AngerVein, Bubbles, ChalkBoard, chalkLine, ChalkLine, ChalkPath, ChalkText, Confetti, DizzyStars, fallAt, FocusLines, focusLinesAt, GloomLines, Hearts,
  IdeaBulb, ImpactFlash, MusicNotes, Petals, Poof, popAt, Rain, riseAt, ShockLines, Snow, spawnsAt, Sparkles, SpeechBubble, Tears, ThoughtBubble, writeAt, Zzz,
} from "./marks";
export type {
  AirArea, AngerVeinProps, BubblesProps, ChalkBoardProps, ChalkLineProps, ChalkPathProps, ChalkTextProps, ConfettiProps, DizzyStarsProps, Fall, FallOptions,
  FocusArea, FocusLinesProps, GloomLinesProps, HeartsProps, IdeaBulbProps, ImpactFlashProps, MusicNotesProps, PetalsProps, PoofProps, RainProps, Rise,
  ShockLinesProps, SnowProps, Spawn, SparklesProps, SpeechBubbleProps, TearsProps, ThoughtBubbleProps, ZzzProps,
} from "./marks";
