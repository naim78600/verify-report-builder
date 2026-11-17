"""V12: the spoken reminder for each verifier, in the Pradeep voice (Microsoft Edge read-aloud "bn-BD-PradeepNeural").

The text of each verifier is different (his trip IDs, applicants, times), so the clip is made when the round is prepared,
on this PC, with the free online voice (internet needed; nothing is paid).  Clips are kept in
~/.verify_report_builder/voices/<name>.mp3 for 3 days.  If the voice service cannot be reached, the round still works:
the helper sends the message without a voice (and says so).  Naim chose the voice, the speed and the words (18-11-2026).
"""
from __future__ import annotations

import asyncio
import threading
import time as _time
from pathlib import Path

from . import config

VOICE = "bn-BD-PradeepNeural"
RATE = "-12%"                     # a little slower than normal: the verifier must catch every trip ID
CACHE = config.SETTINGS_DIR / "voices"
KEEP_DAYS = 3


def clip_path(name: str) -> Path:
    return CACHE / f"{name}.mp3"


def _clean_old() -> None:
    cutoff = _time.time() - KEEP_DAYS * 86400
    for p in CACHE.glob("*.mp3"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass


async def _make(items: list[dict], progress=None) -> dict:
    import edge_tts                                       # bundled with the program
    done, failed = 0, []
    for n, it in enumerate(items, 1):
        out = clip_path(it["voice"])
        if out.exists() and out.stat().st_size > 1000:
            done += 1
            continue
        for attempt in range(3):
            try:
                tmp = out.with_suffix(".part")
                await edge_tts.Communicate(it["say"], VOICE, rate=RATE).save(str(tmp))
                tmp.replace(out)
                done += 1
                break
            except Exception:                              # noqa: BLE001 - network / service busy: try again, then give up
                await asyncio.sleep(2 + attempt * 3)
        else:
            failed.append(it["voice"])
        if progress:
            progress(n, len(items))
    return {"made": done, "failed": failed}


def make_clips(items: list[dict], progress=None) -> dict:
    """Makes the clip of every round item (blocking; run it in a worker thread).  -> {"made": n, "failed": [names]}"""
    CACHE.mkdir(parents=True, exist_ok=True)
    _clean_old()
    try:
        import edge_tts  # noqa: F401
    except Exception:
        return {"made": 0, "failed": [i["voice"] for i in items], "error": "voice package missing"}
    return asyncio.run(_make([i for i in items if i.get("say") and i.get("voice")], progress))


def make_clips_in_background(items: list[dict], done=None) -> threading.Thread:
    def run():
        res = make_clips(items)
        if done:
            done(res)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t
