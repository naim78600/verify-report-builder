"""Make the reminder voice clips ONCE (run by .github/workflows/voices.yml; the result is committed to
src/report_builder/assets/voices/).  Free, offline model: Coqui TTS "tts_models/bn/custom/vits-male" (MIT; trained on
the IIT Madras Bangla corpus, so the accent is Kolkata-style - Naim: fine, as long as it is understood)."""
import sys
from pathlib import Path

CLIPS = {
    "general": "আসসালামু আলাইকুম। আপনার কাছে চলমান ফাইল আছে। মেসেজটি দেখে আজকের আপডেট দিন।",
    "appointment_today": "আসসালামু আলাইকুম। আজ আপনার অ্যাপয়েন্টমেন্ট আছে। আজই কাজটি শেষ করুন, আর মেসেজে উত্তর দিন।",
    "sla_passed": "আসসালামু আলাইকুম। আপনার ফাইলের সময় পার হয়ে গেছে। আজই শেষ করুন। মেসেজে ফাইল নম্বর দেওয়া আছে।",
    "bs_submit": "আসসালামু আলাইকুম। ব্যাংক স্টেটমেন্ট অফিসে জমা দিন। মেসেজে ফাইল নম্বর দেওয়া আছে।",
}

if __name__ == "__main__":
    from TTS.api import TTS
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "voices_out")
    out.mkdir(parents=True, exist_ok=True)
    tts = TTS("tts_models/bn/custom/vits-male", progress_bar=False)
    for name, text in CLIPS.items():
        tts.tts_to_file(text=text, file_path=str(out / f"{name}.wav"))
        print("made", name)
