"""The workspace's stock (library/stock) and the catalogue: listing, taking, drawing what stock lacks in the look,
keeping a project's own drawings. No image provider is called: a painter stands in for it."""
import asyncio
import importlib
import json
from pathlib import Path

import pytest
from PIL import Image

from reelsmith import stock as S
from reelsmith import tools as T
from test_drawn import figure

D = importlib.import_module("reelsmith.providers.draw")
LOOK = {"sheet": "sheet.png", "who": "a round orange cat in a green apron", "character": "STYLE-C.",
        "set": "STYLE-S.", "prop": "STYLE-P."}


class Painter:
    """Cut-outs are a drawn figure (twins: the same figure redrawn with the mouth or the eyes shut); plates are
    opaque."""
    name = "fake"

    def __init__(self, tmp):
        self.tmp, self.calls = tmp, []

    def draw(self, prompt, gen_size, workdir, ref, timeout, **kw):
        self.calls.append(dict(prompt=prompt, ref=Path(ref).name if ref else None, **kw))
        out = self.tmp / f"gen-{len(self.calls)}.png"
        if not prompt.endswith(D.CUTOUT_NOTE):
            Image.new("RGB", (1024, 1536), (180, 200, 220)).save(out)
            return D.Shot("ok", out, 1.0, thread="t")
        twin = prompt.startswith(D.TWIN_PREFIX)
        eyes = "shut" if "eyes are shut" in prompt else "open"
        big = Image.new("RGBA", (1024, 1536), (0, 0, 0, 0))
        fig = figure((340, 560), s=1.08, shift=(14, 9), mouth="shut", eyes=eyes) if twin else figure((300, 500))
        big.paste(fig, (300, 400))
        big.save(out)
        return D.Shot("ok", out, 1.0, thread="t")

    def forget(self, shot):
        pass


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    monkeypatch.setattr(D, "_BLOCKED", {})
    monkeypatch.setattr(D, "_ref_jpeg", lambda ref, workdir: ref)
    plain = D.draw_many

    def no_ffmpeg_fit(src, dst, size, **_):
        Image.open(src).convert("RGB").resize(size).save(dst)
        return size
    monkeypatch.setattr(D, "draw_many", lambda root, pictures, provider=None:
                        plain(root, pictures=pictures, provider=provider, fit=no_ffmpeg_fit))
    root = tmp_path / "ws"
    project = root / "projects" / "film"
    (project / "assets").mkdir(parents=True)
    (root / "workspace.json").write_text('{"profile": "douyin"}', encoding="utf-8")
    (project / "project.json").write_text('{"version": 2, "meta": {"title": "t"}, "tracks": [], "assets": {}}',
                                          encoding="utf-8")
    return project


def stock_dir(project):
    return project.parent.parent / "library" / "stock"


def with_look(project):
    stock = stock_dir(project)
    stock.mkdir(parents=True, exist_ok=True)
    (stock / "look.json").write_text(json.dumps(LOOK), encoding="utf-8")
    figure((300, 500)).save(stock / "sheet.png")


def assets(project):
    return json.loads((project / "project.json").read_text(encoding="utf-8"))["assets"]


def stocked_pose(project, tmp_path, pid="shrug"):
    for name, kw in (("a", {}), ("b", {"mouth": "shut"}), ("c", {"mouth": "shut", "eyes": "shut"})):
        figure((300, 500), **kw).save(tmp_path / f"{name}.png")
    return S.save_item(stock_dir(project), "pose", pid, [("src", tmp_path / "a.png"), ("shut", tmp_path / "b.png"),
                                                        ("blink", tmp_path / "c.png")], {"what": "shrugs"})


# ------------------------------------------------------------------ the catalogue
def test_the_catalogue_is_well_formed():
    cat = S.catalogue()
    data = json.loads(S.CATALOGUE.read_text(encoding="utf-8"))
    for kind, plural in S.KINDS.items():
        ids = [e["id"] for e in data[plural]]
        assert len(ids) == len(set(ids)) and all(S.ID.match(i) for i in ids), kind
        assert all(e.get("what") for e in data[plural]), kind
    assert len(cat["pose"]) >= 40 and len(cat["set"]) >= 30 and len(cat["prop"]) >= 50
    assert all(e.get("view") and e.get("pose") for e in cat["pose"].values())
    assert all(e["layers"][0]["name"] == "plate" and all(x.get("description") for x in e["layers"])
               for e in cat["set"].values())
    assert all(e.get("description") for e in cat["prop"].values())
    assert not set(cat["pose"]) & set(cat["prop"])           # both become the bare asset id
    assert any(e.get("blink") is False for e in cat["pose"].values())


# ------------------------------------------------------------------ stock and take from stock
def test_listing_shows_stock_and_the_catalogue_left(ws, tmp_path):
    stocked_pose(ws, tmp_path)
    r = T.stock(str(ws))
    assert r.ok and "- pose:shrug [shut blink; feet 0.50] shrugs" in r and "look.json: missing" in r, r
    assert "shrug," not in r.split("Catalogue")[1] and "neutral" in r.split("Catalogue")[1]
    one = T.stock(str(ws), kind="prop")
    assert "- prop:coin: a gold coin" in one and "poses in stock" not in one
    assert "shrug_blink" in T.stock(str(ws), name="pose:shrug")
    assert "is in the catalogue, not in stock" in T.stock(str(ws), name="set:kitchen")
    assert not T.stock(str(ws), name="pose:nothing_like_it").ok


def test_take_copies_a_pose_with_its_twins_and_gives_the_manifest(ws, tmp_path):
    stocked_pose(ws, tmp_path)
    r = T.take(str(ws), ["pose:shrug"])
    assert r.ok and "Took 1 of 1" in r and "assets shrug, shrug_shut, shrug_blink" in r, r
    assert "const poses = { shrug: { src: a.shrug_asset, shut: a.shrug_shut_asset, blink: a.shrug_blink_asset, " \
           "feet: 0.50 } };" in r
    got = assets(ws)
    assert got["shrug"]["alpha"] and got["shrug_blink"]["path"] == "assets/shrug_blink.png"
    assert (ws / "assets" / "shrug_shut.png").is_file()
    assert T.take(str(ws), '["pose:shrug"]').ok                  # the same pictures again: fine


def test_take_refuses_to_overwrite_another_picture_with_the_same_id(ws, tmp_path):
    stocked_pose(ws, tmp_path)
    Image.new("RGB", (40, 40)).save(ws / "assets" / "shrug.png")
    raw = json.loads((ws / "project.json").read_text(encoding="utf-8"))
    raw["assets"]["shrug"] = {"path": "assets/shrug.png", "kind": "image"}
    (ws / "project.json").write_text(json.dumps(raw), encoding="utf-8")
    r = T.take(str(ws), ["pose:shrug"])
    assert not r.ok and "already holds another picture" in r and "shrug_shut" not in assets(ws)


def test_without_a_look_the_catalogue_is_not_drawn(ws, tmp_path, monkeypatch):
    painter = Painter(tmp_path)
    monkeypatch.setattr(D, "make_provider", lambda ctx: painter)
    r = T.take(str(ws), ["prop:coin"])
    assert not r.ok and "look.json" in r and '"who"' in r and painter.calls == []


# ------------------------------------------------------------------ drawing what stock lacks
def test_a_missing_pose_is_drawn_in_order_kept_and_taken(ws, tmp_path, monkeypatch):
    with_look(ws)
    painter = Painter(tmp_path)
    monkeypatch.setattr(D, "make_provider", lambda ctx: painter)
    r = T.take(str(ws), ["pose:shrug"])
    assert r.ok and "drawn in the look and kept in stock" in r and "Drew 3 of 3" in r, r
    base, shut, blink = painter.calls
    assert base["prompt"].startswith(LOOK["who"] + ", shoulders raised") and "STYLE-C." in base["prompt"]
    assert base["ref"] == "look_sheet.png" and "ref_note" not in base
    assert shut["prompt"].startswith(D.TWIN_PREFIX + S.SHUT_PROMPT) and shut["ref"] == "shrug.png"
    assert blink["prompt"].startswith(D.TWIN_PREFIX + S.BLINK_PROMPT) and blink["ref"] == "shrug_shut.png"
    meta = json.loads((stock_dir(ws) / "poses" / "shrug.json").read_text(encoding="utf-8"))
    assert meta["twins"] == ["shut", "blink"] and meta["feet"] == 0.5 and meta["tags"] == ["gesture"]
    assert meta["prompt"] in base["prompt"] and meta["view"] == "front"
    assert "const poses = { shrug: { src: a.shrug_asset" in r
    assert {"shrug", "shrug_shut", "shrug_blink"} <= set(assets(ws))
    painter.calls.clear()
    assert T.take(str(ws), ["pose:shrug"]).ok and painter.calls == []       # stock now: no draw


def test_a_pose_with_closed_eyes_gets_no_blink_and_a_failed_twin_is_reported(ws, tmp_path, monkeypatch):
    with_look(ws)

    class NoTwins(Painter):
        def draw(self, prompt, *a, **kw):
            if prompt.startswith(D.TWIN_PREFIX):
                self.calls.append({"prompt": prompt})
                return D.Shot("noimage", None, 1.0, thread="t")
            return super().draw(prompt, *a, **kw)
    painter = NoTwins(tmp_path)
    monkeypatch.setattr(D, "make_provider", lambda ctx: painter)
    r = T.take(str(ws), ["laugh"])
    assert r.ok and "without laugh_shut" in r and "laugh_blink" not in r.split("Drawing:")[0], r
    assert "const poses = { laugh: { src: a.laugh_asset, feet: 0.50 } };" in r
    assert len(painter.calls) == 3                                   # base, then the shut twin tried twice


def test_a_set_is_drawn_plate_first_then_its_piece_matched_to_it(ws, tmp_path, monkeypatch):
    with_look(ws)
    painter = Painter(tmp_path)
    monkeypatch.setattr(D, "make_provider", lambda ctx: painter)
    r = T.take(str(ws), ["set:kitchen", "prop:coin"])
    assert r.ok and "Took 2 of 2" in r, r
    find = lambda words: next(c for c in painter.calls if words in c["prompt"])  # noqa: E731
    plate, counter, coin = find(S.PLATE_FLOOR), find("a kitchen island counter"), find("gold coin")
    assert len(painter.calls) == 3
    assert S.PLATE_FLOOR in plate["prompt"] and "STYLE-S." in plate["prompt"] and plate["ref"] == "look_sheet.png"
    assert counter["ref"] == "kitchen_plate.png" and counter["ref_note"] == D.MATCH_CUT_NOTE
    assert "STYLE-P." in coin["prompt"]
    assert "set kitchen back to front: kitchen_plate, the figure, kitchen_counter" in r
    meta = json.loads((stock_dir(ws) / "sets" / "kitchen.json").read_text(encoding="utf-8"))
    assert [(x["name"], x["front"]) for x in meta["layers"]] == [("plate", False), ("counter", True)]


# ------------------------------------------------------------------ keep
def test_keep_saves_a_pose_with_its_twins_and_refuses_to_overwrite(ws, tmp_path):
    for aid, kw in (("wave", {}), ("wave_shut", {"mouth": "shut"})):
        figure((300, 500), **kw).save(ws / "assets" / f"{aid}.png")
    raw = json.loads((ws / "project.json").read_text(encoding="utf-8"))
    raw["assets"] = {a: {"path": f"assets/{a}.png", "kind": "image", "alpha": True, "note": "a cat waving"}
                     for a in ("wave", "wave_shut")}
    (ws / "project.json").write_text(json.dumps(raw), encoding="utf-8")
    r = T.keep(str(ws), ["wave"], "pose")
    assert r.ok and "pose:wave with shut, feet 0.50" in r, r
    meta = json.loads((stock_dir(ws) / "poses" / "wave.json").read_text(encoding="utf-8"))
    assert meta["what"] == "a cat waving" and meta["files"]["shut"]["file"] == "wave_shut.png"
    again = T.keep(str(ws), ["wave"], "pose")
    assert not again.ok and "replace=true" in again
    assert T.keep(str(ws), ["wave"], "pose", what="waves hello", replace=True).ok
    assert "waves hello" in T.stock(str(ws), kind="pose")
    assert not T.keep(str(ws), ["ghost"], "prop").ok and not T.keep(str(ws), ["wave"], "shape").ok


def test_keep_a_set_names_it_from_its_layers(ws, tmp_path):
    Image.new("RGB", (300, 500), (90, 90, 90)).save(ws / "assets" / "attic_plate.png")
    figure((300, 500)).save(ws / "assets" / "attic_beam.png")
    raw = json.loads((ws / "project.json").read_text(encoding="utf-8"))
    raw["assets"] = {"attic_plate": {"path": "assets/attic_plate.png", "kind": "image"},
                     "attic_beam": {"path": "assets/attic_beam.png", "kind": "image", "alpha": True}}
    (ws / "project.json").write_text(json.dumps(raw), encoding="utf-8")
    r = T.keep(str(ws), ["attic_plate", "attic_beam"], "set", what="an attic")
    assert r.ok and "set:attic" in r and "plate, beam" in r, r
    assert "set:attic [plate, beam] an attic" in T.stock(str(ws), kind="set")


def test_the_three_tools_are_published():
    from reelsmith.mcp_server import mcp
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"stock", "take", "keep"} <= names and {"stock", "take", "keep"} <= set(T.TOOLS)


# ------------------------------------------------------------------ a film's own cast
GRANNY = "an old woman with a grey bun and a floral padded jacket"


def with_plain_look(project):
    stock = stock_dir(project)
    stock.mkdir(parents=True, exist_ok=True)
    (stock / "look.json").write_text(json.dumps({k: LOOK[k] for k in ("sheet", "character", "set", "prop")}),
                                     encoding="utf-8")
    figure((300, 500)).save(stock / "sheet.png")


def test_a_look_without_a_fixed_character_draws_poses_only_for_a_cast(ws, tmp_path, monkeypatch):
    with_plain_look(ws)
    painter = Painter(tmp_path)
    monkeypatch.setattr(D, "make_provider", lambda ctx: painter)
    r = T.take(str(ws), ["pose:shrug"])
    assert not r.ok and "no fixed character" in r and "cast" in r and painter.calls == []
    assert "take(project, [\"pose:<id>\"], cast=" in T.stock(str(ws))
    assert "<cast>_shrug" in T.stock(str(ws), name="pose:shrug")
    assert T.take(str(ws), ["prop:coin"]).ok                         # places and things need no character
    assert not T.take(str(ws), ["pose:shrug"], cast="granny").ok     # who is missing
    assert not T.take(str(ws), ["pose:shrug"], cast="Gran ny", who=GRANNY).ok
    assert not T.take(str(ws), ["pose:shrug"], cast="look", who=GRANNY).ok     # look_sheet is the workspace's


def test_a_cast_member_gets_a_sheet_then_poses_that_stay_in_the_project(ws, tmp_path, monkeypatch):
    with_plain_look(ws)
    painter = Painter(tmp_path)
    monkeypatch.setattr(D, "make_provider", lambda ctx: painter)
    r = T.take(str(ws), ["pose:shrug"], cast="granny", who=GRANNY)
    assert r.ok and "Took 1 of 1" in r and "drawn for granny from granny_sheet" in r, r
    sheet, base, shut, blink = painter.calls
    assert "model sheet" in sheet["prompt"] and GRANNY in sheet["prompt"] and "STYLE-C." in sheet["prompt"]
    assert sheet["ref"] == "look_sheet.png"
    assert base["prompt"].startswith(f"The same character as the reference model sheet ({GRANNY}), shoulders raised")
    assert base["ref"] == "granny_sheet.png" and shut["ref"] == "granny_shrug.png"
    assert blink["ref"] == "granny_shrug_shut.png"
    assert "const poses = { granny_shrug: { src: a.granny_shrug_asset, shut: a.granny_shrug_shut_asset, " \
           "blink: a.granny_shrug_blink_asset, feet: 0.50 } };" in r
    assert {"granny_sheet", "granny_shrug", "granny_shrug_shut", "granny_shrug_blink"} <= set(assets(ws))
    assert not (stock_dir(ws) / "poses").exists()                    # the film's own: nothing kept
    painter.calls.clear()
    again = T.take(str(ws), ["pose:shrug", "pose:think"], cast="granny", who=GRANNY)
    assert again.ok and "already in this project as granny's" in again and "Took 2 of 2" in again, again
    assert len(painter.calls) == 3 and all("model sheet of one" not in c["prompt"] for c in painter.calls)
    assert "granny_think: { src: a.granny_think_asset" in again
    far = T.take(str(ws), ["pose:moonwalk_no"], cast="granny", who=GRANNY)
    assert not far.ok and "style_ref_asset='granny_sheet'" in far


def test_a_look_may_turn_blinks_off_and_a_twin_that_is_not_one_stays_out_of_the_manifest(ws, tmp_path, monkeypatch):
    with_plain_look(ws)
    look = stock_dir(ws) / "look.json"
    look.write_text(json.dumps({**json.loads(look.read_text(encoding="utf-8")), "blink": False}), encoding="utf-8")
    painter = Painter(tmp_path)
    monkeypatch.setattr(D, "make_provider", lambda ctx: painter)
    r = T.take(str(ws), ["pose:shrug"], cast="granny", who=GRANNY)
    assert r.ok and len(painter.calls) == 3 and "granny_shrug_blink" not in r, r     # sheet, pose, shut
    figure((340, 560)).save(ws / "assets" / "granny_shrug_blink.png")           # a stray redraw on another canvas
    raw = json.loads((ws / "project.json").read_text(encoding="utf-8"))
    raw["assets"]["granny_shrug_blink"] = {"path": "assets/granny_shrug_blink.png", "kind": "image", "alpha": True,
                                           "width": 340, "height": 560}
    (ws / "project.json").write_text(json.dumps(raw), encoding="utf-8")
    again = T.take(str(ws), ["pose:shrug"], cast="granny", who=GRANNY)
    assert again.ok and "blink:" not in again.split("const poses")[1], again
    report = ("1. a_blink: ok, x. its middle 94% of the way down the figure\n"
              "2. a_shut: ok, x. its middle 14% of the way down the figure\n"
              "3. b_blink: ok, x. its middle 10% of the way down\n4. b_shut: ok, x. its middle 14% of the way down")
    assert S._misplaced_blinks([report]) == {"a_blink"}


def test_a_cast_works_beside_a_fixed_character_and_a_failed_sheet_stops_its_poses(ws, tmp_path, monkeypatch):
    with_look(ws)
    stocked_pose(ws, tmp_path)

    class NoSheet(Painter):
        def draw(self, prompt, *a, **kw):
            if "model sheet of one" in prompt:
                self.calls.append({"prompt": prompt})
                return D.Shot("noimage", None, 1.0, thread="t")
            return super().draw(prompt, *a, **kw)
    painter = NoSheet(tmp_path)
    monkeypatch.setattr(D, "make_provider", lambda ctx: painter)
    r = T.take(str(ws), ["pose:shrug", "prop:coin"], cast="guard", who="a tall security guard in a navy uniform")
    assert r.ok and "guard_sheet was not drawn" in r and "Took 1 of 2" in r, r
    assert "guard_shrug" not in assets(ws) and "shrug" not in assets(ws)     # the stock pose is the fixed character's
