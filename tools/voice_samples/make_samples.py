"""Voice SAMPLES for Naim to choose from (run by .github/workflows/voice-samples.yml; nothing here ships in the program).
A = Microsoft Edge read-aloud voice, Bangladesh, male (Pradeep)   B = same, female (Nabanita)   C = Google Translate voice (bn).
All three are free online voices; the clips are made once and then live inside the program (no cost while it runs)."""
import asyncio
import sys
from pathlib import Path

TEXT = {
    "general": "আসসালামু আলাইকুম। আপনার কাছে চলমান ফাইল আছে। মেসেজটি দেখে আজকের আপডেট দিন।",
    "sla_passed": "আসসালামু আলাইকুম। আপনার ফাইলের সময় পার হয়ে গেছে। আজই শেষ করুন। মেসেজে ফাইল নম্বর দেওয়া আছে।",
}
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)


async def edge():
    import edge_tts
    for tag, voice in (("A_male_Pradeep", "bn-BD-PradeepNeural"), ("B_female_Nabanita", "bn-BD-NabanitaNeural")):
        for name, text in TEXT.items():
            await edge_tts.Communicate(text, voice, rate="-8%").save(str(out / f"{tag}_{name}.mp3"))
            print("made", tag, name)

try:
    asyncio.run(edge())
except Exception as e:                                   # one source failing must not hide the other
    print("edge voices failed:", e)
try:
    from gtts import gTTS
    for name, text in TEXT.items():
        gTTS(text, lang="bn").save(str(out / f"C_google_{name}.mp3"))
        print("made C", name)
except Exception as e:
    print("google voice failed:", e)
