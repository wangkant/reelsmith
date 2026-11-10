# Why is the sea salty?

A 30-second landscape explainer in English. One question, the mechanism step by step, the number, a twist.

## Source

NOAA Ocean Service, "Why is the ocean salty?" https://oceanservice.noaa.gov/facts/whysalty.html

- Rocks on land are the major source of the salts dissolved in seawater. Rainwater is slightly acidic, so it erodes
  rocks; the ions it releases are carried by streams and rivers to the ocean.
- About 3.5 % of the weight of seawater is dissolved salts: about 35 grams in a litre.
- USGS, "Saline water use in the United States": fresh water has less than 1,000 ppm of dissolved salts, under
  a gram in a litre. https://www.usgs.gov/water-science-school/science/saline-water-use-united-states
- The NOAA page also names vents in the seafloor as a second source. The film says where most of the salt comes from and
  does not claim rock is the only source.

## Lines

1. Why is the sea salty, when the rivers that fill it taste fresh?
2. Rain is slightly acidic. It wears down rock, and rivers carry the dissolved minerals to the sea.
3. Then the sun lifts the water back into the sky. The salt stays behind.
4. Repeat that for billions of years, and every litre of seawater holds about thirty-five grams of salt.
5. The rivers are salty too. Just too little to taste.

## Pictures

All drawn at 16:9 with "Photograph, natural light, cinematic, no people, no text, no signs, no watermark."

- `delta`: aerial photograph of a wide river delta flowing into a deep blue sea at golden hour, braided channels of
  pale water spreading into the ocean, green banks.
- `river`: a clear shallow mountain river running over smooth round pebbles, seen close to the water surface,
  sunlight glinting on small ripples.
- `rain`: rain falling on dark wet granite mountain rocks, a small stream running down between the stones, overcast
  moody light, shallow depth of field.
- `sun`: a low warm sun over a calm open ocean, thin mist rising from the water surface, soft orange and teal light.
- `crust`: a shallow tidal pool at a rocky shore drying in the sun, a thick white crust of sea salt crystals around
  its rim, the ocean beyond, low warm light.
- `salt`: a clear glass of seawater on a weathered wooden table at the shore, a small pile of coarse white sea salt
  crystals beside it on the left third of the frame, the ocean softly blurred behind.

Animated, 4 s each: `delta_v`, `river_v`, `rain_v`, `sun_v`, `crust_v` (in each, what moves is the water: it
flows, falls, rises as mist or shimmers; the camera pushes in, stays or rises). `salt` stays a still with a slow
push.

## Storyboard

The picture follows the words: each phrase gets the shot it names.

| voice | picture | on screen |
|---|---|---|
| 1 "Why is the sea salty" / "when the rivers ... taste fresh" | the delta from the air / the clear river | the question as a title |
| 2 "Rain is slightly acidic" / "rivers carry the minerals to the sea" | rain on rock / the river / the delta | the NOAA sentence highlighted; then the steps, one at a time |
| 3 "the sun lifts the water" / "The salt stays behind" | the sun over the sea / the salt-crusted pool | the steps go on and end on the salt |
| 4 "billions of years" / "thirty-five grams" | the four shots again, fast / the glass of seawater | "x billions of years"; the number, 35 g |
| 5 "The rivers are salty too" | the river, dimmed | a litre of river water against a litre of seawater |

`ev_noaa` was captured from the NOAA page with the match "slightly acidic" and re-boxed to that one line, so the
sentence reads large. `ev_usgs` (captured, not shown) is where "under 1 g" comes from: the USGS calls water fresh
under 1,000 parts per million of dissolved salts. `bed` is a soft sea wash synthesized with ffmpeg (filtered pink
noise), under the voice at 0.1.
