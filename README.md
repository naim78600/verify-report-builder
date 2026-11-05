# Verify Report Builder v2.2 (ভেরিফাই রিপোর্ট বিল্ডার)

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

## v2.2 এ যা বদলেছে

- **In / Out (সংশোধন):** শুধু **Dhaka City Corporation (DNCC + DSCC)** ও **Chattogram City Corporation** = In। গাজীপুর, নারায়ণগঞ্জ, সাভার, টঙ্গী … সব Out। প্যাকেজের একটি ট্রিপ Out হলে পুরো প্যাকেজ Out; Single/Extra/Re-CPV নিজ ঠিকানা অনুযায়ী। SLA: In = ২, Out = ৪ কার্যদিবস।
- **Report Summary (Done / Due):** ট্র্যাকারের ভাষায় — `Done-App House, Office, Sign, LOI, BS1 (Insufficient fund), BS2, Co-App House` / `Due-0`। ক্রম: App → LOI/BS/ডকুমেন্ট → Co-App → PG। Bank ট্রিপ সবসময় **BS** (একাধিক হলে BS1, BS2)। **I/F = Insufficient fund।** ফোন/ইমেইল/নাম লেখা হয় না। Done-এর **সমস্যাগুলো (ব্র্যাকেটে) Due-তেও হুবহু একই ভাষায়** আসে, নরম পিচ রঙে হাইলাইট করা; সমস্যা না থাকলে `Due-0`।
- **Excel:** দুটি শিট — **Complete Report** ও **Incomplete Report** (সঙ্গে Summary, Holidays; অভ্যন্তরীণ কপিতে Check List)। ফিল্টার-বোতাম শুধু **File No** ও **Last Update Date**-এ। *Last Update* ভাগ হয়েছে: **Last Update Date** (আসল তারিখ, ফিল্টার করা যায়) ও **Last Update Details** (ফাইলের শেষ আপডেট + প্রতিটি ট্রিপের আইডি/ধরন সহ শেষ লাইন; ফিল্টার নেই)। ব্যানার, KPI টাইল, ৭৫% জুম — পুরো রিপোর্ট স্ক্রিনে ধরে।
- **রং:** লাল ও হলুদ কোথাও নেই। সবুজ/টিল = ভালো, নরম কমলা = নেতিবাচক, ইন্ডিগো = Out, **হালকা আকাশি নীল = অভ্যন্তরীণ কপিতে ‘যাচাই করুন’**।
- **ফাইল হিস্টরি (নতুন):** ‘রিপোর্টের ধরন’-এ **ফাইল হিস্টরি** বাছুন → ফাইল নম্বরের Excel/CSV দিন (পুরো নম্বর অথবা শেষের কয়েকটি অঙ্ক, শূন্য যোগ করতে হবে না; অথবা নম্বর পেস্ট করুন)। সফটওয়্যার প্রতিটি ফাইল খুঁজে সম্পূর্ণ ইতিহাসের একটি Excel বানায়: Summary, Timeline (নতুন থেকে পুরোনো), Submission History (`2026-09-08 Done-PG. Due-App …` ধাঁচে — ড্যাশবোর্ডের ঘটনা থেকে হিসাব করা, আনুমানিক), Trips, Appointments, Re-CPV & Extra, Concerns, Not Found। **সময়সীমা নেই।** প্রথমবার সব ফাইলের তালিকা পড়তে কয়েক মিনিট লাগতে পারে; ফাইল নম্বর ও তারিখ কম্পিউটারে (`~/.verify_report_builder/file_index.json`, কোনো ব্যক্তিগত তথ্য নেই) জমা থাকে, পরের বার শুধু নতুন দিন পড়ে। না পেলে **File not found**, বাকি ফাইলের ইতিহাস ঠিকই আসে। এটিও শুধু পড়ে (GET)।
- **কমান্ড লাইন:** `python run_app.py --cli --email you@x.com --history numbers.xlsx --outdir out` (পাসওয়ার্ড `VERIFY_PASSWORD` পরিবেশ চলকে বা প্রম্পটে)।

## v2.1 এ যা বদলেছে

- **নতুন চেহারা:** বাঁদিকে মেনু, ডানে ৪টি ধাপ (লগইন → সময়সীমা → রিপোর্টের ধরন → কী তৈরি হবে)। ছোট স্ক্রিনে উপরের অংশ স্ক্রল হয়, বোতাম নিচে স্থির।
- **সময়সীমা:** ‘শেষ কয়েক দিন’ (যেমন 60) অথবা ‘তারিখ বাছুন’। তারিখ বাছলে দিনের ঘর বন্ধ হয়ে যায়। ‘বিলিং’ শব্দ বাদ।
- **In / Out:** Dhaka city, Gazipur city, Narayanganj city — এই তিন এলাকার ভিতরে (ম্যাপ/lat-long) হলে In, বাকি সব Out। প্যাকেজের একটি ট্রিপও Out হলে পুরো প্যাকেজ Out; Single/Extra/Re-CPV নিজ নিজ ঠিকানা অনুযায়ী।
- **SLA:** In = ২ কার্যদিবস, Out = ৪ কার্যদিবস (শুক্র, শনি ও সরকারি ছুটি বাদ), Receive Date (= তৈরির তারিখ) থেকে। বেশি হলে ‘SLA Breach’।
- **Bill Slab:** তৈরির দিনে ৩/৪/৫টি ট্রিপ = Package; ৬/৭/৮ নম্বর ট্রিপ = Extra Trip 1/2/3 (আলাদা Single বিল)। প্রতিটি সারিতে ফাইলের **পুরো ইতিহাস** (প্রথম থেকে শেষ) থাকে।
- **BS:** Bank ট্রিপ সব জায়গায় ‘BS’ (Bank Statement)।
- **নতুন কলাম:** *Last Update* (Activity Log থেকে: ফাইল ও প্রতিটি ট্রিপের শেষ আপডেট, তারিখ-সময় সহ) এবং *Appointment* (ট্রিপ আইডি, ধরন, অ্যাপয়েন্টমেন্টের সময়, তৈরির সময় সেকেন্ড সহ, কারণ; না থাকলে NO)।
- **রং:** নেতিবাচক জিনিসে চোখে-লাগা লাল নয়, নরম অ্যাম্বার; ইতিবাচকে সবুজ; Out-এ ইন্ডিগো। Excel, PDF ও ইমেইল পাতায় একই রং।

## v2 এর নতুন সুবিধা

v1 এর সব অপশন আগের মতোই আছে। নতুন চারটি:

1. **Prime Bank Report** – Excel + PDF।
   - *ট্র্যাকার* ধরন: প্রতিদিনের 3pm/7pm রিপোর্ট (Complete + Incomplete)। শিরোনামের সময় ল্যাপটপের ঘড়ি থেকে (বিকাল ৫টার আগে 3pm, পরে 7pm), চাইলে নিজে বাছা যায়।
   - *বিলিং* ধরন: তারিখের সীমা (যেমন 2026-08-01 থেকে 2026-11-02)।
   - দুই কপি: **ব্যাংক কপি** (পরিষ্কার) ও **অভ্যন্তরীণ কপি** (হলুদ ঘর = মানুষকে দেখে নিতে হবে + Check List শিট)।
   - TAT / Extra TAT এক্সেলে জীবন্ত ফর্মুলা; ছুটির তালিকা `Holidays` শিটে।
2. **Re-CPV সহ এক্সেল রিপোর্ট** – v1 এর বিস্তারিত রিপোর্ট, প্রতিটি ফাইলের নিচে Re-CPV/Extra, সাথে `Billing Rows` ও `Calculation` শিট (ট্রিপ সংখ্যা মিলিয়ে দেখা)।
3. **ছুটির তালিকা** – ২০২৭ পর্যন্ত আছে। নতুন ছুটি যোগ করতে প্রতি লাইনে লিখুন:
   `2027-03-09 | 2027-03-11 | Eid ul Fitr` (শুরু | শেষ | নাম; এক দিনের হলে শেষ তারিখ বাদ দিন) অথবা CSV/টেক্সট ফাইল ইমপোর্ট করুন। তালিকা শেষ হওয়ার কাছাকাছি হলে সতর্কতা দেখায়।
4. **ইমেইলের জন্য কপি** – ব্রাউজারে পাতা খোলে; **Copy** চেপে Zoho Mail এ Paste করুন। সফটওয়্যার নিজে কখনো ইমেইল পাঠায় না। সিগনেচার **ইমেইল সিগনেচার** বোতামে একবার সেট করুন।

CLI: `python run_app.py --cli --prime --email you@x.com --mode tracker --outdir out`
তারিখের সীমা: `python run_app.py --cli --prime --email you@x.com --mode range --from 2026-08-01 --till 2026-11-02 --outdir out`

> হলুদ ঘর: Dhaka ভিতরে/বাইরে (In/Out), Report Summary, বাতিল ট্রিপ — যেখানে সফটওয়্যার নিশ্চিত নয়। অভ্যন্তরীণ কপিতে দেখে নিন।

## GitHub থেকে বিল্ড ও ডাউনলোড

1. নতুন **Private** রিপোজিটরি বানিয়ে এই সব ফাইল push করুন।
2. **Actions → Build desktop app → Run workflow**। প্রায় ৫–১০ মিনিটে শেষ হবে।
3. শেষ হলে রানের পাতার নিচে **Artifacts** থেকে ডাউনলোড করুন:
   `Windows-64bit`, `Windows-32bit`, `Mac-AppleSilicon` (M1–M4), `Mac-Intel` (macOS 13 Ventura বা নতুন)।
4. স্থায়ী ডাউনলোড লিংক চাইলে ট্যাগ দিন: `git tag v2.0.0 && git push origin v2.0.0` → **Releases** এ zip ফাইল চলে আসবে।

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
- `billing.py`, `activity.py`, `recpv.py`, `summary.py`, `geo.py`, `holidays.py` – v2 এর বিলিং নিয়ম, অ্যাক্টিভিটি লগ, Re-CPV, Done/Due, In/Out, ছুটি।
- `prime_excel.py`, `prime_pdf.py`, `email_copy.py` – Prime Bank Excel/PDF/ইমেইল পাতা।
- `excel.py` – এক্সেল (Executive Summary, File Report, File/Trip Status, ডেটা শিট, Failed Files)।
- সেটিংস (`~/.verify_report_builder/settings.json`): `workers`, `org_name` বদলানো যায়। পাসওয়ার্ড কখনো লেখা হয় না।
