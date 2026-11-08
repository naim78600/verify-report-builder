# Verify Report Builder — Version 5 (v5.0.0)

Prime Bank PLC-এর দৈনিক সাবমিশন ট্র্যাকার (Complete + Incomplete, Excel + PDF) বানায়, ফাইল হিস্টরি তৈরি করে এবং সরাসরি ব্যাংককে ইমেইল পাঠায়। Verify থেকে **শুধু তথ্য পড়ে (GET)**, কিছু বদলায় না; পাসওয়ার্ড কোথাও সংরক্ষণ হয় না।

## ডাউনলোড

| সিস্টেম | ফাইল |
|---|---|
| Windows 64-bit | `VerifyReportBuilder-Setup-Windows-64bit.exe` |
| Windows 32-bit | `VerifyReportBuilder-Setup-Windows-32bit.exe` |
| Mac (Apple Silicon M1–M4) | `VerifyReportBuilder-Mac-AppleSilicon.dmg` |
| Mac (Intel) | `VerifyReportBuilder-Mac-Intel.dmg` |

`.zip` (portable) ফাইলও নিচে আছে। প্রথমবার খুললে ডিজিটাল স্বাক্ষর নেই বলে সতর্কতা আসে — Windows: *More info → Run anyway*; Mac: *System Settings → Privacy & Security → Open Anyway*।

## Version 5-এ নতুন

- **Done / Due শুধু ভেরিফায়ারের Remarks থেকে** — ব্যাক-অফিসের Comment (নির্দেশ) থেকে নয়। Payslip-বাক্য (“HR will verify only salary certificate”) এখন ঠিকভাবে পড়া হয়, ভুল “Head office disagree” আসে না।
- **File History ক্র্যাশ ঠিক:** ফাঁকা শিট থাকলে (যেমন সব নম্বর পাওয়া গেলে) `'MergedCell' object is not iterable` দিয়ে থেমে যেত — আর যায় না।
- **File History ইনপুট = File No + Applicant Name:** নমুনা Excel (অ্যাপের বোতামে বা `templates/File_History_Format.xlsx`); ফাইল নম্বর দিয়ে খোঁজা হয়, নামের জন্য Summary শিটে **Name Check** (Matches / Matches Guarantor / Different)।
- **আগের সব অপশন অপরিবর্তিত** (ট্র্যাকার, তারিখ-সীমা, Re-CPV, সাধারণ এক্সেল, ইমেইল, ছুটি, SLA ও Incomplete নিয়ম)।
- ১৪৩টি স্বয়ংক্রিয় টেস্ট + আসল অ্যাপ-উইন্ডোর GUI smoke test (File History সহ; Windows, macOS, Linux)।

## Version 4 থেকে চলছে

- **SLA Restart:** Appointment-এর *scheduled date* থেকে এবং **যেকোনো নতুন ট্রিপ** তৈরি হলে সঙ্গে সঙ্গে; In (Dhaka ও Chattogram City Corporation) = ২ কার্যদিবস, Out = ৪ কার্যদিবস। নতুন কলাম **“SLA Start / Restart Date”** (Excel ও PDF)।
- **Incomplete** = শুধু Hold, Finished কিন্তু Submit হয়নি ও Partially Submitted।

## সব ফিচার — প্রথম সংস্করণ থেকে Version 5 পর্যন্ত (বিস্তারিত)

প্রতিটি ধাপে আগের সব ফিচার থেকে যায়; নিচে কোন সংস্করণে কী যোগ হয়েছে ক্রমানুসারে লেখা।

### Version 1 — প্রথম সংস্করণ (৩১ অক্টোবর ২০২৬): ড্যাশবোর্ড থেকে এক্সেল রিপোর্ট

- **লগইন করে ফাইল সংগ্রহ:** ইমেইল ও পাসওয়ার্ড দিলে শেষ N দিনের (ডিফল্ট **৯০ দিন**) Prime Bank PLC-এর সব ফাইল Verify ড্যাশবোর্ড থেকে সংগ্রহ হয়।
- **সার্ভার বাছাই:** মূল সাইট (Production) / স্টেজিং / অন্য সার্ভার। স্টেজিং বা অন্য সার্ভারের ঠিকানা একবার দিলে মনে থাকে।
- **শুধু পড়ে, কিছু বদলায় না:** সব অনুরোধ GET; অনুমোদিত পাথের তালিকা কোডেই বাঁধা — Delete / Edit / Cancel / Logs-লেখা / OCR-এর কোনো কোডই নেই।
- **পাসওয়ার্ড কোথাও সংরক্ষণ হয় না** (কোডে, ফাইলে বা সেটিংসে)।
- **দ্রুত ও নিরাপদ সংগ্রহ:** তালিকা পেজ ধরে (৫০/পেজ), প্রতিটি ফাইলের বিবরণ একসাথে ৬টি (সর্বোচ্চ ৮) অনুরোধে; কোনো ফাইল ব্যর্থ হলে বাকি রিপোর্ট চলে, ব্যর্থ ফাইল আলাদা শিটে (**Failed Files**)।
- **নিয়মভিত্তিক সংক্ষিপ্ত রিমার্কস:** পুরোপুরি অফলাইন নিয়মে লেখা হয় — কোনো তথ্য বাইরে যায় না।
- **এক্সেল রিপোর্ট:** Executive Summary, File Report, File/Trip Status ও ডেটা শিট।
- **সহজ ব্যবহার:** শেষে ‘এক্সেল খুলুন’ বোতাম; ফাইল ডিফল্টে `Documents/VerifyReports` ফোল্ডারে।
- **বিল্ড:** GitHub Actions থেকে Windows (.exe) ও Mac (Apple Silicon / Intel) অ্যাপ।

### Version 2 (২ নভেম্বর) — Prime Bank Report, Re-CPV, ছুটি, ইমেইল কপি

- **Prime Bank Report (Excel + PDF)** দুই ধরনে: **ট্র্যাকার** (প্রতিদিনের 3 PM / 7 PM রিপোর্ট — Complete + Incomplete; শিরোনামের সময় ল্যাপটপের ঘড়ি থেকে, বিকাল ৫টার আগে 3pm, পরে 7pm; হাতেও বাছা যায়) ও **তারিখের সীমা** (যেমন ২০২৬-০৮-০১ থেকে ২০২৬-১১-০২)।
- **TAT ও Extra TAT** Excel-এ জীবন্ত ফর্মুলা (সংখ্যা নিজে বসানো নয়, তাই হাতে তারিখ বদলালে নিজে হিসাব হয়)।
- **Re-CPV সহ বিস্তারিত এক্সেল:** প্রতিটি ফাইলের নিচে Re-CPV / Extra; সঙ্গে `Billing Rows` ও `Calculation` শিট (ট্রিপ সংখ্যা মিলিয়ে দেখার জন্য)।
- **ছুটির তালিকা:** ২০২৭ পর্যন্ত সরকারি ছুটি ভিতরেই আছে। নতুন ছুটি লিখুন `2027-03-09 | 2027-03-11 | Eid ul Fitr` ধাঁচে (এক দিনের হলে শেষ তারিখ বাদ) অথবা CSV/টেক্সট ফাইল ইমপোর্ট করুন। তালিকা শেষ হওয়ার কাছে এলে সতর্ক করে।
- **ইমেইলের জন্য কপি:** ব্রাউজারে পাতা খোলে → **Copy** → Zoho Mail-এ Paste। ইমেইল সিগনেচার একবার সেট করা যায়।
- **চার-লক্ষ্য বিল্ড:** Windows 64-bit, Windows 32-bit, Mac Apple Silicon, Mac Intel।

### Version 2.1 (৫ নভেম্বর) — নতুন চেহারা ও ব্যাংকের হিসাব

- **নতুন ইউজার ইন্টারফেস:** বাঁদিকে মেনু, ডানে ৪টি ধাপ (লগইন → সময়সীমা → রিপোর্টের ধরন → কী তৈরি হবে); ছোট স্ক্রিনে উপরের অংশ স্ক্রল হয়, বোতাম নিচে স্থির।
- **সময়সীমা:** ‘শেষ কয়েক দিন’ অথবা ‘তারিখ বাছুন’ (তারিখ বাছলে দিনের ঘর বন্ধ)।
- **In / Out ও SLA:** In = ২ কার্যদিবস, Out = ৪ কার্যদিবস (শুক্র, শনি ও সরকারি ছুটি বাদ); সময় পেরোলে **SLA Breach**।
- **Bill Slab:** তৈরির দিনে ৩/৪/৫টি ট্রিপ = **Package**; ৬/৭/৮ নম্বর ট্রিপ = **Extra Trip 1/2/3** (আলাদা Single বিল)। প্রতিটি সারিতে ফাইলের পুরো ইতিহাস।
- **BS:** Bank ট্রিপ সব জায়গায় ‘BS’ (Bank Statement)।
- **নতুন কলাম:** *Last Update* (Activity Log থেকে ফাইল ও প্রতিটি ট্রিপের শেষ আপডেট, তারিখ-সময় সহ) এবং *Appointment* (ট্রিপ আইডি, ধরন, অ্যাপয়েন্টমেন্টের সময়, তৈরির সময়, কারণ; না থাকলে NO)।
- **নরম রং:** নেতিবাচকে চোখে-লাগা লাল নয়; ইতিবাচকে সবুজ; Out-এ ইন্ডিগো — Excel, PDF ও ইমেইল পাতায় একই রং।

### Version 2.2 (৫ নভেম্বর) — সঠিক In/Out, ট্র্যাকারের ভাষায় Done/Due, ফাইল হিস্টরি

- **In (সংশোধন):** শুধু Dhaka City Corporation (DNCC + DSCC) ও Chattogram City Corporation; গাজীপুর, নারায়ণগঞ্জ, সাভার, টঙ্গী … সব Out। প্যাকেজের একটি ট্রিপ Out হলে পুরো প্যাকেজ Out; Single / Extra / Re-CPV নিজ ঠিকানা অনুযায়ী।
- **Report Summary (Done / Due) ট্র্যাকারের ভাষায়:** `Done-App House, Office, Sign, LOI, BS1 (Insufficient fund), BS2, Co-App House` / `Due-0`। ক্রম: App → LOI/BS/ডকুমেন্ট → Co-App → PG। Bank ট্রিপ সবসময় BS (একাধিক হলে BS1, BS2); I/F = Insufficient fund; ফোন / ইমেইল / নাম কখনো লেখা হয় না। Done-এর সমস্যাগুলো (ব্র্যাকেটে) Due-তেও একই ভাষায় আসে, নরম পিচ রঙে হাইলাইট; সমস্যা না থাকলে `Due-0`।
- **দুই-শিটের Excel:** *Complete Report* ও *Incomplete Report* (সঙ্গে Summary, Holidays)। ফিল্টার-বোতাম শুধু **File No** ও **Last Update Date**-এ। Last Update ভাগ: **Last Update Date** (আসল তারিখ) ও **Last Update Details**।
- **রিপোর্ট দেখতে সুবিধা:** ব্যানার, KPI টাইল, ৭৫% জুম — পুরো রিপোর্ট এক স্ক্রিনে।
- **ফাইল হিস্টরি (নতুন রিপোর্টের ধরন):** ফাইল নম্বরের Excel/CSV দিন (পুরো নম্বর অথবা শেষের কয়েকটি অঙ্ক; অথবা নম্বর পেস্ট করুন) → প্রতিটি ফাইলের সম্পূর্ণ ইতিহাসের একটি Excel: Summary, Timeline (নতুন থেকে পুরোনো), Submission History, Trips, Appointments, Re-CPV & Extra, Concerns, Not Found। **সময়সীমা নেই।** ফাইল নম্বর ও তারিখ কম্পিউটারে (`~/.verify_report_builder/file_index.json`, কোনো ব্যক্তিগত তথ্য নেই) জমা থাকে, পরের বার শুধু নতুন দিন পড়ে। CLI: `--history numbers.xlsx`।

### Version 2.2.1 ও 2.2.2 (৫ নভেম্বর) — ড্যাশবোর্ডের সঙ্গে মিল

- **Submitted সংখ্যা ড্যাশবোর্ডের সঙ্গে মেলানো:** সফটওয়্যার ড্যাশবোর্ডের নিজের Submitted তালিকা পড়ে মিলিয়ে দেখে। Complete = ওই তারিখসীমার মধ্যে Submitted হওয়া সারি (Receive যেদিনই হোক)।
- **স্ক্রিনে মিলের ফল:** ‘ড্যাশবোর্ডের Submitted: ১৪ টি · রিপোর্টে মিলেছে: ১৪ টি ✓’; Excel-এর Summary শিটে ‘Dashboard check’ ব্লক।
- **ড্যাশবোর্ডের তারিখ-নিয়ম লাইভ সাইটে যাচাই করে মেলানো:** স্ট্যাটাস ছাড়া = ফাইলের Start Date; স্ট্যাটাস দিয়ে = ফাইল বর্তমান স্ট্যাটাসে যেদিন ঢুকেছে। ফাইলের তালিকা দুই ধরনের মিলন, তাই পরে Submitted/Hold হওয়া ফাইলও ধরা পড়ে।

### Version 2.3.0 (৬ নভেম্বর) — ব্যাংকের পাঠানো আসল মেইল মিলিয়ে নিয়ম

- Zoho Sent-এর ট্র্যাকার মেইল (১৮/১০ – ০৫/১১), ব্যাংকের Excel (৩৭১৪ সারি) ও লাইভ activity log পাশাপাশি রেখে **Complete / Incomplete-এর নিয়ম** ঠিক করা।
- **Complete =** activity log-এর `status updated to SUBMITTED` ঘটনার দিন।
- **ছুটির দিনের সাবমিশন পরের কর্মদিবসে:** শুক্র / শনি / ছুটিতে Submitted সারি পরের কর্মদিবসের ট্র্যাকারে যায়; Submission Date ও TAT সেই কর্মদিবস ধরে; Check List-এ আসল সাবমিশন সময় থাকে।
- **‘Incomplete তালিকা’ অপশন:** আজকের Partial / চলমান Partial সহ / সব Pending (এই অপশন পরে v3.2-এ ড্যাশবোর্ড-স্ট্যাটাসের নিয়মে বদলে গেছে)।

### Version 3.0.0 (৬ নভেম্বর) — দিনে দুইবার স্বয়ংক্রিয় ট্র্যাকার ও সরাসরি মেইল

- **দুই ফেজ:** *1st (3:30 PM মেইল)* = বিকাল ৩টা পর্যন্ত অবস্থা; *2nd (7:00 PM)* = পুরো দিন। ‘শুধু ৩টার পরের সাবমিশন’ টিক দিলে ১ম ফেজে যা গেছে তা বাদ। Excel-এ ‘Before / After 3 PM’ কলাম।
- **একটিই সম্পাদনাযোগ্য Excel** (Complete Report · Incomplete Report · Summary · Holidays · Check List) — ‘ব্যাংক কপি / অভ্যন্তরীণ কপি’ আর নেই। ফাইলের নাম `Prime_Bank_Submission_Tracker_YYYY-MM-DD_Phase1|Phase2.xlsx`।
- **হালকা আকাশি নীল ঘর = ‘এখানে কারণ পাওয়া যায়নি, লিখে দিন’।** Excel-এ লিখে সেভ করে উইন্ডোতে ‘আবার যাচাই করুন’ চাপলে নীল ঘর নতুন করে গোনে। *Check List* শিটে কারণ।
- **সরাসরি ইমেইল (Zoho SMTP):** To / Cc / Bcc (ডিফল্ট To = ব্যাংকের ৩ জন, বদলালে মনে থাকে); **৩টি বার্তার নমুনা** (Formal / Concise / Executive — সংখ্যা নিজে থেকে বসে, চাইলে এডিট); সিগনেচার (নাম · পদ · ফোন · Barikoi Technologies Limited · লোগো); সংযুক্তি = পাঠানোর মুহূর্তের সর্বশেষ Excel (অভ্যন্তরীণ *Check List* শিট স্বয়ংক্রিয়ভাবে বাদ)।
- **নিরাপদ পাঠানো:** আগে ‘নিজেকে টেস্ট পাঠান’ (শুধু verify@barikoi.com-এ); একই তারিখ + ফেজের মেইল আগে গেলে সতর্কতা (দুইবার না যাওয়ার জন্য); সাইডবারে ‘পাঠানো ইমেইল’-এর তালিকা; **Zoho App Password ফাইলে সেভ হয় না**; সার্ভার সেটিং (`smtp.zoho.com`, SSL ৪৬৫; `.in` / `.eu` / `.com.au` অ্যাকাউন্টের জন্য বদলানো যায়)।
- **কমান্ড লাইন / Task Scheduler:** `--prime --mode tracker --slot 3pm|7pm --send-mail --template formal|concise|executive`, `--to/--cc/--bcc`, `--after3`, `--pdf`, `--keep-checklist`, `--force`।
- **Incomplete-এ SLA + Partial নিয়ম** এবং ড্যাশবোর্ডের Submitted তালিকার সঙ্গে স্বয়ংক্রিয় মিলান (*Check List* শিটে প্রতিটি ফাইল কখন সাবমিট হলো ও কোন মেইলে গেল)।

### Version 3.1.0 / 3.1.1 / 3.1.2 (৬ নভেম্বর)

- **3.1.0:** Incomplete তালিকা **ফাইল ধরে** ঠিক হয় (ড্যাশবোর্ডের সঙ্গে মেলে) ও ফেজের হিসাব মিলিয়ে নেওয়া হয়।
- **3.1.1:** একটি সারি পাতার চেয়ে লম্বা হলেও PDF আর থামে না।
- **3.1.2:** **পড়ার মতো PDF** — বড় ফন্ট (৮.৬), নতুন কলাম-প্রস্থ, লম্বা ঘর সংক্ষেপ (পুরো লেখা Excel-এ)। **Inactive ট্রিপ** আর ‘ভুতুড়ে’ Incomplete সারি বানায় না।

### Version 3.2.0 (৬ নভেম্বর) — স্ট্যাটাস-ভিত্তিক Incomplete, এক ফাইল = এক সারি

- **Incomplete ড্যাশবোর্ড-স্ট্যাটাস ধরে:** Hold → কারণ = Hold-এর সময়ের comment (না থাকলে Appointment); Finished কিন্তু Submit হয়নি; Partially Submitted (বাকি ডকুমেন্টসহ)।
- **এক ফাইল = এক সারি:** Incomplete-এ সবসময়; Complete-এ একই দিনের Re-CPV / Extra আলাদা সারিতে দ্বিতীয়বার আসে না (Package + Single আলাদা বিল হলে দুটোই থাকে)। পুরো ইতিহাস Bill Slab কলামে।
- **Pending Reason কলাম** Excel ও PDF-এ (নিয়ম ও সংক্ষিপ্ত রূপসহ); PDF-এ File No ও Receive Date প্রশস্ত।
- **Area নিয়ম:** Panchlaish = Chattogram City Corporation (ওয়ার্ড ০৩ → In); Keraniganj, Gazipur, Tongi, Savar … Out; সীমানার কাছে ঠিকানার লেখা জেতে (নীল ঘর + Check List)।

### Version 3.2.1 (৬ নভেম্বর) — শুধু প্রয়োজনীয় Incomplete, Report Summary ফাইলের শেষ আপডেট ধরে

- **চলমান (On Going / Created) ফাইল Incomplete-এ কখনো আসে না** — SLA পেরোলেও না। তালিকায় শুধু Hold, Finished-not-submitted ও Partially Submitted; ট্র্যাকার ও তারিখ-সীমা দুই রিপোর্টেই।
- **Report Summary একই ফাইলের একাধিক সারির সব ট্রিপ বিবেচনা করে:** পরে তৈরি LOI ট্রিপে ফল Completed হলে Due-র পুরনো লেখা সরে Done-এ আসে (শেষ আপডেটই জেতে)।

### Version 4.0.0 (৮ নভেম্বর) — SLA Restart ও সর্বশেষ activity-নির্ভর Done/Due

- **নতুন SLA নিয়ম (ব্যাংকের চূড়ান্ত):** In = ২ কার্যদিবস, Out = ৪ কার্যদিবস। **Appointment** দিলে সর্বশেষ Appointment-এর *scheduled date* থেকে (শুক্র / শনি / ছুটি হলে পরের কর্মদিবস ধরে) আবার গোনা শুরু; **যেকোনো নতুন ট্রিপ** (Re-CPV, Extra / Additional, Single …) তৈরি হলে তৈরির দিন থেকেই সঙ্গে সঙ্গে restart, কোনো দেরি নেই। একাধিক কারণ থাকলে সবচেয়ে পরের তারিখ। মৃত ট্রিপে (Canceled / Inactive / Withdrawn) restart হয় না।
- **ফাইল-ভিত্তিক SLA:** একই ফাইলের অন্য বিল-সারির নতুন ট্রিপও গোনা হয়; একই দিনে Package-এ মিশে যাওয়া Re-CPV / Extra-র restart-ও দেখানো সারিতে ধরা হয়।
- **নতুন কলাম “SLA Start / Restart Date”** (Excel ও PDF, Receive Date-এর পরে); TAT এই তারিখ থেকে গোনা হয়। restart হলে ঘর **বেগুনি (plum)** এবং সহজ ভাষায় লেখা: *“SLA restarted from DD/MM/YYYY (N working days again, from the latest appointment date / from the new trip created on DD/MM/YYYY)”*। Summary শিটে ‘SLA restarted (appointment / new trip)’ সারি।
- **Report Summary (Done / Due) সবসময় সর্বশেষ activity ধরে:** একই বাক্যের বিষয় ধরে সমস্যা বসে (Office-এর লেখায় ‘LOI verify করতে রাজি নয়’ = LOI-এর সমস্যা); ভুল বানানের ‘LOI signed’ চেনা যায়; ‘..’ দিয়ে আলাদা বাক্য; একই সাবমিশনের পরের LOI ট্রিপ পুরনো Done/Due খুলে বা বন্ধ করে দেয়; ‘Can be verified from <নাম> branch’ নোট চেনা যায়।
- **নতুন স্বয়ংক্রিয় পরীক্ষা:** মোট **১২৯টি টেস্ট** (SLA restart-এর ১৩টিসহ) এবং **GUI smoke test** — আসল অ্যাপ-উইন্ডো মক সার্ভারে চালিয়ে ট্র্যাকার (Excel + PDF), ইমেইল উইন্ডো, ছুটির উইন্ডো, তারিখ-সীমার রিপোর্ট ও ‘পাসওয়ার্ড সেভ হয় না’ যাচাই; GitHub Actions-এ Windows, macOS ও Linux তিনটিতেই।
- **লাইভ ৯০ দিনের ডেটায় ফল:** ১৫২৫ সারির মধ্যে ৫৯৪টিতে Appointment ও ২১৫টিতে নতুন ট্রিপের কারণে SLA restart; SLA Breach ৫১১ থেকে ১০২।

---

### Version 5.0.0 (৮ নভেম্বর) — Done / Due শুধু Remarks থেকে, File History-র সংশোধন ও File No + Applicant Name Excel

- **Done / Due (Report Summary) এখন শুধু ভেরিফায়ারের Remarks থেকে লেখা হয়, ব্যাক-অফিসের Comment থেকে নয়।** *Comment* = ফাইল তৈরির সময় ব্যাক-অফিস ভেরিফায়ারকে যে **নির্দেশ** দেয় (যেমন “LOI will be signed from head office”); *Remarks* = কাজ শেষে ভেরিফায়ার যা **পেয়েছে** তার বর্ণনা। আগে Comment-এর নির্দেশও Done / Due-তে নোট হিসেবে ঢুকে যেত (যেমন নির্দেশের “Will be signed from head office” Done ও Due দুটোতেই আসত)। এখন Comment কেবল একটি কাজে লাগে — “Document” ট্রিপটি আসলে কিসের (LOI, Payslip, Tuition, Rental …) তা চেনা; ফলাফল, সমস্যা ও কারণ সবই Remarks (ও চলমান ট্রিপের সর্বশেষ Appointment-এর কারণ) থেকে।
- **Payslip বাক্যের ভুল পড়া ঠিক:** “HR payslip will be not verified. HR will verified only salary certificate.” আগে ভুল করে “Head office disagree” নোটও দিত। এখন ফল: `Done-… LOI (HR verifies salary certificate only)` / `Due-LOI (HR verifies salary certificate only)` — Comment যা-ই লেখা থাকুক। (সত্যিকারের “HR does not agree to verify the LOI” লেখা থাকলে “Head office disagree” আগের মতোই আসে।) Comment-এর কোনো শব্দে (“different”, “current”, “parent”) আর ভুল করে *Rental* আইটেম বসে না।
- **File History ক্র্যাশ ঠিক:** কোনো শিট ফাঁকা থাকলে (যেমন সব নম্বর পাওয়া গেলে ‘Not Found’ শিটে কিছুই থাকে না) Excel বানানোর সময় `TypeError: 'MergedCell' object is not iterable` দিয়ে পুরো রান থেমে যেত। কারণ: ফাঁকা শিটে ফ্রিজ-করা ঘরটি “কিছু নেই” লেখা মার্জ-করা সারির ভিতরে পড়ত। এখন কোনো শিট ফাঁকা হলেও ইতিহাস ঠিকভাবে তৈরি হয় (‘Not Found’ শিটে “Every number was found.” লেখা থাকে)।
- **File History-র ইনপুট Excel: `File No` + `Applicant Name`।** শুধু দুটি কলাম দিলেই ইতিহাস চলে আসে। শিরোনাম-শব্দ (File No / Tracking No …, আর Applicant / Customer / Name / আবেদনকারী / নাম) দেখে কলাম চেনা হয়; ফাইল নম্বর পুরো (`CC-…`) বা শেষের কয়েকটি অঙ্ক — দুটোই চলে; নাম ঐচ্ছিক (না দিলে আগের মতোই)। ফাইল নম্বর *নাম দিয়ে* খোঁজা হয় না — নম্বর দিয়েই খোঁজা হয়, নাম মেলানোর জন্য।
- **Name Check:** নাম দেওয়া থাকলে Summary শিটে তিনটি নতুন কলাম — *Applicant Name (given)*, *Name Check*, *Applicant on the file*। **Matches** = একই ব্যক্তি (Md. / Mohammad, শব্দের ক্রম, একটি শব্দ কম, ছোট বানান-ভুল সহনীয়); **Matches Guarantor 1 / Co-Applicant** = নামটি ফাইলের অন্য concern-এর; **Different** = ফাইলের Applicant অন্য নাম (পাশের কলামে দেখানো)। ‘Not Found’ শিটেও দেওয়া নাম থাকে। নাম না দিলে শিটগুলো হুবহু আগের মতো।
- **নমুনা Excel:** ‘ফাইল হিস্টরি’ বাছলে ‘⬇ নমুনা Excel (File No + Applicant Name) সংরক্ষণ করুন’ বোতাম; রিপোজিটরিতেও আছে: `templates/File_History_Format.xlsx` (প্রথম শিটে দুই কলাম + ৫০০ প্রস্তুত সারি; File No কলাম Text ফরম্যাটে যাতে শুরুর শূন্য কখনো হারায় না; দ্বিতীয় শিটে কীভাবে ভরতে হবে)।
- **আগের কোনো অপশন বদলায়নি:** ট্র্যাকার, তারিখ-সীমা, Re-CPV, সাধারণ এক্সেল, ইমেইল, ছুটি, SLA নিয়ম, Incomplete নিয়ম — সবই Version 4-এর মতো (শুধু Done / Due-র Comment-নির্ভরতা বাদ)।
- **পরীক্ষা:** মোট **১৪৩টি স্বয়ংক্রিয় টেস্ট** (Version 5-এর ১৪টি নতুন: ক্র্যাশ, নাম-সহ ইনপুট, Name Check, নমুনা Excel, Comment-বনাম-Remarks, এবং ড্যাশবোর্ড→ট্র্যাকার Excel পর্যন্ত end-to-end) এবং আসল অ্যাপ-উইন্ডোর GUI smoke test-এ এখন File History ধাপও আছে (Windows, macOS, Linux)।

---

নিয়মের পূর্ণ বিবরণ, পুরো ওয়ার্কফ্লো, কমান্ড লাইন ও ইতিহাস: রিপোজিটরির `README.md`।
