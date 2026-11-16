"""Make the reminder voice clips ONCE (run by .github/workflows/voices.yml; the result is committed to
src/report_builder/assets/voices/).  Voice: Microsoft Edge read-aloud "bn-BD-PradeepNeural" (Bangladesh, male) -
Naim's choice (16 Nov 2026).  A free online voice: the clips are made here once and then live inside the program,
so nothing is asked from the internet while the program runs."""
import asyncio
import sys
from pathlib import Path

VOICE = "bn-BD-PradeepNeural"
CLIPS = {
    "general": "আসসালামু আলাইকুম। আপনার কাছে চলমান ফাইল আছে। মেসেজটি দেখে আজকের আপডেট দিন।",
    "appointment_today": "আসসালামু আলাইকুম। আজ আপনার অ্যাপয়েন্টমেন্ট আছে। আজই কাজটি শেষ করুন, আর মেসেজে উত্তর দিন।",
    "sla_passed": "আসসালামু আলাইকুম। আপনার ফাইলের সময় পার হয়ে গেছে। আজই শেষ করুন। মেসেজে ফাইল নম্বর দেওয়া আছে।",
    "bs_submit": "আসসালামু আলাইকুম। ব্যাংক স্টেটমেন্ট অফিসে জমা দিন। মেসেজে ফাইল নম্বর দেওয়া আছে।",
}


async def main(out: Path):
    import edge_tts
    for name, text in CLIPS.items():
        await edge_tts.Communicate(text, VOICE, rate="-8%").save(str(out / f"{name}.mp3"))
        print("made", name)

if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "voices_out")
    out.mkdir(parents=True, exist_ok=True)
    asyncio.run(main(out))
