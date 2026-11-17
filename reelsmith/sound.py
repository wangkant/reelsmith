"""Sound made on this machine with ffmpeg alone: looping ambience beds and one-shot effects, synthesised from noise,
tones and envelopes (nothing downloaded, no samples), written as 48 kHz WAV audio assets."""
from __future__ import annotations

import json
import math
import random
import re
import tempfile
import time
import wave
import zlib
from array import array
from dataclasses import dataclass
from pathlib import Path

from .providers.config import (ProviderError, check_id, check_replaceable, context, exe, register_asset, rel,
                               run_tree, safe_tool, tail)

SR = 48000
BED_LUFS = -24.0            # a bed at volume 0.25, ducked to 0.5, sits about 30 dB under a -12 LUFS voice line
SHOT_PEAK = -3.0            # one-shots are levelled by their peak: too short for integrated loudness
CEILING = -1.0              # no gain ever takes the true peak past this
SEAM_S = 1.0                # beds crossfade this much of their tail into their head, so the loop has no seam
BED_S = (2.0, 120.0)
SHOT_S = (0.05, 8.0)
GAIN_DB = (-40.0, 12.0)


@dataclass(frozen=True)
class Kind:
    bed: bool
    blurb: str              # three words for the tool's description
    build: object           # (Graph, random.Random) -> label of the mono result
    trim_db: float = 0.0    # a held tone at the shared peak is far louder than a hit: this brings it back in line


class Graph:
    """A filter_complex built from sources, chains and mixes; every noise source draws its own seed."""

    def __init__(self, seconds: float, seeds: random.Random):
        self.d = seconds
        self.seeds = seeds
        self.parts: list[str] = []
        self.n = 0

    def _label(self) -> str:
        self.n += 1
        return f"s{self.n}"

    def add(self, source: str, *filters: str) -> str:
        out = self._label()
        self.parts.append(",".join([source, *[f for f in filters if f]]) + f"[{out}]")
        return out

    def then(self, label: str, *filters: str) -> str:
        out = self._label()
        self.parts.append(f"[{label}]" + ",".join(filters) + f"[{out}]")
        return out

    def noise(self, color: str, *filters: str) -> str:
        return self.add(f"anoisesrc=c={color}:seed={self.seeds.randrange(1, 2**31)}:a=0.5:r={SR}:d={self.d:.6f}",
                        *filters)

    def expr(self, e: str, *filters: str) -> str:
        return self.add(f"aevalsrc=exprs='{e}':s={SR}:d={self.d:.6f}", *filters)

    def train(self, rate: float, decay: float, jitter: float = 0.8, attack: float = 0.0) -> str:
        """Random events at `rate` a second, each jumping to a random height and dying away over `decay` s (rising
        over `attack` s when given): an envelope 0..1 to multiply a sound by."""
        th = max(0.0, 1.0 - rate / SR)
        k = math.exp(-1.0 / (max(decay, 1e-4) * SR))
        hit = f"if(gt(abs(val(0)),{th:.9f}),{1 - jitter:.4f}+{jitter:.4f}*(abs(val(0))-{th:.9f})/{1 - th:.9e},0)"
        env = f"st(0,max(ld(0)*{k:.9f},{hit}))"
        if attack > 0:
            a = 1.0 - math.exp(-1.0 / (attack * SR))
            body = f"{env};st(1,ld(1)+(ld(0)-ld(1))*{a:.9f});ld(1)"
        else:
            body = f"{env};ld(0)"
        src = f"anoisesrc=c=white:seed={self.seeds.randrange(1, 2**31)}:a=1:r={SR}:d={self.d:.6f}"
        return self.add(src, f"aeval=exprs='{body}':c=same")

    def mul(self, a: str, b: str, *filters: str) -> str:
        out = self._label()
        self.parts.append(f"[{a}][{b}]amultiply" + "".join("," + f for f in filters if f) + f"[{out}]")
        return out

    def mix(self, pairs: list[tuple[str, float]], *filters: str) -> str:
        if len(pairs) == 1 and pairs[0][1] == 1:
            return self.then(pairs[0][0], *filters) if filters else pairs[0][0]
        out = self._label()
        ins = "".join(f"[{lab}]" for lab, _ in pairs)
        weights = " ".join(f"{w:g}" for _, w in pairs)
        self.parts.append(f"{ins}amix=inputs={len(pairs)}:weights='{weights}':normalize=0:duration=longest"
                          + "".join("," + f for f in filters if f) + f"[{out}]")
        return out


def _bp(f: float, w: float) -> str:
    return f"bandpass=f={f:.1f}:t=h:w={w:.1f}"


def _sweep(f0: float, f1: float, tau: float, t: str = "t") -> str:
    """Phase of a tone gliding from f0 to f1 with time constant tau (closed form, so it never clicks)."""
    return f"2*PI*({f1:.3f}*{t}+({f0 - f1:.3f})*{tau:.5f}*(1-exp(-{t}/{tau:.5f})))"


def _hit(tk: float, tau: float, attack: float = 0.0) -> str:
    """0 before tk, then a strike dying away over tau; the max() keeps exp() from overflowing before tk."""
    rise = f"*min(1,(t-{tk:.4f})/{attack:.4f})" if attack > 0 else ""
    return f"exp(-max(0,t-{tk:.4f})/{tau:.4f})*gte(t,{tk:.4f}){rise}"


def _ring(base: float, modes, tk: float = 0.0, span: float = 1.0) -> str:
    """Decaying partials (ratio, amplitude, decay) of one struck body, starting at tk."""
    return "+".join(f"{a:g}*sin(2*PI*{base * r:.2f}*(t-{tk:.4f}))*{_hit(tk, dec * span)}" for r, a, dec in modes)


def _bump(c: float, w: float) -> str:
    return f"exp(-pow((t-{c:.4f})/{w:.4f},2))"


# ------------------------------------------------------------------ beds
def _room(g: Graph, p: random.Random) -> str:
    low = g.noise("brown", f"lowpass=f={p.uniform(180, 300):.0f}")
    air = g.noise("pink", "highpass=f=200", "lowpass=f=2500")
    return g.mix([(low, 1), (air, 0.18)])


def _street(g: Graph, p: random.Random) -> str:
    wash = g.noise("brown", "lowpass=f=500")
    hiss = g.noise("pink", "highpass=f=300", "lowpass=f=2500")
    car = g.mul(g.noise("pink", _bp(p.uniform(550, 850), 1100)),
                g.train(p.uniform(0.08, 0.16), 1.8, 0.6, attack=1.0))
    return g.mix([(wash, 1), (hiss, 0.3), (car, 3.0)], "lowpass=f=4000")


def _wind(g: Graph, p: random.Random) -> str:
    waves = "+".join(f"sin(2*PI*{p.uniform(lo, hi):.4f}*t+{p.uniform(0, 6.28):.3f})"
                     for lo, hi in ((0.05, 0.09), (0.11, 0.17), (0.19, 0.31)))
    gust = g.expr(f"0.3+0.7*(({waves})/3+1)/2")
    body = g.mul(g.noise("pink", "highpass=f=90", "lowpass=f=1300"), gust)
    whistle = g.mul(g.noise("white", _bp(p.uniform(650, 1100), 70)), g.expr(f"pow(0.3+0.7*(({waves})/3+1)/2,3)"))
    return g.mix([(body, 1), (whistle, 0.6)])


def _rain(g: Graph, p: random.Random) -> str:
    hiss = g.noise("white", "highpass=f=1200", "lowpass=f=8000")
    drops = g.mul(g.noise("white"), g.train(p.uniform(70, 110), 0.004, 0.9), _bp(2600, 3000))
    patter = g.mul(g.noise("pink"), g.train(p.uniform(20, 30), 0.012, 0.8), "lowpass=f=900")
    rumble = g.noise("brown", "lowpass=f=150")
    return g.mix([(hiss, 0.35), (drops, 1.6), (patter, 0.9), (rumble, 0.3)])


def _kitchen(g: Graph, p: random.Random) -> str:
    hz = p.choice((100, 120)) * p.uniform(0.98, 1.02)
    hum = g.expr(f"0.5*sin(2*PI*{hz:.3f}*t)+0.25*sin(4*PI*{hz:.3f}*t)+0.1*sin(6*PI*{hz:.3f}*t)")
    fan = g.noise("pink", "highpass=f=60", "lowpass=f=700")
    sizzle = g.mul(g.noise("white"), g.train(p.uniform(150, 250), 0.0015, 1.0), "highpass=f=3000")
    return g.mix([(hum, 0.05), (fan, 1), (sizzle, 0.5)])


def _fire(g: Graph, p: random.Random) -> str:
    flutter = g.expr(f"0.8+0.2*sin(2*PI*{p.uniform(0.3, 0.7):.3f}*t)*sin(2*PI*{p.uniform(1.5, 3):.3f}*t)")
    roar = g.mul(g.noise("brown", "lowpass=f=300"), flutter)
    crackle = g.mul(g.noise("white"), g.train(p.uniform(4, 7), 0.006, 1.0), "highpass=f=1500")
    pops = g.mul(g.noise("pink"), g.train(p.uniform(0.5, 0.9), 0.03, 0.8), _bp(900, 1200))
    hiss = g.noise("white", "highpass=f=4000")
    return g.mix([(roar, 1), (crackle, 2.0), (pops, 2.0), (hiss, 0.04)])


def _water(g: Graph, p: random.Random) -> str:
    base = g.noise("pink", _bp(1000, 1800))
    parts = [(base, 0.5)]
    for f in (450, 850, 1500):
        f *= p.uniform(0.85, 1.15)
        parts.append((g.mul(g.noise("pink", _bp(f, f * 0.6)), g.train(18, 0.035, 0.8, attack=0.008)), 2.0))
    parts.append((g.noise("white", "highpass=f=3000"), 0.06))
    return g.mix(parts)


def _crowd(g: Graph, p: random.Random) -> str:
    parts = [(g.noise("pink", "highpass=f=300", "lowpass=f=2500"), 0.25)]
    for _ in range(6):
        f = p.uniform(350, 900)
        parts.append((g.mul(g.noise("pink", _bp(f, 600)), g.train(p.uniform(2.5, 4.5), 0.12, 0.7, attack=0.03)),
                      1.0))
    return g.mix(parts, "lowpass=f=2200", "aecho=0.7:0.5:60|97:0.3|0.2")


def _night(g: Graph, p: random.Random) -> str:
    calls = []
    for _ in range(p.randint(2, 4)):
        f, r, c = p.uniform(3800, 5200), p.uniform(25, 40), p.uniform(0.7, 2.2)
        a, ph = p.uniform(0.3, 1.0), p.uniform(0, 6.28)
        calls.append(f"{a:.3f}*sin(2*PI*{f:.2f}*t)*pow(max(0,sin(2*PI*{r:.3f}*t)),2)"
                     f"*max(0,(sin(2*PI*{c:.3f}*t+{ph:.3f})-0.55)/0.45)")
    insects = g.expr("+".join(calls))
    air = g.noise("pink", "lowpass=f=1200")
    return g.mix([(insects, 0.6), (air, 0.5)])


def _office(g: Graph, p: random.Random) -> str:
    hvac = g.noise("pink", "highpass=f=60", "lowpass=f=600")
    hiss = g.noise("white", "highpass=f=2000", "lowpass=f=6000")
    parts = [(hvac, 1), (hiss, 0.03)]
    for _ in range(2):
        # someone types in bursts: key clicks gated by a slow swell
        keys = g.mul(g.noise("white", _bp(p.uniform(2500, 3500), 2500)),
                     g.train(p.uniform(9, 13), 0.004, 0.5, attack=0.0005))
        parts.append((g.mul(keys, g.train(p.uniform(0.15, 0.25), 2.5, 0.3, attack=0.4)), 4.0))
    return g.mix(parts, "lowpass=f=6000")


def _cafe(g: Graph, p: random.Random) -> str:
    parts = [(g.noise("pink", "highpass=f=200", "lowpass=f=1800"), 0.8)]
    for _ in range(5):
        f = p.uniform(350, 800)
        parts.append((g.mul(g.noise("pink", _bp(f, 500)), g.train(p.uniform(2.5, 4), 0.12, 0.7, attack=0.03)), 0.8))
    for _ in range(3):
        base = p.uniform(2000, 4000)
        cup = g.expr(f"sin(2*PI*{base:.1f}*t)+0.5*sin(2*PI*{base * 2.7:.1f}*t)")
        parts.append((g.mul(cup, g.train(p.uniform(0.25, 0.45), 0.12, 0.7)), 0.1))
    return g.mix(parts, "lowpass=f=7000", "aecho=0.7:0.5:50|83:0.25|0.15")


def _market(g: Graph, p: random.Random) -> str:
    parts = [(g.noise("pink", "highpass=f=250", "lowpass=f=2500"), 0.7)]
    for _ in range(9):
        f = p.uniform(350, 1100)
        parts.append((g.mul(g.noise("pink", _bp(f, 600)), g.train(p.uniform(3.5, 5.5), 0.1, 0.7, attack=0.02)), 1.0))
    for _ in range(2):
        # a nearer voice calling out: a held vowel with a rising and falling pitch
        f0, form = p.uniform(160, 240), p.uniform(600, 900)
        call = g.expr(f"st(0,ld(0)+2*PI*{f0:.1f}*(1+0.1*sin(2*PI*{p.uniform(0.6, 1.2):.2f}*t))/{SR});"
                      + "+".join(f"sin({k}*ld(0))/{k}" for k in range(1, 9)), _bp(form, 500))
        parts.append((g.mul(call, g.train(p.uniform(0.15, 0.3), 0.5, 0.5, attack=0.08)), 0.25))
    crates = g.mul(g.noise("pink", _bp(400, 400)), g.train(p.uniform(0.3, 0.6), 0.03, 0.6))
    return g.mix(parts + [(crates, 1.0)], "lowpass=f=3500", "aecho=0.7:0.4:70:0.2")


def _forest(g: Graph, p: random.Random) -> str:
    waves = "+".join(f"sin(2*PI*{p.uniform(lo, hi):.4f}*t+{p.uniform(0, 6.28):.3f})"
                     for lo, hi in ((0.06, 0.1), (0.13, 0.2), (0.25, 0.35)))
    gust = f"0.4+0.6*(({waves})/3+1)/2"
    leaves = g.mul(g.noise("pink", "highpass=f=400", "lowpass=f=6000"), g.expr(gust))
    rustle = g.mul(g.mul(g.noise("white", _bp(3500, 3000)), g.train(150, 0.002, 1.0)), g.expr(gust))
    parts = [(leaves, 0.8), (rustle, 0.5), (g.noise("brown", "lowpass=f=200"), 0.6)]
    for _ in range(p.randint(2, 3)):
        fc, fm, beta, rep = p.uniform(2500, 4500), p.uniform(8, 25), p.uniform(2, 6), p.uniform(8, 14)
        tone = g.expr(f"sin(2*PI*{fc:.1f}*t+{beta:.2f}*sin(2*PI*{fm:.2f}*t))"
                      f"*pow(max(0,sin(2*PI*{rep:.2f}*t)),2)")
        parts.append((g.mul(tone, g.train(p.uniform(0.2, 0.4), 0.6, 0.6, attack=0.02)), 0.2))
    return g.mix(parts)


def _sea(g: Graph, p: random.Random) -> str:
    a, b = p.uniform(0.09, 0.13), p.uniform(0.05, 0.08)
    lift = f"((sin(2*PI*{a:.4f}*t+{p.uniform(0, 6.28):.3f})+0.6*sin(2*PI*{b:.4f}*t+{p.uniform(0, 6.28):.3f}))/1.6+1)/2"
    wash = g.mul(g.noise("pink", "highpass=f=60", "lowpass=f=900"), g.expr(f"0.25+0.75*pow({lift},2)"))
    surf = g.mul(g.noise("white", "highpass=f=2000", "lowpass=f=9000"), g.expr(f"pow({lift},4)"))
    rumble = g.noise("brown", "lowpass=f=120")
    return g.mix([(wash, 1), (surf, 0.5), (rumble, 0.6)])


def _train(g: Graph, p: random.Random) -> str:
    period, pair = p.uniform(0.9, 1.1), p.uniform(0.11, 0.15)
    # two wheel sets over each rail joint: da-dum ... da-dum, as a periodic envelope with no event list
    def hits(tau: float) -> str:
        return "+".join(f"{a}*exp(-mod(t+{period - o:.4f},{period:.4f})/{tau:.4f})"
                        for o, a in ((0.0, 1.0), (pair, 0.8), (period / 2, 0.7), (period / 2 + pair, 0.6)))
    rumble = g.mul(g.noise("brown", "lowpass=f=180"), g.expr(f"0.85+0.15*sin(2*PI*{p.uniform(1, 1.6):.2f}*t)"))
    rattle = g.noise("pink", _bp(900, 800))
    clack = g.mul(g.noise("pink", _bp(500, 600)), g.expr(hits(0.02)))
    tick = g.mul(g.noise("white", _bp(2500, 2000)), g.expr(hits(0.006)))
    return g.mix([(rumble, 1), (rattle, 0.08), (clack, 1.5), (tick, 0.4)])


# ------------------------------------------------------------------ one-shots (d = their length)
def _whoosh(g: Graph, p: random.Random) -> str:
    d, parts = g.d, []
    for f, c, w in ((350, 0.42, 1.0), (1100, 0.5, 0.8), (3200, 0.58, 0.5)):
        env = g.expr(f"exp(-pow((t-{c * d:.4f})/{0.22 * d:.4f},2))")
        parts.append((g.mul(g.noise("pink", _bp(f * p.uniform(0.9, 1.1), f)), env), w))
    return g.mix(parts)


def _thump(g: Graph, p: random.Random) -> str:
    dec = min(0.25, g.d / 3)
    body = g.expr(f"sin({_sweep(p.uniform(95, 125), p.uniform(42, 55), 0.03)})*exp(-t/{dec:.4f})*min(1,t/0.002)")
    knock = g.mul(g.noise("brown", "lowpass=f=400"), g.expr("exp(-t/0.03)"))
    return g.mix([(body, 1), (knock, 1.5)])


def _tick(g: Graph, p: random.Random) -> str:
    click = g.mul(g.noise("white", _bp(p.uniform(3000, 4000), 3000)), g.expr("exp(-t/0.0025)"))
    tone = g.expr(f"sin(2*PI*{p.uniform(1900, 2500):.1f}*t)*exp(-t/0.008)")
    return g.mix([(click, 1), (tone, 0.3)])


def _pop(g: Graph, p: random.Random) -> str:
    body = g.expr(f"sin({_sweep(p.uniform(800, 1000), p.uniform(300, 400), 0.012)})*exp(-t/0.035)*min(1,t/0.0008)")
    snap = g.mul(g.noise("white", _bp(2000, 2500)), g.expr("exp(-t/0.0015)"))
    return g.mix([(body, 1), (snap, 0.8)])


def _sizzle(g: Graph, p: random.Random) -> str:
    fry = g.mul(g.noise("white", "highpass=f=2500", "lowpass=f=9000"), g.train(p.uniform(300, 500), 0.0015, 1.0))
    hiss = g.noise("white", "highpass=f=4000")
    body = g.mix([(fry, 1), (hiss, 0.12)])
    return g.mul(body, g.expr(f"min(1,t/0.03)*exp(-t/{g.d / 3:.4f})"))


def _crackle(g: Graph, p: random.Random) -> str:
    snaps = g.mul(g.noise("white"), g.train(p.uniform(22, 35), 0.005, 1.0), "highpass=f=1200")
    pops = g.mul(g.noise("pink"), g.train(p.uniform(4, 8), 0.02, 0.8), _bp(800, 1000))
    body = g.mix([(snaps, 1), (pops, 0.8)])
    return g.mul(body, g.expr(f"min(1,t/0.01)*exp(-t/{g.d / 2.5:.4f})"))


def _pour(g: Graph, p: random.Random) -> str:
    f = p.uniform(550, 750)
    stream = g.noise("pink", _bp(f, 500))
    gurgle = g.mul(g.noise("pink", _bp(f * 1.4, 600)), g.train(p.uniform(10, 16), 0.05, 0.8, attack=0.01))
    splash = g.noise("white", _bp(2500, 2000))
    body = g.mix([(stream, 0.6), (gurgle, 1.6), (splash, 0.12)])
    return g.mul(body, g.expr(f"min(1,t/0.12)*min(1,max(0,({g.d:.4f}-t)/0.3))"))


def _drip(g: Graph, p: random.Random) -> str:
    f0, f1 = p.uniform(500, 700), p.uniform(1200, 1600)
    return g.expr(f"sin({_sweep(f0, f1, 0.012)})*exp(-t/0.05)*min(1,t/0.0005)", "aecho=0.8:0.5:35:0.25")


def _steam(g: Graph, p: random.Random) -> str:
    hiss = g.noise("white", "highpass=f=2500", "lowpass=f=11000")
    breath = g.noise("pink", "highpass=f=800")
    body = g.mix([(hiss, 1), (breath, 0.3)])
    return g.mul(body, g.expr(f"min(1,t/0.04)*pow(max(0,1-t/{g.d:.4f}),1.6)"))


def _tear(g: Graph, p: random.Random) -> str:
    fibres = g.mul(g.noise("white"), g.train(p.uniform(280, 420), 0.0012, 1.0), _bp(2800, 4000))
    rips = g.mul(g.noise("white"), g.train(p.uniform(30, 50), 0.004, 0.9), _bp(1200, 1500))
    body = g.mix([(fibres, 1), (rips, 0.6)])
    return g.mul(body, g.expr(f"min(1,t/0.03)*min(1,max(0,({g.d:.4f}-t)/0.06))"
                              f"*(0.75+0.25*sin(2*PI*{p.uniform(5, 9):.2f}*t))"))


def _clink(g: Graph, p: random.Random) -> str:
    base, span = p.uniform(1800, 2600), min(1.0, g.d / 0.8)
    rings = "+".join(f"{a}*sin(2*PI*{base * r * p.uniform(0.98, 1.02):.1f}*t)*exp(-t/{dec * span:.4f})"
                     for r, a, dec in ((1, 1, 0.6), (2.76, 0.6, 0.35), (5.4, 0.35, 0.2), (8.93, 0.2, 0.12)))
    ring = g.expr(f"({rings})*min(1,t/0.0005)")
    tap = g.mul(g.noise("white", "highpass=f=3000"), g.expr("exp(-t/0.001)"))
    return g.mix([(ring, 0.5), (tap, 0.6)])


def _shutter(g: Graph, p: random.Random) -> str:
    t1 = 0.005
    t2 = t1 + p.uniform(0.05, 0.09)
    hits = "+".join(f"{a}*exp(-(t-{tk:.4f})/0.006)*gte(t,{tk:.4f})" for tk, a in ((t1, 1), (t2, 0.7)))
    click = g.mul(g.noise("white", _bp(2500, 3000)), g.expr(hits))
    thunk = g.expr("+".join(f"{a}*sin(2*PI*220*(t-{tk:.4f}))*exp(-(t-{tk:.4f})/0.015)*gte(t,{tk:.4f})"
                            for tk, a in ((t1, 1), (t2, 0.7))))
    return g.mix([(click, 1), (thunk, 0.06)])


def _boing(g: Graph, p: random.Random) -> str:
    f0, rate, dec = p.uniform(150, 190), p.uniform(13, 17), min(0.6, g.d / 2.5)
    # a phase accumulator: the spring's wobble is a frequency, so the phase must be summed sample by sample
    freq = f"{f0:.2f}*(1+0.3*exp(-t/0.35)*sin(2*PI*{rate:.2f}*t))*(1+0.15*(1-exp(-t/0.2)))"
    tone = "+".join(f"{a:g}*sin({k}*ld(0))" for k, a in ((1, 1), (2, 0.6), (3, 0.4), (4, 0.25), (5, 0.15)))
    return g.expr(f"st(0,ld(0)+2*PI*{freq}/{SR});({tone})*exp(-t/{dec:.4f})*min(1,t/0.003)", "lowpass=f=2500")


def _plop(g: Graph, p: random.Random) -> str:
    bubble = g.expr(f"sin({_sweep(p.uniform(280, 340), p.uniform(800, 950), 0.025)})*exp(-t/0.06)*min(1,t/0.001)")
    weight = g.expr(f"sin(2*PI*{p.uniform(110, 140):.1f}*t)*exp(-t/0.035)*min(1,t/0.002)")
    return g.mix([(bubble, 1), (weight, 0.5)])


def _ding(g: Graph, p: random.Random) -> str:
    base, span = p.uniform(2000, 2500), min(1.0, g.d / 1.2)
    # a detuned twin of the first partial beats against it: the shimmer of a real bell
    ring = g.expr(_ring(base, ((1, 1, 0.9), (1.004, 0.6, 0.9), (2.76, 0.35, 0.4), (5.4, 0.15, 0.2)), 0.0, span))
    tap = g.mul(g.noise("white", "highpass=f=3000"), g.expr("exp(-t/0.001)"))
    return g.mix([(ring, 0.5), (tap, 0.3)])


def _chime(g: Graph, p: random.Random) -> str:
    base, gap, span = p.uniform(1000, 1150), min(0.13, g.d / 4), min(1.0, g.d)
    modes = ((1, 1, 0.45), (2, 0.2, 0.2), (3, 0.08, 0.12))
    low, high = _ring(base, modes, 0.0, span), _ring(base * 1.5, modes, gap, span)
    # a soft mallet: each note rises over 3 ms instead of starting on a click
    return g.expr(f"min(1,t/0.003)*(({low})+min(1,max(0,t-{gap:.4f})/0.003)*({high}))")


def _buzz(g: Graph, p: random.Random) -> str:
    f, rough = p.uniform(95, 115), p.uniform(1.05, 1.07)
    odd = "+".join(f"sin(2*PI*{f * m:.2f}*{k}*t)/{k}" for m in (1, rough) for k in range(1, 30, 2))
    end = g.d * 0.9
    env = f"min(1,t/0.006)*min(1,max(0,({end:.4f}-t)/0.03))*(0.8+0.2*sin(2*PI*30*t))"
    return g.expr(f"({odd})*{env}", "lowpass=f=3500")


def _coin(g: Graph, p: random.Random) -> str:
    base, sc = p.uniform(3800, 4500), min(1.0, g.d / 0.9)
    tk, gap, amp, rings = 0.003, 0.11 * sc, 1.0, []
    for i in range(7):
        last = i == 6 or tk + gap * 0.7 > g.d * 0.8
        modes = ((1, 1, 0.5 if last else 0.06), (1.58, 0.6, 0.3 if last else 0.04), (2.4, 0.3, 0.02))
        rings.append(f"{amp:.3f}*({_ring(base * p.uniform(0.99, 1.01), modes, tk, sc)})")
        if last:
            break
        tk, gap, amp = tk + gap, gap * 0.7, amp * 0.8
    tap = g.mul(g.noise("white", "highpass=f=5000"), g.expr("exp(-t/0.001)"))
    return g.mix([(g.expr("+".join(rings)), 0.5), (tap, 0.2)])


def _register(g: Graph, p: random.Random) -> str:
    sc = min(1.0, g.d / 0.9)
    clunk = g.mul(g.noise("pink", _bp(500, 600)), g.expr("exp(-t/0.03)*min(1,t/0.001)"))
    thunk = g.expr("sin(2*PI*120*t)*exp(-t/0.03)*min(1,t/0.002)")
    bell, t1 = p.uniform(2200, 2500), 0.08 * sc
    modes = ((1, 1, 0.5), (2.4, 0.4, 0.3), (4.1, 0.2, 0.15))
    ching = g.expr(f"{_ring(bell, modes, t1, sc)}+0.7*({_ring(bell * 1.01, modes, t1 + 0.035 * sc, sc)})")
    jingle = g.mul(g.noise("white", _bp(5500, 2000)), g.train(40, 0.01, 0.8))
    jingle = g.mul(jingle, g.expr(f"{_hit(t1, 0.2 * sc, 0.01)}"))
    return g.mix([(clunk, 2.0), (thunk, 0.5), (ching, 0.35), (jingle, 0.6)])


def _poof(g: Graph, p: random.Random) -> str:
    sc = min(1.0, g.d / 0.5)
    low = g.mul(g.noise("pink", _bp(p.uniform(250, 350), 400)), g.expr(f"min(1,t/0.01)*exp(-t/{0.18 * sc:.4f})"))
    mid = g.mul(g.noise("pink", _bp(1200, 1500)), g.expr(f"min(1,t/0.005)*exp(-t/{0.07 * sc:.4f})"))
    high = g.mul(g.noise("white", "highpass=f=3500"), g.expr("min(1,t/0.002)*exp(-t/0.025)"))
    return g.mix([(low, 1), (mid, 0.5), (high, 0.15)])


def _splat(g: Graph, p: random.Random) -> str:
    body = g.expr(f"sin({_sweep(p.uniform(110, 140), 60, 0.02)})*exp(-t/0.06)*min(1,t/0.002)")
    slap = g.mul(g.noise("pink", "highpass=f=300", _bp(900, 1600)), g.expr("exp(-t/0.04)*min(1,t/0.001)"))
    wet = g.mul(g.mul(g.noise("white", _bp(1800, 2000)), g.train(p.uniform(130, 170), 0.004, 0.9)),
                g.expr("exp(-t/0.09)"))
    return g.mix([(body, 0.2), (slap, 2.0), (wet, 2.0)], "lowpass=f=5000")


def _zip(g: Graph, p: random.Random) -> str:
    span, parts = min(g.d, 0.35), []
    for i, f in enumerate((500, 900, 1600, 2800, 5000)):
        env = _bump((0.2 + 0.13 * i) * span, 0.12 * span)
        parts.append((g.mul(g.noise("pink", _bp(f * p.uniform(0.95, 1.05), f * 0.8)), g.expr(env)), 1.0))
    r = 8.0
    chirp = g.expr(f"0.15*sin(2*PI*400*{span / math.log(r):.5f}*(exp({math.log(r) / span:.4f}*t)-1))"
                   f"*{_bump(0.55 * span, 0.25 * span)}*lt(t,{span:.4f})")
    return g.mix(parts + [(chirp, 1)])


def _slide(up: bool):
    def build(g: Graph, p: random.Random) -> str:
        lo, hi = p.uniform(420, 500), p.uniform(1800, 2100)
        f0, f1 = (lo, hi) if up else (hi, lo)
        d, k = g.d, math.log(f1 / f0)
        vib = 0.012 * (f0 + f1) / 2 / 6
        phase = f"2*PI*{f0:.2f}*{d / k:.5f}*(exp({k / d:.5f}*t)-1)+{vib:.3f}*sin(2*PI*6*t)"
        env = f"min(1,t/0.03)*min(1,max(0,({d:.4f}-t)/0.06))"
        tone = g.expr(f"(sin({phase})+0.12*sin(2*({phase})))*{env}")
        breath = g.mul(g.noise("white", _bp(2500, 3000)), g.expr(env))
        return g.mix([(tone, 1), (breath, 0.04)])
    return build


def _squeak(g: Graph, p: random.Random) -> str:
    span, lo, up = min(g.d, 0.22), p.uniform(1300, 1500), p.uniform(700, 1000)
    freq = f"({lo:.1f}+{up:.1f}*sin(PI*min(t,{span:.4f})/{span:.4f}))"
    tone = "sin(ld(0))+0.5*sin(2*ld(0))+0.25*sin(3*ld(0))"
    # stick-slip of rubber: a fast tremolo on the tone
    env = f"min(1,t/0.01)*max(0,1-t/{span:.4f})*(0.7+0.3*sin(2*PI*45*t))"
    return g.expr(f"st(0,ld(0)+2*PI*{freq}/{SR});({tone})*{env}", _bp(2400, 3000))


def _knock(g: Graph, p: random.Random) -> str:
    f, gap = p.uniform(180, 230), min(0.17, g.d / 3.5)
    times = ((0.003, 1.0), (0.003 + gap, 0.85))
    wood = "+".join(f"{a}*({_ring(f, ((1, 1, 0.045), (2.3, 0.6, 0.025), (4.6, 0.3, 0.012)), tk)})"
                    for tk, a in times)
    click = g.mul(g.noise("white", _bp(2000, 2500)), g.expr("+".join(f"{a}*{_hit(tk, 0.003)}" for tk, a in times)))
    return g.mix([(g.expr(wood), 1), (click, 0.5)])


def _page(g: Graph, p: random.Random) -> str:
    span = min(g.d, 0.5)
    rustle = g.mul(g.mul(g.noise("white", _bp(3500, 5000)), g.train(p.uniform(250, 350), 0.002, 1.0)),
                   g.expr(_bump(0.55 * span, 0.25 * span)))
    flap = g.mul(g.noise("pink", _bp(700, 900)), g.expr(_bump(0.72 * span, 0.08 * span)))
    air = g.mul(g.noise("pink", "highpass=f=1500"), g.expr(_bump(0.6 * span, 0.2 * span)))
    return g.mix([(rustle, 1), (flap, 0.8), (air, 0.25)])


def _stamp(g: Graph, p: random.Random) -> str:
    thud = g.expr(f"sin({_sweep(p.uniform(150, 180), 90, 0.02)})*exp(-t/0.05)*min(1,t/0.002)")
    pad = g.mul(g.noise("pink", "lowpass=f=400"), g.expr("exp(-t/0.035)*min(1,t/0.001)"))
    slap = g.mul(g.noise("white", _bp(1800, 2500)), g.expr("exp(-t/0.012)"))
    crush = g.mul(g.mul(g.noise("white", _bp(3000, 3000)), g.train(200, 0.002, 1.0)), g.expr("exp(-t/0.05)"))
    return g.mix([(thud, 1), (pad, 1.2), (slap, 0.5), (crush, 0.4)])


def _type(g: Graph, p: random.Random) -> str:
    keys, tk = [], 0.01
    while not keys or (tk < g.d - 0.04 and len(keys) < 120):
        keys.append((tk, p.uniform(0.6, 1.0), p.random() < 0.12))
        tk += p.uniform(0.06, 0.13) + (p.uniform(0.15, 0.3) if p.random() < 0.08 else 0)
    clicks = "+".join(f"{a:.2f}*{_hit(k, 0.004)}" for k, a, _ in keys)
    # the space bar bottoms out lower than the letters
    thock = "+".join(f"{a:.2f}*sin(2*PI*{180 if space else p.uniform(300, 380):.0f}*(t-{k:.4f}))*{_hit(k, 0.012)}"
                     for k, a, space in keys)
    return g.mix([(g.mul(g.noise("white", _bp(3000, 3000)), g.expr(clicks)), 1), (g.expr(thock), 0.25)])


def _heartbeat(g: Graph, p: random.Random) -> str:
    period, beats, tk = p.uniform(0.8, 0.9), [], 0.01
    gap = min(0.2, g.d / 3)
    while tk < g.d - gap - 0.08:
        beats += [(tk, 1.0), (tk + gap, 0.7)]
        tk += period
    if not beats:
        beats = [(0.01, 1.0)]
    lub = "+".join(f"{a}*sin({_sweep(75, 45, 0.04, f'max(0,t-{k:.4f})')})*{_hit(k, 0.07, 0.006)}" for k, a in beats)
    skin = g.mul(g.noise("brown", "lowpass=f=150"), g.expr("+".join(f"{a}*{_hit(k, 0.04, 0.004)}" for k, a in beats)))
    return g.mix([(g.expr(lub), 1), (skin, 0.6)])


def _zap(g: Graph, p: random.Random) -> str:
    span = min(g.d, 0.35)
    ph = _sweep(p.uniform(2200, 2800), p.uniform(220, 300), 0.17 * span)
    env = f"exp(-t/{0.4 * span:.4f})*min(1,t/0.002)"
    return g.expr(f"(sin({ph})+0.4*sin(2*({ph}))+0.25*sin(3*({ph})))*{env}", "aecho=0.8:0.6:40:0.3")


def _sparkle(g: Graph, p: random.Random) -> str:
    span = min(g.d, 0.9)
    times = sorted(p.uniform(0, 0.7 * span) for _ in range(p.randint(7, 9)))
    # each ping a little higher than the last: the twinkle climbs
    pitches = [(2800 + 3500 * i / len(times)) * p.uniform(0.9, 1.1) for i in range(len(times))]
    pings = "+".join(f"{p.uniform(0.5, 1):.2f}*({_ring(f, ((1, 1, 0.09), (2.76, 0.2, 0.04)), tk)})"
                     for f, tk in zip(pitches, times))
    shimmer = g.mul(g.noise("white", "highpass=f=6000"), g.expr(_bump(0.4 * span, 0.3 * span)))
    return g.mix([(g.expr(pings), 1), (shimmer, 0.08)])


def _snare(g: Graph, p: random.Random, tk: float = 0.0, a: float = 1.0) -> list[tuple[str, float]]:
    body = g.expr(f"{a}*({_ring(p.uniform(180, 200), ((1, 1, 0.06), (1.7, 0.6, 0.04)), tk)})")
    wires = g.mul(g.noise("white", "highpass=f=1800", "lowpass=f=9000"), g.expr(f"{a}*{_hit(tk, 0.11)}"))
    crack = g.mul(g.noise("white", _bp(3500, 3000)), g.expr(f"{a}*{_hit(tk, 0.006)}"))
    return [(body, 0.7), (wires, 0.6), (crack, 1.0)]


def _drum(g: Graph, p: random.Random) -> str:
    return g.mix(_snare(g, p))


def _metal(g: Graph, p: random.Random) -> str:
    # six square oscillators at clashing pitches, the classic drum-machine cymbal
    k = p.uniform(1.9, 2.1)
    squares = "+".join(f"sgn(sin(2*PI*{f * k:.2f}*t))" for f in (205.3, 304.4, 369.6, 522.7, 540.0, 800.0))
    return g.expr(f"({squares})/6", "highpass=f=3500", "highpass=f=3500")


def _cymbal(g: Graph, p: random.Random) -> str:
    dec = min(1.5, g.d / 2.5)
    env = f"min(1,t/0.001)*(exp(-t/{dec:.4f})+exp(-t/0.02))"
    metal = g.mul(_metal(g, p), g.expr(env))
    wash = g.mul(g.noise("white", "highpass=f=5000"), g.expr(env))
    return g.mix([(metal, 0.7), (wash, 0.5)])


def _badum(g: Graph, p: random.Random) -> str:
    sc = min(1.0, g.d / 1.2)
    t1, t2 = 0.16 * sc, 0.42 * sc
    tom = g.expr(f"sin({_sweep(160, 120, 0.05)})*{_hit(0, 0.1, 0.002)}")
    floor = g.expr(f"sin({_sweep(120, 80, 0.05, f'max(0,t-{t1:.4f})')})*{_hit(t1, 0.18, 0.002)}")
    kick = g.expr(f"sin({_sweep(110, 50, 0.03, f'max(0,t-{t1:.4f})')})*{_hit(t1, 0.15, 0.002)}")
    tss = g.mul(_metal(g, p), g.expr(_hit(t2, 0.5 * sc, 0.001)))
    hiss = g.mul(g.noise("white", "highpass=f=6000"), g.expr(_hit(t2, 0.35 * sc, 0.001)))
    beater = g.mul(g.noise("pink", _bp(1200, 1500)), g.expr(_hit(t1, 0.012)))
    return g.mix([*_snare(g, p, 0.0, 0.7), (tom, 0.6), (floor, 1.0), (kick, 0.9), (beater, 0.8), (tss, 0.6),
                  (hiss, 0.4)])


def _footsteps(g: Graph, p: random.Random) -> str:
    gap = min(0.5, max(0.14, (g.d - 0.15) / 3.3))
    steps, tk = [], 0.01
    while not steps or (tk < g.d - 0.1 and len(steps) < 4):
        steps.append((tk, 1.0 if len(steps) % 2 == 0 else 0.85))
        tk += gap * p.uniform(0.95, 1.05)
    heel = g.mul(g.noise("pink", "lowpass=f=500"), g.expr("+".join(f"{a}*{_hit(k, 0.025)}" for k, a in steps)))
    thud = g.expr("+".join(f"{a}*sin(2*PI*90*(t-{k:.4f}))*{_hit(k, 0.03, 0.002)}" for k, a in steps))
    scuff = g.mul(g.noise("pink", _bp(1500, 2000)),
                  g.expr("+".join(f"{a * 0.5}*{_hit(k + 0.05, 0.03, 0.005)}" for k, a in steps)))
    tap = g.mul(g.noise("white", _bp(3000, 2500)), g.expr("+".join(f"{a}*{_hit(k, 0.004)}" for k, a in steps)))
    return g.mix([(heel, 1), (thud, 0.5), (scuff, 0.6), (tap, 0.3)])


KINDS: dict[str, Kind] = {
    "room": Kind(True, "quiet indoor tone", _room),
    "street": Kind(True, "distant traffic passing", _street),
    "wind": Kind(True, "gusting outdoor air", _wind),
    "rain": Kind(True, "steady falling rain", _rain),
    "kitchen": Kind(True, "hood hum, sizzle", _kitchen),
    "fire": Kind(True, "roar with crackles", _fire),
    "water": Kind(True, "babbling flowing stream", _water),
    "crowd": Kind(True, "far wordless murmur", _crowd),
    "night": Kind(True, "insects, night air", _night),
    "office": Kind(True, "keys and air", _office),
    "cafe": Kind(True, "murmur, clinking cups", _cafe),
    "market": Kind(True, "busy wordless voices", _market),
    "forest": Kind(True, "birds and leaves", _forest),
    "sea": Kind(True, "waves breaking slowly", _sea),
    "train": Kind(True, "rolling rail rhythm", _train),
    "whoosh": Kind(False, "fast air pass", _whoosh),
    "thump": Kind(False, "low soft impact", _thump),
    "tick": Kind(False, "tiny sharp click", _tick),
    "pop": Kind(False, "short bright pop", _pop),
    "sizzle": Kind(False, "hot fat burst", _sizzle),
    "crackle": Kind(False, "dry snapping bits", _crackle),
    "pour": Kind(False, "liquid pouring gurgle", _pour),
    "drip": Kind(False, "single water drop", _drip),
    "steam": Kind(False, "hiss fading out", _steam),
    "tear": Kind(False, "paper or skin", _tear),
    "clink": Kind(False, "glass or metal", _clink),
    "shutter": Kind(False, "camera shutter click", _shutter),
    "boing": Kind(False, "springy cartoon bounce", _boing),
    "plop": Kind(False, "small wet drop", _plop),
    "ding": Kind(False, "small bell strike", _ding),
    "chime": Kind(False, "rising right answer", _chime),
    "buzz": Kind(False, "wrong answer buzzer", _buzz, -4.0),
    "coin": Kind(False, "coin drops, rings", _coin),
    "register": Kind(False, "cash register ring", _register),
    "poof": Kind(False, "soft cloud puff", _poof),
    "splat": Kind(False, "wet messy impact", _splat),
    "zip": Kind(False, "fast swish up", _zip),
    "slide_up": Kind(False, "slide whistle up", _slide(True), -8.0),
    "slide_down": Kind(False, "slide whistle down", _slide(False), -8.0),
    "squeak": Kind(False, "rubber toy squeak", _squeak),
    "knock": Kind(False, "two knocks, wood", _knock),
    "page": Kind(False, "page turning over", _page),
    "stamp": Kind(False, "rubber stamp, paper", _stamp),
    "type": Kind(False, "short keyboard burst", _type),
    "heartbeat": Kind(False, "lub-dub heart beats", _heartbeat),
    "zap": Kind(False, "laser zap down", _zap),
    "sparkle": Kind(False, "climbing magic twinkle", _sparkle),
    "drum": Kind(False, "snare rim shot", _drum),
    "cymbal": Kind(False, "crash cymbal wash", _cymbal),
    "badum": Kind(False, "joke drum sting", _badum),
    "footsteps": Kind(False, "a few steps", _footsteps),
}


def kinds_text() -> str:
    beds = ", ".join(f"{k} ({v.blurb})" for k, v in KINDS.items() if v.bed)
    shots = ", ".join(f"{k} ({v.blurb})" for k, v in KINDS.items() if not v.bed)
    return f"beds: {beds}; one-shots: {shots}"


# ------------------------------------------------------------------ ffmpeg
def _ff(args: list, timeout: float = 300) -> str:
    rc, _out, err, timed_out = run_tree([exe("ffmpeg"), "-hide_banner", "-nostdin", *args], timeout=timeout,
                                        no_window=True)
    if timed_out or rc != 0:
        raise ProviderError(f"ffmpeg failed{' (timed out)' if timed_out else ''}: {tail(err, 4, 400)}")
    return err


def graph_for(kind: str, seconds: float, seed: int) -> str:
    """The filter_complex for one sound; its output is [out]."""
    spec = KINDS[kind]
    n = round(seconds * SR)
    if not spec.bed:
        g = Graph(seconds, random.Random(f"{seed}/noise"))
        mono = spec.build(g, random.Random(f"{seed}/{kind}"))
        fade = min(0.005, seconds / 4)
        g.parts.append(f"[{mono}]atrim=end_sample={n},apad=whole_len={n},"
                       f"afade=t=out:st={seconds - fade:.6f}:d={fade:.6f}[out]")
        return ";".join(g.parts)
    seam = min(SEAM_S, seconds / 4)
    m = round(seam * SR)
    longer = (n + m) / SR
    parts, sides = [], []
    for side in ("L", "R"):
        # one set of parameters, independent noise per side: the same place, heard wide
        g = Graph(longer, random.Random(f"{seed}/noise/{side}"))
        g.n = 100 * len(sides)
        sides.append(spec.build(g, random.Random(f"{seed}/{kind}")))
        parts += g.parts
    parts.append(f"[{sides[0]}][{sides[1]}]amerge=inputs=2,atrim=end_sample={n + m},apad=whole_len={n + m},"
                 "asplit[head][tail]")
    parts.append(f"[head]atrim=end_sample={n},afade=t=in:d={seam:.6f}:curve=qsin[h]")
    parts.append(f"[tail]atrim=start_sample={n},asetpts=PTS-STARTPTS,afade=t=out:d={seam:.6f}:curve=qsin[t]")
    parts.append("[h][t]amix=inputs=2:normalize=0:duration=first[out]")
    return ";".join(parts)


def measure(path: Path) -> tuple[float | None, float | None]:
    """(integrated LUFS, true peak dBTP); None where it cannot be measured (a sound shorter than 0.4 s has no
    integrated loudness)."""
    err = _ff(["-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"])
    i = re.findall(r"I:\s+(-?[\d.]+|-inf) LUFS", err)
    pk = re.findall(r"Peak:\s+(-?[\d.]+|-inf) dBFS", err)
    lufs = float(i[-1]) if i and i[-1] != "-inf" else None
    peak = float(pk[-1]) if pk and pk[-1] != "-inf" else None
    return (lufs if lufs is not None and lufs > -69 else None), peak


def bands(path: Path) -> dict:
    """Share of the power below 250 Hz, 250-2000 Hz and above 2000 Hz (rounded to a whole percent)."""
    power = {}
    for name, f in (("low", "lowpass=f=250:p=2,lowpass=f=250:p=2"),
                    ("mid", "highpass=f=250:p=2,highpass=f=250:p=2,lowpass=f=2000:p=2,lowpass=f=2000:p=2"),
                    ("high", "highpass=f=2000:p=2,highpass=f=2000:p=2")):
        err = _ff(["-nostats", "-i", str(path), "-af", f"{f},volumedetect", "-f", "null", "-"])
        m = re.findall(r"mean_volume:\s+(-?[\d.]+|-inf) dB", err)
        power[name] = 10 ** (float(m[-1]) / 10) if m and m[-1] != "-inf" else 0.0
    total = sum(power.values()) or 1.0
    return {k: round(100 * v / total) for k, v in power.items()}


def read_pcm(path: Path) -> tuple[list[array], int]:
    """The channels of a 16-bit WAV as arrays of samples, and its rate."""
    with wave.open(str(path), "rb") as w:
        ch, rate, width = w.getnchannels(), w.getframerate(), w.getsampwidth()
        if width != 2:
            raise ProviderError(f"{path.name} is not 16-bit PCM")
        data = array("h", w.readframes(w.getnframes()))
    return [data[c::ch] for c in range(ch)], rate


def _rms_db(xs) -> float:
    if not len(xs):
        return -120.0
    p = sum(x * x for x in xs) / len(xs)
    return 10 * math.log10(p / 32768 ** 2) if p > 0 else -120.0


def seam(path: Path, ms: float = 50) -> dict:
    """How the end of a file meets its start when looped: level of the first and last `ms` (dB, loudest channel)
    and the jump across the joint against the usual sample-to-sample step (1 is an ordinary step)."""
    chans, rate = read_pcm(path)
    k = max(1, round(rate * ms / 1000))
    first = max(_rms_db(c[:k]) for c in chans)
    last = max(_rms_db(c[-k:]) for c in chans)
    jumps = []
    for c in chans:
        win = list(c[:k]) + list(c[-k:])
        steps = sorted(abs(win[i + 1] - win[i]) for i in range(len(win) - 1) if i != k - 1)
        usual = steps[int(0.9 * (len(steps) - 1))] or 1
        jumps.append(abs(c[0] - c[-1]) / usual)
    return {"first_db": round(first, 1), "last_db": round(last, 1), "diff_db": round(abs(first - last), 1),
            "jump": round(max(jumps), 2)}


def make(out: Path, kind: str, seconds: float, seed: int, gain_db: float = 0.0) -> dict:
    """Synthesise `kind` into a 48 kHz 16-bit WAV at `out`, levelled (beds by loudness, one-shots by peak) and kept
    under the true-peak ceiling; returns its measures."""
    spec = KINDS[kind]
    with tempfile.TemporaryDirectory(prefix="reelsmith-sound-") as tmp:
        raw = Path(tmp) / "raw.wav"
        script = Path(tmp) / "graph.txt"
        script.write_text(graph_for(kind, seconds, seed), encoding="utf-8")
        _ff(["-y", "-loglevel", "error", "-filter_complex_script", str(script), "-map", "[out]", "-ar", str(SR),
             "-c:a", "pcm_f32le", str(raw)], timeout=120 + 4 * seconds)
        lufs, peak = measure(raw)
        if peak is None:
            raise ProviderError(f"the {kind} sound came out silent (seed {seed}); try another seed")
        want = (BED_LUFS - lufs) if (spec.bed and lufs is not None) else (SHOT_PEAK - peak)
        gain = min(want + gain_db + spec.trim_db, CEILING - 0.5 - peak)
        ch = "2" if spec.bed else "1"
        _ff(["-y", "-loglevel", "error", "-i", str(raw), "-af", f"volume={gain:.3f}dB", "-ar", str(SR), "-ac", ch,
             "-c:a", "pcm_s16le", str(out)])
    lufs, peak = measure(out)
    info = {"kind": kind, "seconds": round(seconds, 3), "seed": seed, "bed": spec.bed, "lufs": lufs, "peak": peak,
            "bands": bands(out)}
    if spec.bed:
        info["seam"] = seam(out)
    return info


def _has_voice(project: Path) -> bool:
    try:
        return bool(json.loads((project / "project.json").read_text(encoding="utf-8")).get("voice"))
    except (OSError, ValueError, AttributeError):
        return False


def default_seed(asset_id: str, kind: str) -> int:
    return zlib.crc32(f"{asset_id}/{kind}".encode("utf-8")) % 1_000_000


def _seconds(kind: str, seconds) -> float:
    lo, hi = BED_S if KINDS[kind].bed else SHOT_S
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not (lo <= seconds <= hi):
        what = "a bed (it loops to fill any clip)" if KINDS[kind].bed else "a one-shot"
        raise ProviderError(f"seconds for {what} must be {lo:g}-{hi:g} (got {seconds!r})")
    return float(seconds)


@safe_tool
def sound(project, id, kind, seconds, seed=None, gain_db=0.0, *, progress=None):
    """(text, is_error): assets/<id>.wav, a synthesised bed or one-shot, registered as an audio asset."""
    started = time.monotonic()
    ctx = context(project)
    asset_id = check_id(id)
    kind = str(kind or "").strip().lower()
    if kind not in KINDS:
        raise ProviderError(f"unknown kind {kind!r}; {kinds_text()}")
    secs = _seconds(kind, seconds)
    if seed is None or seed == "":
        seed = default_seed(asset_id, kind)
    if isinstance(seed, float) and seed.is_integer():
        seed = int(seed)
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**31:
        raise ProviderError(f"seed must be a whole number 0 to {2**31 - 1} (got {seed!r})")
    if isinstance(gain_db, bool) or not isinstance(gain_db, (int, float)) or not GAIN_DB[0] <= gain_db <= GAIN_DB[1]:
        raise ProviderError(f"gain_db must be {GAIN_DB[0]:g} to {GAIN_DB[1]:g} (got {gain_db!r})")
    check_replaceable(ctx, asset_id, "audio")
    out = ctx.assets_dir / f"{asset_id}.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    if progress:
        progress("sound", 0.0)
    info = make(out, kind, secs, seed, float(gain_db))
    b = info["bands"]
    level = f"{info['lufs']:g} LUFS" if info["lufs"] is not None else "too short for LUFS"
    note = f"sound {kind}, seed {seed}, {secs:g} s" + (f", gain {gain_db:+g} dB" if gain_db else "")
    reg = register_asset(ctx, asset_id, {"path": rel(ctx, out), "kind": "audio", "note": note})
    voiced = _has_voice(ctx.project)
    if info["bed"]:
        s = info["seam"]
        clip = {"id": f"{asset_id}_1", "type": "audio", "asset": asset_id, "start": 0, "end": "end",
                "volume": 0.25 if voiced else 0.15, "loop": True}
        if voiced:
            clip["duck"] = {"under": "voice", "to": 0.5}
        use = (f"A stereo bed that loops without a seam (ends {s['diff_db']:g} dB apart). Put it on an audio track "
               f"under the scene: {json.dumps(clip)}.")
    else:
        clip = {"id": f"{asset_id}_1", "type": "audio", "asset": asset_id, "start": "line:3+0.3" if voiced else 2,
                "dur": round(secs, 3), "volume": 0.5 if voiced else 0.7}
        use = (f"A mono one-shot. Put it on a second audio track as a short clip at the action, e.g. "
               f"{json.dumps(clip)}.")
    if not voiced:
        use += (" With no voice, mastering lifts the whole mix to the profile's loudness: keep the bed well under the "
                "one-shots.")
    return (f"Made {asset_id!r}: {kind}, seed {seed}, {secs:g} s, {level}, true peak {info['peak']:g} dBTP; power "
            f"low {b['low']}% / mid {b['mid']}% / high {b['high']}% (below 250 Hz / to 2 kHz / above), in "
            f"{time.monotonic() - started:.1f} s -> {rel(ctx, out)}. {use}{reg}"), False
