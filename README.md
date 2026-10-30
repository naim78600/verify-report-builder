# Verify Report Builder (ভেরিফাই রিপোর্ট বিল্ডার)

Windows ও Mac এর জন্য ডেস্কটপ সফটওয়্যার। লগইন করে শেষ N দিনের (আদিতে ৯০) Prime Bank PLC-এর সব ফাইল সংগ্রহ করে একটি এক্সেল রিপোর্ট বানায়।
**শুধু তথ্য পড়ে (GET); কোনো তথ্য বদলায় না।** পাসওয়ার্ড কোডে বা ফাইলে সংরক্ষণ হয় না।

## ব্যবহার (ব্যবহারকারীর জন্য)

1. ফাইল ডাউনলোড করুন (নিচে "GitHub থেকে ডাউনলোড") এবং unzip করুন।
2. অ্যাপ খুলুন → সার্ভার বাছুন → ইমেইল ও পাসওয়ার্ড দিন → **রিপোর্ট তৈরি করুন**।
3. শেষ হলে **এক্সেল খুলুন** চাপুন। ফাইল আদিতে `Documents/VerifyReports` ফোল্ডারে থাকে।

প্রথমবার খুললে সতর্কতা আসবে (ডিজিটাল স্বাক্ষর নেই বলে):

- **Windows:** “Windows protected your PC” → **More info → Run anyway**।
- **Mac:** অ্যাপে ডাবল ক্লিক করলে “can’t be opened” আসবে। তখন **System Settings → Privacy & Security** এ নিচে নামুন → “VerifyReportBuilder was blocked” এর পাশে **Open Anyway** চাপুন → পাসওয়ার্ড দিন।
  (পুরনো macOS-এ অ্যাপে ডান ক্লিক → Open কাজ করে। নতুন macOS-এ সাধারণত Open Anyway লাগে।)
  বিকল্প: Terminal এ `xattr -dr com.apple.quarantine ~/Downloads/VerifyReportBuilder.app`

## GitHub থেকে বিল্ড ও ডাউনলোড

1. নতুন **Private** রিপোজিটরি বানিয়ে এই সব ফাইল push করুন।
2. **Actions → Build desktop app → Run workflow**। প্রায় ৫–১০ মিনিটে শেষ হবে।
3. শেষ হলে রানের পাতার নিচে **Artifacts** থেকে ডাউনলোড করুন:
   `VerifyReportBuilder-Windows` (.exe), `VerifyReportBuilder-Mac-AppleSilicon` (M1/M2/M3/M4), `VerifyReportBuilder-Mac-Intel`।
4. স্থায়ী ডাউনলোড লিংক চাইলে ট্যাগ দিন: `git tag v1.0.0 && git push origin v1.0.0` → **Releases** এ zip ফাইল চলে আসবে।

> আপনার MacBook Apple Silicon (M-সিরিজ) হলে `Mac-AppleSilicon`, Intel হলে `Mac-Intel` নিন। (Apple menu → About This Mac এ দেখা যায়।)

## ডেভেলপারদের জন্য

```bash
pip install -r requirements-dev.txt
python run_app.py                      # জানালা
python -m pytest -q tests              # মক সার্ভারে পুরো ফ্লো পরীক্ষা (আসল সার্ভারে যায় না)
VERIFY_PASSWORD=... python run_app.py --cli --web https://verify.bmapsbd.com --email you@x.com --out report.xlsx
```

- `src/report_builder/client.py` – শুধু GET + অনুমোদিত পাথ তালিকা (Delete/Edit/Cancel/Logs/OCR ইত্যাদি কোডেই নেই)।
- `collect.py` – লগইন → তালিকা (৫০/পেজ) → প্রতিটি ফাইলের বিবরণ (একসাথে ৬টি, সর্বোচ্চ ৮) → ব্যর্থ ফাইল আলাদা।
- `remarks.py` – নিয়মভিত্তিক সংক্ষিপ্ত রিমার্কস (অফলাইন, ডেটা বাইরে যায় না)।
- `excel.py` – এক্সেল (Executive Summary, File Report, File/Trip Status, ডেটা শিট, Failed Files)।
- সেটিংস (`~/.verify_report_builder/settings.json`): `workers`, `org_name` বদলানো যায়। পাসওয়ার্ড কখনো লেখা হয় না।
