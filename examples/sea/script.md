# Why is the sea salty?

A 30-second landscape explainer in English. One question, the mechanism step by step, the number, a twist.

## Source

NOAA Ocean Service, "Why is the ocean salty?" https://oceanservice.noaa.gov/facts/whysalty.html

- Rocks on land are the major source of the salts dissolved in seawater. Rainwater is slightly acidic, so it erodes
  rocks; the ions it releases are carried by streams and rivers to the ocean.
- About 3.5 % of the weight of seawater is dissolved salts: about 35 grams in a litre.
- The page also names vents in the seafloor as a second source. The film says where most of the salt comes from and
  does not claim rock is the only source.

## Lines

1. Why is the sea salty, when the rivers that fill it taste fresh?
2. Rain is slightly acidic. It wears down rock, and rivers carry the dissolved minerals to the sea.
3. Then the sun lifts the water back into the sky. The salt stays behind.
4. Repeat that for billions of years, and every litre of seawater holds about thirty-five grams of salt.
5. The rivers are salty too. Just too little to taste.

## Pictures

All four drawn at 16:9 with "Photograph, natural light, cinematic, no people, no text, no signs, no watermark."

- `delta`: aerial photograph of a wide river delta flowing into a deep blue sea at golden hour, braided channels of
  pale water spreading into the ocean, green banks.
- `rain`: rain falling on dark wet granite mountain rocks, a small stream running down between the stones, overcast
  moody light, shallow depth of field.
- `sun`: a low warm sun over a calm open ocean, thin mist rising from the water surface, soft orange and teal light.
- `salt`: a clear glass of seawater on a weathered wooden table at the shore, a small pile of coarse white sea salt
  crystals beside it on the left third of the frame, the ocean softly blurred behind.

Animated, 4 s each: `delta_v` (the river flows into the sea, waves roll in; camera push), `rain_v` (rain falls, the
stream runs; camera still), `sun_v` (mist rises, the reflection shimmers; camera rise). `salt` stays a still with a
slow push.

## Storyboard

| voice | picture | on screen |
|---|---|---|
| 1 | the delta from the air | the question as a title |
| 2 | rain on rock, then the delta again, played backwards | the NOAA sentence highlighted; then the steps, one at a time |
| 3 | the sun over the sea | the steps go on: the sun lifts the water, the salt stays |
| 4 | the three shots again, fast | "× billions of years"; then the glass of seawater and the number, 35 g |
| 5 | the delta | captions only |

`ev_noaa` was captured from the page with the match "slightly acidic" and re-boxed to that one line, so the
sentence reads large. `bed` is a soft sea wash synthesized with ffmpeg (filtered pink noise), under the voice at
0.1.
