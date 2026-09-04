"""Fitness mode. The fake ssh discriminates the three media-VM scripts by their stdin, like the bats stub did."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from yt.fitness import (
    Resolved,
    add_to_show,
    ask_order,
    parse_listing,
    pick_target,
    safe_show_name,
    season_order,
    split_target,
)
from yt.ui import Failure

URL = "https://youtu.be/abcDEF12345"
BASE = "/mnt/nfs/movies/youtube/fitness"
LISTING = "Bodyweight\t1\tBodyweight\t22\tfeed\nKettlebell\t1\tCompilations\t17\tcourse\nKettlebell\t2\tTurkish Get-Up\t26\tcourse\nKettlebell\t3\tTutorials\t9\tfeed\n"
RESOLVED_COURSE = f"{BASE}/Kettlebell\n{BASE}/Kettlebell/Season 03\n10\n2\ncourse\n0\n"
RESOLVED_FEED = f"{BASE}/Kettlebell\n{BASE}/Kettlebell/Season 03\n990\n3\nfeed\n0\n"
RESOLVED_NO_ORDER = f"{BASE}/Kettlebell\n{BASE}/Kettlebell/Season 03\n10\n2\ncourse\n1\n"
STAGED = "Kettlebell S03E10 - Mark_Wildman-Snatch-[abcDEF12345].mkv\n"


class TestParseListing:
    def test_parses_shows_and_seasons(self) -> None:
        shows, seasons = parse_listing(LISTING)
        assert shows == ["Bodyweight", "Kettlebell"]
        assert seasons[("Kettlebell", 3)].title == "Tutorials"
        assert seasons[("Kettlebell", 3)].order == "feed"
        assert seasons[("Kettlebell", 2)].episodes == 26

    def test_show_without_seasons_and_old_four_column_lines(self) -> None:
        shows, seasons = parse_listing("Running\t\t\t0\t\nYoga\t1\tBasics\t4\n")
        assert shows == ["Running", "Yoga"]
        assert ("Running", 0) not in seasons
        assert seasons[("Yoga", 1)].order == "course"

    def test_empty(self) -> None:
        assert parse_listing("") == ([], {})


class TestSplitTarget:
    @pytest.mark.parametrize(
        ("target", "expected"),
        [
            ("Kettlebell/3", ("Kettlebell", "3", "")),
            ("Kettlebell/Tutorials", ("Kettlebell", "Tutorials", "")),
            ("Kettlebell/4:Swings", ("Kettlebell", "4:Swings", "")),
            ("Kettlebell/4:Swings:feed", ("Kettlebell", "4:Swings", "feed")),
            ("Kettlebell/3:course", ("Kettlebell", "3", "course")),
        ],
    )
    def test_split(self, target: str, expected: tuple[str, str, str]) -> None:
        assert split_target(target) == expected


class TestResolved:
    def test_derived_fields(self) -> None:
        r = Resolved(f"{BASE}/K", f"{BASE}/K/Season 03", 990, 3, "feed", False)
        assert r.season_number == 3
        assert r.season_name == "Season 03"
        assert r.code == "S03E990"


class TestPrompts:
    def test_ask_order_defaults_and_validates(
        self, answers: Callable[[str], None], capsys: pytest.CaptureFixture[str]
    ) -> None:
        answers("\n")
        assert ask_order("feed") == "feed"
        answers("x\nc\n")
        assert ask_order("feed") == "course"
        assert "? f or c" in capsys.readouterr().err
        answers("")
        with pytest.raises(Failure):
            ask_order("course")

    def test_pick_by_number_and_name(self, answers: Callable[[str], None], capsys: pytest.CaptureFixture[str]) -> None:
        answers("2\ntutorials\n")
        assert pick_target(LISTING) == ("Kettlebell/3", None)
        err = capsys.readouterr().err
        assert "Seasons of Kettlebell:" in err
        assert "3) Tutorials (9 episodes, feed)" in err

    def test_pick_show_by_name_then_season_number(self, answers: Callable[[str], None]) -> None:
        answers("kettlebell\n2\n")
        assert pick_target(LISTING) == ("Kettlebell/2", None)

    def test_bad_answers_are_re_asked(self, answers: Callable[[str], None], capsys: pytest.CaptureFixture[str]) -> None:
        answers("9\nZumba\n1\n7\n1\n")
        assert pick_target(LISTING) == ("Bodyweight/1", None)
        err = capsys.readouterr().err
        assert "? no such show: 9" in err
        assert "? no such season: 7" in err

    def test_new_season_asks_name_and_order(self, answers: Callable[[str], None]) -> None:
        answers("2\nn\nSwings\nc\n")
        assert pick_target(LISTING) == ("Kettlebell/4:Swings", "course")

    def test_new_show_goes_straight_to_first_season(
        self, answers: Callable[[str], None], capsys: pytest.CaptureFixture[str]
    ) -> None:
        answers("n\nRunning\nForm\n\n")
        assert pick_target(LISTING) == ("Running/1:Form", "feed")
        assert "Running has no seasons yet — the first one will be Season 01." in capsys.readouterr().err

    def test_eof_aborts(self, answers: Callable[[str], None]) -> None:
        answers("")
        with pytest.raises(Failure):
            pick_target(LISTING)


@pytest.fixture
def media(fake_ssh: Any, cookies: Path, answers: Callable[[str], None]) -> Any:
    fake_ssh.on("mktemp -d", stdout="/tmp/yt.stub42\n")
    fake_ssh.on("--print '%(id)s'", stdout="abcDEF12345\nKettlebell Snatch Technique\nMark Wildman\n")
    fake_ssh.on("python3 -", stdout="nfo written\n")
    fake_ssh.on("bash -s", host="media", stdin_has="for sd in", stdout=LISTING)

    def resolve(call: Any) -> tuple[int, str] | None:
        if call.host == "media" and call.stdin and "next episode number" in call.stdin:
            return (0, RESOLVED_FEED) if call.command.endswith(" feed") else (0, RESOLVED_COURSE)
        return None

    fake_ssh.when(resolve)
    fake_ssh.on("bash -s", host="media", stdout=STAGED)
    answers("y\n")
    return fake_ssh


def _resolve_calls(media: Any) -> list[str]:
    return [c.command for c in media.calls if c.stdin and "next episode number" in c.stdin]


def test_nfo_step_captures_its_output_instead_of_inheriting_stdout(
    media: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """jellyfin_nfo.py prints every sidecar it writes; with capture=False those paths
    inherit yt's stdout and arrive ahead of the video path, breaking `yt -f URL | epm`."""
    assert add_to_show("Kettlebell/3", URL) == 0
    out, err = capsys.readouterr()
    assert "nfo written" not in out, "helper output must not reach stdout"
    assert "nfo written" in err, "helper output should still be visible as progress"
    nfo_call = next(c for c in media.calls if c.command.startswith("python3 -"))
    assert nfo_call.capture is True


def test_fast_path_downloads_and_prints_final_path(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    assert add_to_show("Kettlebell/3", URL) == 0
    out, err = capsys.readouterr()
    assert out == f"{BASE}/Kettlebell/Season 03/Kettlebell S03E10 - Mark_Wildman-Snatch-[abcDEF12345].mkv\n"
    assert "Kettlebell / Season 03 (course)  →  S03E10" in err
    assert _resolve_calls(media) == [f"bash -s -- {BASE} Kettlebell 3 ''"]
    item = next(c for c in media.calls if c.stdin and "prefix=$(printf" in c.stdin)
    assert item.command == (
        f"bash -s -- /tmp/yt.stub42 /tmp/yt.stub42/cookies.txt /mnt/nfs/downloads/yt-staging/yt.stub42 {URL} Kettlebell 3 10 2"
    )
    helper = next(c for c in media.calls if "python3 -" in c.command)
    assert helper.command == "python3 - /mnt/nfs/downloads/yt-staging/yt.stub42 Kettlebell 3 10"
    assert helper.stdin and "jellyfin_nfo" in helper.stdin
    nas = next(c for c in media.calls if c.host == "nas")
    assert (
        nas.command
        == "bash -s -- /mnt/swift/downloads/yt-staging/yt.stub42 '/mnt/tank/movies/youtube/fitness/Kettlebell/Season 03'"
    )
    assert "Jellyfin picks it up on the next scheduled scan" in err


def test_interactive_picks_show_and_season(
    media: Any, answers: Callable[[str], None], capsys: pytest.CaptureFixture[str]
) -> None:
    answers("2\ntutorials\ny\n")
    assert add_to_show("", URL) == 0
    out, err = capsys.readouterr()
    assert "Seasons of Kettlebell:" in err
    assert "3) Tutorials (9 episodes, feed)" in err
    assert "Kettlebell/Season 03/Kettlebell S03E10" in out


def test_declining_confirmation_aborts(
    media: Any, answers: Callable[[str], None], capsys: pytest.CaptureFixture[str]
) -> None:
    answers("2\n3\nn\n")
    with pytest.raises(Failure):
        add_to_show("", URL)
    assert "Aborted" in capsys.readouterr().err
    assert media.count("bash -s", host="nas") == 0
    assert media.commands()[-1] == "rm -rf /tmp/yt.stub42 2>/dev/null || true"


def test_non_interactive_without_target_fails(
    media: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("YT_FITNESS_ANSWERS_FROM_STDIN")
    with pytest.raises(Failure):
        add_to_show("", URL)
    assert "stdin is not a terminal" in capsys.readouterr().err


def test_duplicate_in_show_is_skipped(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    media.rules.insert(
        0,
        lambda c: (
            (0, f"{BASE}/Kettlebell/Season 02/Kettlebell S02E05 - old-[abcDEF12345].mkv\n")
            if c.command.startswith("find ")
            else None
        ),
    )
    assert add_to_show("Kettlebell/2", URL) == 0
    out, err = capsys.readouterr()
    assert "Already in this show: Kettlebell/Season 02/Kettlebell S02E05 - old-[abcDEF12345].mkv" in err
    assert out.endswith("old-[abcDEF12345].mkv\n")
    assert media.count("bash -s", host="nas") == 0


def test_download_failure(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    media.rules.insert(0, lambda c: (2, "") if c.stdin and "prefix=$(printf" in c.stdin else None)
    with pytest.raises(Failure):
        add_to_show("Kettlebell/3", URL)
    assert "Remote download failed" in capsys.readouterr().err
    assert media.commands()[-1] == "rm -rf /tmp/yt.stub42 /mnt/nfs/downloads/yt-staging/yt.stub42 2>/dev/null || true"


def test_nas_failure_keeps_staging(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    media.rules.insert(0, lambda c: (1, "") if c.host == "nas" else None)
    with pytest.raises(Failure):
        add_to_show("Kettlebell/3", URL)
    assert "NAS transfer failed" in capsys.readouterr().err
    assert not any("rm -rf" in c for c in media.commands())


def test_nfo_failure_keeps_staging(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    media.rules.insert(0, lambda c: (1, "") if "python3 -" in c.command else None)
    with pytest.raises(Failure):
        add_to_show("Kettlebell/3", URL)
    assert "nfo generation failed" in capsys.readouterr().err
    assert media.count("bash -s", host="nas") == 0


def test_target_without_slash_is_rejected(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(Failure):
        add_to_show("Kettlebell", URL)
    assert "<Show>/<Season>" in capsys.readouterr().err
    assert media.calls == []


def test_missing_order_marker_is_asked_once(
    media: Any, answers: Callable[[str], None], capsys: pytest.CaptureFixture[str]
) -> None:
    def resolve(call: Any) -> tuple[int, str] | None:
        if call.stdin and "next episode number" in call.stdin:
            return (0, RESOLVED_FEED) if call.command.endswith(" feed") else (0, RESOLVED_NO_ORDER)
        return None

    media.rules.insert(0, resolve)
    answers("f\ny\n")
    assert add_to_show("Kettlebell/3", URL) == 0
    err = capsys.readouterr().err
    assert "has no order set yet" in err
    assert "(feed)  →  S03E990" in err
    assert _resolve_calls(media) == [f"bash -s -- {BASE} Kettlebell 3 ''", f"bash -s -- {BASE} Kettlebell 3 feed"]


def test_inline_order_creates_feed_season(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    assert add_to_show("Kettlebell/4:Swings:feed", URL) == 0
    assert "S03E990" in capsys.readouterr().err
    assert _resolve_calls(media) == [f"bash -s -- {BASE} Kettlebell 4:Swings feed"]


def test_new_season_order_from_picker_reaches_resolve(media: Any, answers: Callable[[str], None]) -> None:
    answers("2\nn\nSwings\nc\ny\n")
    assert add_to_show("", URL) == 0
    assert _resolve_calls(media) == [f"bash -s -- {BASE} Kettlebell 4:Swings course"]


def test_resolve_failure(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    media.rules.insert(0, lambda c: (4, "") if c.stdin and "next episode number" in c.stdin else None)
    with pytest.raises(Failure):
        add_to_show("Kettlebell/9", URL)
    assert "Could not resolve Kettlebell/9" in capsys.readouterr().err


def test_first_episode_reminds_about_posters(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    media.rules.insert(
        0,
        lambda c: (
            (0, f"{BASE}/Running\n{BASE}/Running/Season 01\n1\n2\ncourse\n0\n")
            if c.stdin and "next episode number" in c.stdin
            else None
        ),
    )
    assert add_to_show("Running/1:Form", URL) == 0
    assert "make_posters.py" in capsys.readouterr().err


def test_jellyfin_scan_requested_when_configured(
    media: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JELLYFIN_URL", "http://jf.local/")
    monkeypatch.setenv("JELLYFIN_API_KEY", "k3y")
    seen: dict[str, Any] = {}

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            pass

    def fake_urlopen(request: Any, timeout: float) -> Response:
        seen["url"] = request.full_url
        seen["auth"] = request.get_header("Authorization")
        return Response()

    monkeypatch.setattr("yt.fitness.urllib.request.urlopen", fake_urlopen)
    add_to_show("Kettlebell/3", URL)
    assert seen == {"url": "http://jf.local/Library/Refresh", "auth": 'MediaBrowser Token="k3y"'}
    assert "Jellyfin library scan requested" in capsys.readouterr().err


def test_jellyfin_scan_failure_is_a_warning(
    media: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import urllib.error

    monkeypatch.setenv("JELLYFIN_URL", "http://jf.local")
    monkeypatch.setenv("JELLYFIN_API_KEY", "k3y")

    def boom(request: Any, timeout: float) -> None:
        raise urllib.error.URLError("down")

    monkeypatch.setattr("yt.fitness.urllib.request.urlopen", boom)
    assert add_to_show("Kettlebell/3", URL) == 0
    assert "Jellyfin scan request failed" in capsys.readouterr().err


class TestSeasonOrder:
    def test_sets_and_reports(self, media: Any, capsys: pytest.CaptureFixture[str]) -> None:
        assert season_order("Kettlebell/3", "feed") == 0
        err = capsys.readouterr().err
        assert "Kettlebell / Season 03: order=feed, next episode S03E990" in err
        assert "newest first" in err
        assert _resolve_calls(media) == [f"bash -s -- {BASE} Kettlebell 3 feed"]

    def test_rejects_bad_order(self, media: Any, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(Failure):
            season_order("Kettlebell/3", "sideways")
        assert "must be feed or course" in capsys.readouterr().err

    def test_requires_target(self, media: Any) -> None:
        with pytest.raises(Failure):
            season_order("Kettlebell", "")


class TestShowNameValidation:
    """The show is the only user-controlled path component: the season directory is
    always "Season NN", so `..` in a show name is the whole traversal surface."""

    @pytest.mark.parametrize("bad", ["..", ".", "../Escape", "-rf", "", "  "])
    def test_rejects_unsafe_show_names_before_any_remote_call(
        self, bad: str, fake_ssh: Any, cookies: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake_ssh.on("mktemp -d", stdout="/tmp/yt.stub42\n")
        with pytest.raises(Failure):
            add_to_show(f"{bad}/1:X", URL)
        assert "not a usable show name" in capsys.readouterr().err
        assert fake_ssh.count("bash -s", host="media") == 0, "must reject before touching the media VM"

    @pytest.mark.parametrize("good", ["Mobility & Physio", "Combat Sports", "Heavy Club", "Kettlebell"])
    def test_accepts_the_show_names_the_library_actually_uses(self, good: str) -> None:
        assert safe_show_name(good) == good

    def test_strips_surrounding_whitespace(self) -> None:
        assert safe_show_name("  Kettlebell  ") == "Kettlebell"

    def test_season_order_rejects_unsafe_names_too(self, fake_ssh: Any, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(Failure):
            season_order("../X/1", "feed")
        assert "not a usable show name" in capsys.readouterr().err
        assert fake_ssh.count("bash -s", host="media") == 0
