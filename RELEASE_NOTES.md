# Verify Report Builder — Version 10 (v10.0.1)

Prime Bank PLC ও LankaBangla-র কাজের জন্য: দৈনিক সাবমিশন ট্র্যাকার, মাসিক বিল, ফাইল হিস্টরি — আর নতুন **BS ট্র্যাকার**, **অফিস রিসিভ** ও **WhatsApp রিমাইন্ডার**। Verify থেকে **শুধু তথ্য পড়ে (GET)**, কিছু বদলায় না; পাসওয়ার্ড কোথাও সংরক্ষণ হয় না।

## Version 10-এ নতুন

| | কী বদলেছে |
|---|---|
| **নতুন উইন্ডো** | খোলার সময় ভাষা বাছুন (**বাংলা / English**) ও লগইন; সাদা সাইডবার: আজ · দৈনিক ট্র্যাকার · মাসিক বিল · BS ট্র্যাকার · অফিস রিসিভ · রিমাইন্ডার · ভেরিফায়ার · ফাইল হিস্টরি · সেটিংস |
| **A4 রিপোর্ট** | PDF ও Excel দুটোই **A4 landscape, সব কলাম** (Sample 1 – A4 Classic); ট্র্যাকার Excel-এর প্রতিটি কলামে ফিল্টার |
| **ফেজের সময়** | ১ম ফেজ **দুপুর ১২:০০**, ২য় ফেজ **সন্ধ্যা ৬:১৫**; কলাম “Before / After 12 PM” |
| **BS ট্র্যাকার** | প্রতি BS একটি সারি (এক ফাইলে দুটো BS পরপর); অনলাইন / অফলাইন ব্যাংক নিজে চেনে; ভেরিফায়ারের রিমার্ক থেকে BS তোলা হয়েছে কি না নিজে বোঝে; মাসিক Excel; ক্লায়েন্টের সই করা লিস্ট (Excel / PDF / ছবি) আপলোড করলে কোনটা রিসিভ হয়নি দেখায়; কুরিয়ার নম্বর, স্লিপের ছবি, অবস্থা |
| **অফিস রিসিভ** | Trip ID বা File No লিখলেই বাকিটা নিজে আসে; সারাদিনের তালিকা; দিনশেষে A4 “আজ রিসিভ হয়েছে” শিট প্রিন্ট করে সই; Excel ফর্ম পূরণ করে আপলোডও করা যায় |
| **১২:০০ ও ৬:১৫ BS চেক** | সব বাকি BS (কোনো সীমা নেই) নিজে থেকে দেখায় |
| **WhatsApp রিমাইন্ডার** | ১০টা, ১টা ও ৪টা (প্রতিবার সব চলমান ও হোল্ড ট্রিপ; ১০টায় BS জমার তাগিদ নেই) — দুই ক্লায়েন্ট; SLA পার / আজ শেষ আগে; পরের দিনের অ্যাপয়েন্টমেন্ট বাদ। হেল্পার প্রতিটি চ্যাট মেসেজ লিখে ও ভয়েস যুক্ত করে খোলে, **Send আপনি চাপেন**; উত্তর নিজে পড়ে বোঝে (যাচ্ছি / শেষ / সমস্যা + কারণ); দিনের সারাংশ শুধু সফটওয়্যারে |
| **ভেরিফায়ার** | ড্যাশবোর্ডের নম্বর; WhatsApp নেই / নম্বর ভুল = লাল; নম্বর বদলানো বা যোগ করা যায় |
| **আগের নিয়ম** | ট্র্যাকার, বিল, ফাইল হিস্টরি, SLA, Incomplete, ইমেইল — সব আগের মতোই |

## প্রথমবার: WhatsApp হেল্পার (১ মিনিট)
Chrome → `chrome://extensions` → **Developer mode** চালু → **Load unpacked** → প্রোগ্রামের **রিমাইন্ডার → হেল্পার সেটআপ** যে ফোল্ডার খোলে সেটি বাছুন। তারপর web.whatsapp.com খুললে ডানদিকে নিচে “Barikoi helper” দেখাবে।

## ডাউনলোড

| সিস্টেম | ফাইল |
|---|---|
| Windows 64-bit | `VerifyReportBuilder-Setup-Windows-64bit.exe` |
| Windows 32-bit | `VerifyReportBuilder-Setup-Windows-32bit.exe` |
| Mac (Apple Silicon M1–M4) | `VerifyReportBuilder-Mac-AppleSilicon.dmg` |
| Mac (Intel) | `VerifyReportBuilder-Mac-Intel.dmg` |

`.zip` (portable) ফাইলও নিচে আছে। প্রথমবার খুললে ডিজিটাল স্বাক্ষর নেই বলে সতর্কতা আসে — Windows: *More info → Run anyway*; Mac: *System Settings → Privacy & Security → Open Anyway*।

## Technical memo — every rule, by function (for developers)

**For:** the developers of the Verify dashboard · **From:** Barikoi operations (Prime Bank PLC desk) · **Version:** 10.0.1 · **Date:** 15 November 2026

Verify Report Builder is a desktop tool that reads the Verify dashboard (GET only) and produces what is sent to Prime Bank PLC:
the daily submission tracker, the monthly bill, and the file history. This memo writes down every rule the tool applies, from the
first one to the last, grouped by function, so the same logic can be built into the dashboard itself. Each section names the
function in this repository that is the reference implementation; the automated tests (`tests/`, 179 of them) are the executable
form of the rules.

Words used below:

| Term | Meaning |
|---|---|
| File | one application on the dashboard (`application_id` is the file number, e.g. `PL-2026…`, `CC-2026…`) |
| Concern | a person on the file: `APPLICANT`, `CO_APPLICANT`, `GUARANTOR` |
| Trip | one task of a concern: `HOUSE`, `OFFICE`, `BANK`, `DOCUMENT`, `GUARANTOR_HOUSE`, `GUARANTOR_OFFICE`, `RENTAL`, `CAR_QUATATION`, `DOC_DRCHAMBER`, `DOC_TUITION`, … |
| File status | 1 Created · 2 On Going · 3 Hold · 4 Finished · 5 Canceled · 6 Submitted · 7 Partially Submitted · 8 Withdrawn |
| Trip status | 1 Created · 2 Allocated · 3 Started · 4 Hold · 5 Finished · 6 Canceled · 7 Inactive · 8 Withdrawn |
| Bill row | one billable event of a file. The tracker and the bill are both lists of bill rows |
| Working day | Sunday–Thursday, minus the holiday list (Friday, Saturday and listed holidays are off) |

---

## 1. Data that is read

Reference: `client.py`, `collect_prime.py`, `model.py`, `activity.py`, `recpv.py`.

| Call (GET) | Used for |
|---|---|
| `/api/v2/auth/user` | the organisation uuid of "Prime Bank PLC" |
| `/api/v2/manager/applications` (dateFrom, dateTill, org_id[], status[], page, sort) | file lists. **Without** `status[]` the dates mean the file's Start Date (received). **With** `status[]` they mean the day the file entered its current status (Submitted = submission day) |
| `/api/v2/manager/applications/{id}` | the file: concerns, trips (type, status, created_at, start_time, end_time, remarks, comment, address, coordinates, end coordinates, appointments) |
| `/api/v2/applications/activity-logs?application_id=` | when the file was created / Submitted / Partially Submitted, when each trip finished, and the last update |
| `/api/v2/re-cpv/tracker` (one year back) | which trips are Re-CPV |

Rules:

1. Nothing is ever written; only the paths above are allowed.
2. The file type is taken from the file number: `PL…` = Loan, `CC…` = Card (the dashboard field is the fallback).
3. A test file (file number contains the word `test`) is never reported or billed.
4. Activity-log times are UTC and are converted to Dhaka time; trip and file times are used as the dashboard shows them.
5. Paging can drop rows when the sort value ties, so a list is read a second time with another sort if the count is short of the server's total.

---

## 2. Bill rows — how the trips of a file become rows

Reference: `billing.build_rows`, `billing._pg_groups`, `billing.slab_for`, `billing.trip_billable`.

A file is cut into rows once; the tracker, the file history and the monthly bill all use the same rows.

1. **Package.** The trips created on the day the file was created (its Start Date), in creation order, are ONE row of kind `Package`, up to **5** trips. Any trip type counts.
2. **6th, 7th … same-day trip** = its own row, kind `Single`, labelled "Created - Extra Trip 1, 2 …".
3. A Canceled or Withdrawn trip never takes one of the five places while the file has a living trip (a batch created twice by mistake must not push the real trips out of the package).
4. **Every trip created on a later day** is its own row: kind `ReCpv` when the trip is in the Re-CPV tracker (or flagged `is_for_recpv`), otherwise kind `Extra`.
5. **Guarantor visits created together**: a guarantor's house and office trips created on the same day are ONE row.
6. **A document created with the package is its own row** (v6.1, the manual bill of September 2026: 50 of 56 such files): every living applicant document trip (LOI, salary certificate, pay slip, rental, car quotation …) created on the package day is taken out of the package and billed on its own row, In or Out by the document's own address (`BillRow.split = True`). v6.0 did this only for an In document of an Out package. A Canceled / Withdrawn document stays with the package (not billed); a file of documents only stays one package. The package row's Report Summary still reads these documents, and the daily tracker folds them into the package line (`fold_complete`), so the tracker keeps one line per file.
7. **Slab of a non-package row** (`slab_for`):

   | Trip | Slab |
   |---|---|
   | guarantor house + office together, or a NEW guarantor house / office | `PG Verification(House+Office/Business+Signature)` |
   | guarantor house / office that is a Re-CPV of an earlier visit | `Single House` / `Single Office` |
   | applicant / co-applicant house, office | `Single House`, `Single Office` |
   | bank | `BS` |
   | document, signature, rental, car quotation, chamber, tuition … | `Single Document(Salary Certificate/Pay Slip/LOI/Signature) Verification` |

8. **What is billable** (`trip_billable`): everything that was created, including an **Inactive** trip. Not billable: a Withdrawn trip, and a Canceled trip that nobody ever started (`start_time` empty). A Canceled trip that had been started is billable (the bank stopped the file after work began).
9. Re-CPV never changes the number of trips; it only labels a trip.
10. Each row has its own Receive Date, Submission, TAT and Extra TAT.

---

## 3. In station / Out station

Reference: `geo.trip_area`, `geo.classify_point`, `geo.classify_text`, `billing.row_area`.

1. **In** = inside Dhaka City Corporation (North + South) or Chattogram City Corporation. Everything else = **Out**.
2. One trip: the address coordinates decide; if they are missing, the end-of-visit coordinates; if both are missing, the address text.
3. The city outlines are approximate, so the answer is marked "not sure" when the point is close to the border, when address and visit coordinates disagree, or when the address text names a place on the other side. An address that names a place outside the two cities (Keraniganj, Gazipur, Savar …) wins over a pin that merely falls inside the outline.
4. **City-edge pins** (v6.1): a pin that is In but "not sure" (near the outline, or address and visit points disagree) is Out when the last two parts of the map address (`exact_address`, the administrative area the map gives, e.g. "Tongi Paurashava, Gazipur Sadar", "Washpur, Keraniganj") name a place outside the two cities. Only that tail is read, so a road name such as "Hathazari Road" never decides.
5. A **package is Out if any of its trips is Out**; a single row is judged on its own trip.
6. Every "not sure" row is listed for a human to look at (tracker: flagged cell; bill: Check sheet). The dashboard's own Station field is not used for billing; a disagreement with it is shown as a note.

---

## 4. Receive date, submission and status of a row

Reference: `billing._assign_submission`, `billing.assign_sub_days`, `billing.file_state`, `activity.parse_logs`.

1. **Receive Date-Time**: Package and same-day Single = the file's Start Date; Re-CPV / Extra = the trip's `created_at`.
2. **Before / After 3 PM** is read from the receive time (cut-off 15:00).
3. **Submission** comes from the activity log, never from the file's `end_date`:
   - Package / Single: the first "Submitted" event of the file.
   - Re-CPV / Extra: the trip must be Finished; then the first "Submitted" event at or after the time the trip was finished.
   - A file that is Partially Submitted and has no follow-up rows is "Partially Submitted", not Submitted.
4. A submission made on a day off (Friday, Saturday, holiday) is reported, and its TAT counted, on the next working day.
5. If the activity log cannot be read the row stays Incomplete and is flagged, it never disappears.
6. **File state** for the Incomplete list is decided per file: closed (Canceled / Withdrawn), submitted (Submitted and nothing added since), partial, or pending (not submitted, or re-opened by a live trip created after the last Submitted). Canceled / Inactive / Withdrawn trips never keep a file pending.

---

## 5. SLA, TAT and Extra TAT

Reference: `billing.sla_start_for`, `billing.compute_tat`, `holidays.py`.

1. **SLA** in working days: **In = 2, Out = 4**.
2. **SLA Start Date** = the Receive Date, unless something restarts the clock. The latest of these wins:
   - **A new trip of the file** (Re-CPV, extra document, any single trip): the SLA restarts on the day the trip is created, with the full 2 / 4 days. A Canceled / Inactive / Withdrawn trip does not restart anything.
   - **An appointment** (new in Version 6): take the latest-created appointment of the file; the report is due on the **next working day after its scheduled date, by 5:59 PM**, for In and Out alike. In numbers: SLA Start = the scheduled date, SLA = 1 working day, and a submission after 17:59:59 on the due day counts one more day.
3. The whole file counts (all its rows), but only what existed when the row was submitted (or, for a pending row, at the end of the report day).
4. **TAT** = working days from the day after the SLA Start Date up to the submission day (or the report day for a pending row).
5. **Extra TAT** = max(0, TAT − SLA), plus the one day of rule 2 when it applies.
6. The Excel cells carry the same calculation as formulas, so the sheet can be checked by hand.

---

## 6. Daily submission tracker

Reference: `billing.select_rows`, `billing.tracker_window`, `billing.fold_complete`, `billing.apply_as_of`, `prime_excel.py`, `prime_pdf.py`.

1. **Days covered**: the report date, plus the days off just before it (Sunday's tracker covers Friday, Saturday and Sunday).
2. **Two mails a day** (v10 times): Phase 1 at **12:00 PM** = submitted before 12 PM; Phase 2 at **6:15 PM** = the whole day, or only what was submitted after 12 PM (`billing.CUTOFF_HOUR = 12`; the internal keys stay `3pm` / `7pm`).
3. **Complete sheet** = rows submitted inside those days, whenever they were received. One row per file and submission day: a Re-CPV / Extra row submitted together with the package is folded into the package row, and the Bill Slab cell carries the whole billing history of the file.
4. **Incomplete sheet**, decided per file as the dashboard does: files not Submitted at the time of the report whose status is **Hold, Finished-but-not-Submitted, or Partially Submitted**. A running file (Created / On Going) is not listed. One row per file.
5. A row submitted after the moment of the report is shown as it was then (Incomplete, "submitted later"), so an old report can be reproduced.
6. The Complete sheet is compared with the dashboard's own Submitted list for the same dates, file by file, and every difference is listed with its reason.
7. **Columns (Version 6), in this order:**

   | # | Column | # | Column |
   |---|---|---|---|
   | 1 | SL | 11 | Re-CPV / Extra Trip (ID) |
   | 2 | File No | 12 | Bill Slab |
   | 3 | File Type (Card / Loan) | 13 | Area (In / Out) |
   | 4 | Applicant Name | 14 | SLA Start / Restart Date |
   | 5 | Concerns Name | 15 | SLA |
   | 6 | Receive Date-Time | 16 | TAT |
   | 7 | Submission Date-Time | 17 | Extra TAT |
   | 8 | Report Status | 18 | Appointment History |
   | 9 | Report Summary (Done / Due) | 19 | Last Update Details |
   | 10 | Last Update Date | 20 | Before / After 12 PM |

   The Incomplete sheet has a 21st column, Pending Reason. Date cells are real dates; v10: every header cell has a filter button. In the PDF, File Type sits under File No and the two Last Update columns are one, to save width.

---

## 7. Report Summary — Done / Due

Reference: `summary.analyze`, `summary._notes_for`, `summary.NOTE_RULES`, `summary.apply_later`. This is rule-based text reading, not AI.

**Principles**

1. Done / Due is written **per trip, from that trip's own remarks**. Remarks = what the verifier found. The back-office Comment (the instruction) is used only to tell what kind of document a `DOCUMENT` trip is (LOI, Payslip, PEC, Chamber, Tuition, Rental …).
2. The row's summary is the list of its trips' items: `Done - App House, Office, Sign, LOI, BS1 …` / `Due - LOI (Signatory not available) …`. "0" means nothing.
3. **The word "not" alone is not negative.** A problem is recognised by a rule (a pattern with a short standard note). "Information ok" protects a remark from the general fallback, but not from the specific rules below.
4. Items: the trip itself (App / Co-App / PG + House / Office, BS, the document's name), plus **Sign** and **LOI** when the remark mentions them. Bank statements are numbered BS1, BS2 … in creation order.
5. When nothing fits, the item is still shown and the cell is flagged **Check** (yellow) with the reason. Nothing is passed as Done silently, and nothing is hidden.

**By trip status**

| Status | Rule |
|---|---|
| Finished | read the remarks; no problem → Done; problem → listed in Done with its note and repeated in Due |
| Finished, no remarks at all | flagged Check |
| Created / Allocated | Due "Not visited yet" |
| Started | Due "Visit in progress" |
| Hold | Due with the reason from the latest appointment, see below |
| Inactive, Canceled | Due only when the verifier wrote a problem in the remarks (a rule matches, or the text is plainly negative). Empty remarks, or remarks that read finished ("Bank statement verified", "LOI verification complete"), are not Due |
| Withdrawn | ignored |

**Appointments**

- An appointment whose scheduled day is still to come (today counts): the item is Due with **"Appointment DD-MM-YYYY hh:mm AM/PM"** and nothing negative.
- For a trip that is still open, the reason of the newest appointment is read together with the remarks; older reasons are replaced by the newest.
- Negative wording is used only when the appointment day has passed and the remark says the person did not come / was not available.

**Problem notes** (the standard short texts the rules produce)

- House / office: Does not live at given address · Does not sit in given office · Moved to another address · Not found at given address · No longer operates at given address · No longer employed at given office · Office closed · Not available · Not known to neighbours/guard · Phone switch off · Disagree to verify · Out of CPV coverage area · Information not ok
- LOI / documents: LOI not verified · Signatory not available · Head office disagree · Disagree to verify · Need to verify by email · Need forwarding letter · Submitted for verification · Will be signed from head office · Can be verified from branch · HR verifies salary certificate only
- Bank: Statement not verified · Insufficient fund · Signature mismatch · Signature missing · Seal missing · Account no wrong · Call not received · No transactions in account
- General: Stop by bank · Could not verify · Will try again later
- Information only (never Due): New address found & verified · Signed from branch · Signed from head office · System generated - no sign required

**Special cases learned from the manual tracker (Version 6)**

1. "LOI not signed in front of me" followed by the signatory's name = the LOI **is** signed.
2. A system-generated LOI ("no sign required") is Done, with the note.
3. "Signature could not be collected / obtained", "can not take applicant sign", "Applicant wasn't present at office" with no signature mentioned → **Sign** Due, even when the remark starts with "Information ok".
4. A problem written after a **PEC** heading in an office remark belongs to the PEC, not to the LOI. The same for a **Chamber** problem ("the applicant no longer operates a chamber at the given address").
5. A house / office remark with nothing positive in it ("The guarantor is away for training …") is Due and flagged Check.
6. "Information not ok" followed by unrelated positive sentences gives the note "Information not ok", not those sentences.
7. Curly apostrophes and common misspellings ("varified", "infront", "sing" for sign) are read as the normal words.
8. **Later trips close earlier items**: a finished later trip of the same person and type removes the earlier Due of that item; a newer pending trip re-opens it.

Measured on 4,421 real trips and 894 tracker rows (Aug–Nov 2026): of 341 Due items written by hand, 267 are also Due by these rules, 10 sit on their own Re-CPV / Extra row, 40 can no longer be checked because the remark was replaced when the trip was finished later, and 24 are explained one by one (mostly the tracker being a snapshot from before the trip was finished).

---

## 8. Monthly bill

Reference: `monthly_bill.build_month_bill`, `monthly_bill.Bill`, `bill_out.py`. Command line: `--bill YYYY-MM`.

1. **What is billed**: every bill row whose Receive Date (= the day it was **created** on the dashboard) is inside the month: new files (package), Re-CPV trips, extra trips. Whether it has been submitted does not matter; a pending row has an empty submission date.
2. **Which files are read**: files received in the month; files whose status changed since the month began; files with a Re-CPV created in the month; and older files (one year back) that hold a trip created in the month.
3. **Card and Loan are separate bills**, each as Excel and PDF.
4. **Left out, and listed with the reason**: test files; Withdrawn trips; Canceled trips that were never started; and the Canceled copy of a file that was created again under the same file number (one file number = one package).
5. **Rates (BDT)**:

   | | In station | Out station |
   |---|---|---|
   | Card package | 450 | 600 |
   | Loan package | 600 | 700 |
   | Re-CPV / extra: single document | 140 | 170 |
   | Re-CPV / extra: house / office / bank statement | 140 | 240 |
   | Re-CPV / extra: PG verification | 140 | 230 |

   In station all Re-CPV / extra rows are one invoice line at 140.
6. **Totals**: Subtotal − penalty deduction = amount after penalty; **VAT 5 %** on that; Grand Total.
7. **Reference**: `Barikoi/PrimeBank/CPVBill-<Month>/<Year>/<MM>`; the bill date is the day the bill is made.
8. **Layout** (same as the invoice sent to the bank): page 1 = summary (lines by station and type, penalty table, VAT, grand total, amount in words, payment details); then one list per line (SL, Ref. No., Applicant's Name, Rec. Date, Sub. Date, TAT, Amount, Category), 25 rows a page, penalised rows highlighted.

---

## 9. Penalty

Reference: `monthly_bill.penalty_pct`, `build_month_bill`, the "Penalty" sheet in `bill_out.py`.

1. **Rate**: Extra TAT 1 day = 20 %, 2 days = 30 %, 3 days or more = 50 % of that row's amount. In and Out alike.
2. Every row with an Extra TAT is **listed** on the Penalty sheet with a Yes / No "Apply" cell and the reason for its starting value:
   - **Yes**: a submitted Package or Bank Statement row (what the manual bill has always charged).
   - **No**: an extra document / Re-CPV row, a split LOI row, and a row that is not submitted yet.
3. The user may change any Yes / No (for example when the bank caused the delay). The workbook's totals follow by formula, and the PDF can be made again from the edited workbook.

---

## 10. Check sheet — nothing may be missing

Reference: `build_month_bill` (stats), the "Check" sheet in `bill_out.py`.

1. Rows created in the month = rows on the Card bill + rows on the Loan bill + rows left out. The sheet shows the three numbers and says OK or not.
2. Trips created in the month on the dashboard = trips inside the rows of the month.
3. Every left-out row is listed with its reason.
4. Rows that were billed but deserve a look are listed: In / Out not sure, and Canceled-but-started trips.

---

## 11. File history

Reference: `file_history.py`, `history_excel.py`.

Input: an Excel with File No and Applicant Name. Each file is looked up by number; the output has a Summary (with a name check against the applicant and the guarantors), Timeline, Submission History, Trips with full remarks, Appointments, Re-CPV & Extra, Concerns, and a Not Found sheet.

---

## 12. Version 7 against the manual September 2026 bill

September 2026 was rebuilt from the live dashboard (read-only) with this code. Version 6 reproduced the software bill that was
sent row for row (844 of 844 rows), so the comparison below is the real engine, not an estimate.

**Completeness.** 411 files were created in September (Card 185, Loan 226; test file and re-created Canceled copies left out) and
76 older files got a new trip in September: 487 files. The bill has exactly these 487 files - none missing. Trips created in
October / November on September files go to those months' bills (bill by create date).

| | Version 6.0 | Version 7.0 | Manual |
|---|---|---|---|
| Rows | 844 | 863 | 849 |
| Same file + row type (Package / Single / PG) | 789 (92.9 %) | 800 (94.2 %) | - |
| Same file + row type + In / Out | 721 (84.9 %) | 734 (86.5 %) | - |
| ... with the manual's 37 In / Out mistakes corrected | - | 771 (90.8 %) | - |
| Amount before penalty (BDT) | 316,210 | 319,170 (Card 115,140 · Loan 204,030) | 321,710 |

- **In / Out** - the 38 packages where the tool and the manual disagreed were checked visit by visit against the map: the tool was
  right in 37 (23 inside Chattogram City Corporation, 8 inside Dhaka City Corporation, 2 in Faridpur / Khulna, 4 with a house
  outside the city), the manual in 1 (an office in Tongi, Gazipur) - fixed in 7.0 (rule 3.4).
- **Same-day documents** - the manual bills every document created with the package on its own row (50 of 56 files); 7.0 does the
  same (rule 2.6).
- **Receive date** - the manual writes the day the bank's request arrived, often the day before the trip was created on the
  dashboard; the dashboard has no such date, so only 551 of 849 rows (64.9 %) have the same date. At month ends this moves a few
  trips between months.
- **Penalty** - the tool charges every late submitted package (20 / 30 / 50 %): about 9,437 BDT in September against 3,510 on the
  manual bill (policy confirmed by the user, not a defect).

## 13. Known limits

1. In / Out depends on approximate city outlines; border cases are flagged, not guessed silently.
2. Done / Due is rule-based. New wording is flagged Check and should be added as a rule.
3. Remarks that are replaced on the dashboard when a trip is finished later cannot be reproduced afterwards; a tracker made today shows today's state.
4. The appointment rule uses the latest-created appointment of the file.

---

## 14. Version 10 (15 November 2026)

### 14.1 Every report on A4 landscape
Reference: `prime_pdf.build_prime_pdf`, `pagesetup.a4`, `prime_excel.COLS`.

1. **PDF** ("Sample 1 – A4 Classic", chosen by the user): A4 landscape, **all 16 / 17 columns**, Carlito font (OFL, Calibri-metric,
   bundled in `assets/fonts`), 7.2 pt; header band with the logo; header row repeated on every page; a row never splits.
   A long cell is cut to a few lines (6, Report Summary 8) and ends with "+N more lines (full text in the Excel)".
2. **Excel**: every workbook the program writes is A4 landscape, all columns on the page width, narrow margins, "Page x of y"
   (`pagesetup.a4`, called right before each save). The invoice sheet of the bill stays an A4 portrait letter. The tracker's
   column widths are the A4 Classic widths and **every column has a filter button** (v7 showed only four).

### 14.2 BS Tracker (bank statements)
Reference: `bs_rules.py`, `bs_tracker.py`, `pages.BSPage`, `pages.ReceivePage`.

1. **Rows**: one row per BANK trip; a file with two BS has two rows, next to each other (sorted by the file's first BS, then file,
   then Trip ID). The monthly Excel takes the trips **created** in that month. Columns: Created Date-Time, Trip ID, File No,
   Applicant, Bank (as written), Bank, BS Type, Verifier, Verifier Phone, Trip Status, Exact Remarks, BS Outcome, Office Received,
   Courier, Courier Slip (picture, about 100 px), Bank Received, Now. Filter on every column, A4 landscape.
2. **Bank and Online / Offline** (`bs_rules.match_bank`): the user's list (28 online, 25 offline incl. Sammilito Islami Bank)
   with SWIFT codes and spellings. The bank written on the trip decides; if empty, the remarks. Standard Bank = Standard Islami
   Bank PLC (renamed 10 Feb 2026) = offline; Standard Chartered = online. A short form that can mean several banks (PBL, JBL,
   MBL, SBL, UBL, BCBL) is decided by another word in the text (e.g. "Pubali branch"); still unclear = **offline** (never missed).
   No manual checking.
3. **Collected or not, from the exact remarks** (`bs_rules.bs_outcome`, first match wins): disagree / refused → not collected
   (applicant disagreed); not possible / closed / transferred / returned / abroad → not collected (not possible); statement not
   verified / mismatch → not collected (with "Insufficient balance" when written); hard copy provided / statement provided →
   collected (hard copy); scan / soft copy / e-mail → collected (soft copy); only "verified" → verified, copy not mentioned;
   no remark on an open trip → pending; anything else → "Check remark". Learnt from the 283 BS trips of 1 Oct – 15 Nov 2026:
   240 of the 242 finished trips are recognised.
4. **Office receive**: a short form in the program (Trip ID or File No → bank, verifier and time fill in by themselves; pages,
   received by, note). A filled Excel form can also be uploaded (`write_receive_template` / `read_receive_upload`). At day end
   the "আজ রিসিভ হয়েছে" sheet (A4 portrait, signature lines) is printed (`write_receive_sheet`).
5. **Courier**: courier name, number, status (Booked / In transit / Delivered / Returned) and the slip picture, per BS.
6. **Bank received**: the user uploads the client's signed list (Excel, CSV, PDF with text, or a photo – read with Windows' own
   OCR). A BS counts as received when its Trip ID, its File No (or the File No's digits) or the applicant's full name is in the
   list; when a file has two BS and only the name is found, the bank's name must be on the same line (`match_signed_list`).
   The program then lists the BS that were sent but are not in the list.
7. **Pending BS** (`pending_bs`), no cap: not yet collected on an open trip, or collected but not yet in the office / courier.
   Checked at **12:00 PM and 6:15 PM** (the latest missed check runs when the program opens).

### 14.3 Verifier reminders on WhatsApp
Reference: `reminders.py`, `helper_server.py`, `assets/whatsapp_helper/`, `pages.RemindersPage`.

1. **Who**: every verifier with an open trip (Created / Allocated / Started / Hold) in an ON GOING or HOLD file, both clients,
   plus verifiers who still have to hand in a collected BS. No cap.
2. **When**: 10:00 AM – today's appointments only; 1:00 PM and 4:00 PM – everyone. A trip whose appointment is on a later day is
   skipped until that day; with an appointment today it is reminded until finished. Office days only, until 6:15 PM; if the PC
   was off, the latest missed round is prepared when the program opens.
3. **Order**: SLA passed → SLA ends today → appointment today → the rest (`Reminder.priority`).
4. **Message**: short Bangla text with the file numbers, and one of four voice clips (SLA passed / appointment today / hand in
   BS / general). Clips are made once with a free offline voice (Coqui TTS `bn/custom/vits-male`, MIT; Kolkata-style accent,
   accepted by the user) by `.github/workflows/voices.yml` and shipped in `assets/voices`.
5. **Sending (risk-free, free)**: nothing is sent by the program. The helper (a Chrome extension added once with "Load unpacked")
   opens each chat with WhatsApp's own click-to-chat link (`web.whatsapp.com/send?phone=…&text=…`), attaches the clip, and waits
   until the user presses Send; then 8 seconds' break and the next verifier. WhatsApp keeps text drafts but not attachments, so the
   voice is attached when the chat opens. The helper never presses Send (a test checks there is no `.click()` in it).
6. **Replies**: the helper reads new messages of the verifiers' chats (chat list preview and the open chat) and gives them to the
   program through `helper_server` (127.0.0.1 only; a request carrying a web page's Origin is refused). `parse_reply`: codes
   1 / 2 / 3 (Bangla or English digits), then common words (Banglish / Bangla / English) → going / done / problem (reason kept) /
   other. A number WhatsApp rejects is marked red ("not on WhatsApp").
7. **Day-end summary** inside the program only: per verifier – rounds, sent, last reply, problem reason, files.
8. **Phone numbers**: `/api/v2/verifiers` (GET, added to the allow-list). Only id, name and phone are kept
   (`client.verifier_phones`); the reply also carries other fields, among them an access token, which are dropped at once
   (a test checks it). **The dashboard team should remove `admin_access_token` from this response.** Numbers can be changed
   or added on the Verifiers page (saved locally).

### 14.4 The window
Reference: `shell.py`, `pages.py`, `gui.ReportsPage`, `i18n.py`.

1. Opening screen every time: **language (বাংলা / English, the last choice pre-selected)** and the sign-in. The password stays
   in memory while the program is open (the 10 AM … 6:15 PM jobs need it); it is never written to disk.
2. White side bar: Today, Daily Tracker, Monthly Bill, BS Tracker, Office receive, Reminders, Verifiers, File History, Settings.
   The report page is the v7 page with the same rules. Excel / PDF stay in English in both languages.

---

## Version 7-এ নতুন

- **সেপ্টেম্বর ২০২৬ লাইভ ড্যাশবোর্ডে পুরো যাচাই:** ৪১১টি নতুন ফাইল + ৭৬টি পুরনো ফাইলের সেপ্টেম্বরের ট্রিপ = ৪৮৭টি ফাইল — বিলে ঠিক এই ৪৮৭টিই আছে, **কোনো ফাইল বাদ নেই**। Version 6 পাঠানো বিলটি সারি-সারি হুবহু (৮৪৪/৮৪৪) আবার তৈরি করেছে।
- **প্যাকেজের সাথে তৈরি document আলাদা সারি:** একই দিনে তৈরি LOI / salary certificate / rental / quotation — সবসময় নিজের সারিতে বিল হয়, নিজের ঠিকানা অনুযায়ী In বা Out (ম্যানুয়াল বিল ৫৬টির ৫০টিতে এভাবেই করেছে)। আগে শুধু “Out package + In LOI” হলে হতো। Canceled document প্যাকেজেই থাকে (বিল হয় না)। দৈনিক ট্র্যাকারে আগের মতো এক ফাইল = এক লাইন, LOI প্যাকেজের Done/Due-তেই থাকে।
- **সিটির সীমানার পিন:** সীমানার কাছের In পিনের ম্যাপ-ঠিকানার শেষ অংশে শহরের বাইরের এলাকা (যেমন “Tongi Paurashava, Gazipur Sadar”, “Keraniganj”) থাকলে Out। রাস্তার নাম (যেমন “Hathazari Road”) ধরা হয় না।
- **ম্যানুয়াল বিলের সাথে মিল (সেপ্টেম্বর):** ফাইল + সারির ধরন ৯৪.২%; In/Out-সহ ৮৬.৫% (ম্যানুয়ালের ৩৭টি In/Out ভুল ঠিক ধরলে ৯০.৮%); পেনাল্টির আগে টাকা ৩,১৯,১৭০ বনাম ৩,২১,৭১০ (৯৯.২%)। ৩৮টি বিতর্কিত প্যাকেজের ৩৭টিতে সফটওয়্যার ঠিক (City Corporation নিয়ম অনুযায়ী), ১টি (Tongi) ঠিক করা হয়েছে।
- **মোট ১৭৯টি স্বয়ংক্রিয় টেস্ট।**

## Version 6-এ নতুন

- **মাসিক বিল (নতুন “মাসিক বিল” অংশ):** মাস বেছে নিলে ওই মাসের ১ তারিখ থেকে শেষ তারিখ পর্যন্ত ড্যাশবোর্ডে যা **তৈরি (create)** হয়েছে — নতুন ফাইল (Package), Re-CPV ও Extra ট্রিপ — সবকিছুর বিল হয়; Submit হয়েছে কি না দেখা হয় না। **Card ও Loan আলাদা**, প্রতিটির **Excel + PDF**, ব্যাংকে দেওয়া Invoice-এর একই ফরম্যাটে (সারাংশ পাতা + ক্যাটাগরি অনুযায়ী ফাইলের তালিকা, VAT 5%, কথায় টাকা)। কমান্ড লাইনে: `--bill 2026-09`।
  - **Rate:** Card Package In 450 / Out 600; Loan Package In 600 / Out 700; In station-এর সব Re-CPV / Extra 140; Out: single document 170, house / office / bank 240, PG 230।
  - **Penalty:** Extra TAT 1 দিন = 20%, 2 দিন = 30%, 3 বা বেশি = 50%। **Penalty** শিটে Extra TAT থাকা প্রতিটি সারি থাকে; দেরিতে Submit হওয়া **Package ও Bank Statement**-এ Apply = Yes, বাকি সারিতে (আলাদা LOI, extra document, Re-CPV, এখনো Submit হয়নি) Apply = No — কারণসহ। Yes / No বদলালে পুরো Excel-এর হিসাব সঙ্গে সঙ্গে বদলায়; **“সম্পাদিত Excel থেকে PDF”** বোতামে সেই Excel থেকেই PDF হয়।
  - **Check শিট:** মাসে তৈরি সারি = Card + Loan + বাদ পড়া; বাদ পড়া প্রতিটি সারি কারণসহ (Canceled ট্রিপ যা কেউ শুরু করেনি, Withdrawn, test ফাইল)। কোনো ফাইল বা ট্রিপ চুপচাপ বাদ যায় না।
- **বিলের সারি ম্যানুয়াল বিলের নিয়মে:** Out station-এর Package-এর LOI / document Dhaka বা Chattogram city-তে হলে আলাদা সারি (In rate); Guarantor-এর House + Office একসাথে = PG, Re-CPV-র Guarantor House / Office = Single House / Office; **Canceled** ট্রিপ ভেরিফায়ার শুরু করে থাকলে বিল হয়, না করলে হয় না; **Inactive** ট্রিপের বিল হয়।
- **Appointment-এর SLA:** Appointment-এর *scheduled date*-এর **পরের কার্যদিবস বিকেল ৫:৫৯** পর্যন্ত (In ও Out একই); একাধিক Appointment থাকলে শেষটি।
- **দৈনিক ট্র্যাকার — নতুন ২০ কলাম:** SL, File No, File Type, Applicant Name, Concerns Name, Receive Date-Time, Submission Date-Time, Report Status, Report Summary (Done / Due), Last Update Date, Re-CPV / Extra Trip, Bill Slab, Area, SLA Start / Restart Date, SLA, TAT, Extra TAT, Appointment History, Last Update Details, Before / After 3 PM। তারিখের ঘরগুলো আসল তারিখ — Excel-এ filter চলে। (Incomplete শিটে শেষে Pending Reason।)
- **Done / Due — ম্যানুয়াল ট্র্যাকারের সঙ্গে মিলিয়ে শেখানো:**
  - সামনের তারিখে Appointment থাকলে শুধু “Appointment on …” — নেতিবাচক কিছু নয়।
  - **Inactive / Canceled** ট্রিপে ভেরিফায়ার সমস্যা লিখে থাকলে Due থাকে (হারিয়ে যায় না); প্রতিটি Bank Statement আলাদা (BS1, BS2 …)।
  - “signature could not be collected”, “can not take applicant sign”, “Applicant wasn't present at office” → Sign Due।
  - Office-এর লেখার ভেতরে **PEC** বা **Chamber**-এর সমস্যা → আলাদা PEC / Chamber Due (LOI নয়)।
  - “LOI not signed in front of me” + signatory-র নাম = LOI signed; system generated LOI (“no sign required”) = Due নয়।
  - লেখায় ভালো কিছুই না থাকলে বা নিয়মে না মিললে **Due + “Check”** (হলুদ) — চুপচাপ Done হয় না।
- ১৭৭টি স্বয়ংক্রিয় টেস্ট + আসল অ্যাপ-উইন্ডোর GUI smoke test (Windows, macOS, Linux)।

## Version 5 থেকে চলছে


- **Done / Due শুধু ভেরিফায়ারের Remarks থেকে** — ব্যাক-অফিসের Comment (নির্দেশ) থেকে নয়। Payslip-বাক্য (“HR will verify only salary certificate”) এখন ঠিকভাবে পড়া হয়, ভুল “Head office disagree” আসে না।
- **File History ক্র্যাশ ঠিক:** ফাঁকা শিট থাকলে (যেমন সব নম্বর পাওয়া গেলে) `'MergedCell' object is not iterable` দিয়ে থেমে যেত — আর যায় না।
- **File History ইনপুট = File No + Applicant Name:** নমুনা Excel (অ্যাপের বোতামে বা `templates/File_History_Format.xlsx`); ফাইল নম্বর দিয়ে খোঁজা হয়, নামের জন্য Summary শিটে **Name Check** (Matches / Matches Guarantor / Different)।
- **আগের সব অপশন অপরিবর্তিত** (ট্র্যাকার, তারিখ-সীমা, Re-CPV, সাধারণ এক্সেল, ইমেইল, ছুটি, SLA ও Incomplete নিয়ম)।
- ১৬২টি স্বয়ংক্রিয় টেস্ট + আসল অ্যাপ-উইন্ডোর GUI smoke test (File History সহ; Windows, macOS, Linux)।

## Version 4 থেকে চলছে (Appointment-এর SLA নিয়ম Version 6-এ বদলেছে — উপরে দেখুন)

- **SLA Restart:** Appointment-এর *scheduled date* থেকে এবং **যেকোনো নতুন ট্রিপ** তৈরি হলে সঙ্গে সঙ্গে; In (Dhaka ও Chattogram City Corporation) = ২ কার্যদিবস, Out = ৪ কার্যদিবস। নতুন কলাম **“SLA Start / Restart Date”** (Excel ও PDF)।
- **Incomplete** = শুধু Hold, Finished কিন্তু Submit হয়নি ও Partially Submitted।

## সব ফিচার — প্রথম সংস্করণ থেকে Version 7 পর্যন্ত (বিস্তারিত; Version 10.0.1 উপরে)

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

### Version 7.0.0 (১১ নভেম্বর) — সেপ্টেম্বরের পূর্ণ যাচাই, প্যাকেজের document আলাদা সারি, সীমানার পিন

- প্যাকেজের সাথে একই দিনে তৈরি প্রতিটি document নিজের সারিতে বিল (In বা Out নিজের ঠিকানায়), ম্যানুয়াল বিলের মতো; ট্র্যাকারে এক ফাইল = এক লাইন থাকে।
- সীমানার কাছের পিন ম্যাপ-ঠিকানার প্রশাসনিক এলাকা (Tongi / Gazipur, Keraniganj) দেখে Out।
- সেপ্টেম্বর ২০২৬: ৪৮৭টি ফাইলের সব বিলে; ম্যানুয়ালের সাথে টাকায় ৯৯.২%, সারির ধরনে ৯৪.২% মিল; ৩৮টি In/Out বিরোধের ৩৭টিতে সফটওয়্যার ঠিক।

---

### Version 6.0.0 (১০ নভেম্বর) — মাসিক বিল, Appointment-এর নতুন SLA, ২০ কলামের ট্র্যাকার, Done / Due প্রশিক্ষণ

- **মাসিক বিল (নতুন “মাসিক বিল” অংশ):** মাস বেছে নিলে ওই মাসের ১ তারিখ থেকে শেষ তারিখ পর্যন্ত ড্যাশবোর্ডে যা **তৈরি (create)** হয়েছে — নতুন ফাইল (Package), Re-CPV ও Extra ট্রিপ — সবকিছুর বিল হয়; Submit হয়েছে কি না দেখা হয় না। **Card ও Loan আলাদা**, প্রতিটির **Excel + PDF**, ব্যাংকে দেওয়া Invoice-এর একই ফরম্যাটে (সারাংশ পাতা + ক্যাটাগরি অনুযায়ী ফাইলের তালিকা, VAT 5%, কথায় টাকা)। কমান্ড লাইনে: `--bill 2026-09`।
  - **Rate:** Card Package In 450 / Out 600; Loan Package In 600 / Out 700; In station-এর সব Re-CPV / Extra 140; Out: single document 170, house / office / bank 240, PG 230।
  - **Penalty:** Extra TAT 1 দিন = 20%, 2 দিন = 30%, 3 বা বেশি = 50%। **Penalty** শিটে Extra TAT থাকা প্রতিটি সারি থাকে; দেরিতে Submit হওয়া **Package ও Bank Statement**-এ Apply = Yes, বাকি সারিতে (আলাদা LOI, extra document, Re-CPV, এখনো Submit হয়নি) Apply = No — কারণসহ। Yes / No বদলালে পুরো Excel-এর হিসাব সঙ্গে সঙ্গে বদলায়; **“সম্পাদিত Excel থেকে PDF”** বোতামে সেই Excel থেকেই PDF হয়।
  - **Check শিট:** মাসে তৈরি সারি = Card + Loan + বাদ পড়া; বাদ পড়া প্রতিটি সারি কারণসহ (Canceled ট্রিপ যা কেউ শুরু করেনি, Withdrawn, test ফাইল)। কোনো ফাইল বা ট্রিপ চুপচাপ বাদ যায় না।
- **বিলের সারি ম্যানুয়াল বিলের নিয়মে:** Out station-এর Package-এর LOI / document Dhaka বা Chattogram city-তে হলে আলাদা সারি (In rate); Guarantor-এর House + Office একসাথে = PG, Re-CPV-র Guarantor House / Office = Single House / Office; **Canceled** ট্রিপ ভেরিফায়ার শুরু করে থাকলে বিল হয়, না করলে হয় না; **Inactive** ট্রিপের বিল হয়।
- **Appointment-এর SLA:** Appointment-এর *scheduled date*-এর **পরের কার্যদিবস বিকেল ৫:৫৯** পর্যন্ত (In ও Out একই); একাধিক Appointment থাকলে শেষটি।
- **দৈনিক ট্র্যাকার — নতুন ২০ কলাম:** SL, File No, File Type, Applicant Name, Concerns Name, Receive Date-Time, Submission Date-Time, Report Status, Report Summary (Done / Due), Last Update Date, Re-CPV / Extra Trip, Bill Slab, Area, SLA Start / Restart Date, SLA, TAT, Extra TAT, Appointment History, Last Update Details, Before / After 3 PM। তারিখের ঘরগুলো আসল তারিখ — Excel-এ filter চলে। (Incomplete শিটে শেষে Pending Reason।)
- **Done / Due — ম্যানুয়াল ট্র্যাকারের সঙ্গে মিলিয়ে শেখানো:**
  - সামনের তারিখে Appointment থাকলে শুধু “Appointment on …” — নেতিবাচক কিছু নয়।
  - **Inactive / Canceled** ট্রিপে ভেরিফায়ার সমস্যা লিখে থাকলে Due থাকে (হারিয়ে যায় না); প্রতিটি Bank Statement আলাদা (BS1, BS2 …)।
  - “signature could not be collected”, “can not take applicant sign”, “Applicant wasn't present at office” → Sign Due।
  - Office-এর লেখার ভেতরে **PEC** বা **Chamber**-এর সমস্যা → আলাদা PEC / Chamber Due (LOI নয়)।
  - “LOI not signed in front of me” + signatory-র নাম = LOI signed; system generated LOI (“no sign required”) = Due নয়।
  - লেখায় ভালো কিছুই না থাকলে বা নিয়মে না মিললে **Due + “Check”** (হলুদ) — চুপচাপ Done হয় না।
- ১৭৭টি স্বয়ংক্রিয় টেস্ট + আসল অ্যাপ-উইন্ডোর GUI smoke test (Windows, macOS, Linux)।

### Version 5.0.0 (৮ নভেম্বর) — Done / Due শুধু Remarks থেকে, File History-র সংশোধন ও File No + Applicant Name Excel

- **Done / Due (Report Summary) এখন শুধু ভেরিফায়ারের Remarks থেকে লেখা হয়, ব্যাক-অফিসের Comment থেকে নয়।** *Comment* = ফাইল তৈরির সময় ব্যাক-অফিস ভেরিফায়ারকে যে **নির্দেশ** দেয় (যেমন “LOI will be signed from head office”); *Remarks* = কাজ শেষে ভেরিফায়ার যা **পেয়েছে** তার বর্ণনা। আগে Comment-এর নির্দেশও Done / Due-তে নোট হিসেবে ঢুকে যেত (যেমন নির্দেশের “Will be signed from head office” Done ও Due দুটোতেই আসত)। এখন Comment কেবল একটি কাজে লাগে — “Document” ট্রিপটি আসলে কিসের (LOI, Payslip, Tuition, Rental …) তা চেনা; ফলাফল, সমস্যা ও কারণ সবই Remarks (ও চলমান ট্রিপের সর্বশেষ Appointment-এর কারণ) থেকে।
- **Payslip বাক্যের ভুল পড়া ঠিক:** “HR payslip will be not verified. HR will verified only salary certificate.” আগে ভুল করে “Head office disagree” নোটও দিত। এখন ফল: `Done-… LOI (HR verifies salary certificate only)` / `Due-LOI (HR verifies salary certificate only)` — Comment যা-ই লেখা থাকুক। (সত্যিকারের “HR does not agree to verify the LOI” লেখা থাকলে “Head office disagree” আগের মতোই আসে।) Comment-এর কোনো শব্দে (“different”, “current”, “parent”) আর ভুল করে *Rental* আইটেম বসে না।
- **File History ক্র্যাশ ঠিক:** কোনো শিট ফাঁকা থাকলে (যেমন সব নম্বর পাওয়া গেলে ‘Not Found’ শিটে কিছুই থাকে না) Excel বানানোর সময় `TypeError: 'MergedCell' object is not iterable` দিয়ে পুরো রান থেমে যেত। কারণ: ফাঁকা শিটে ফ্রিজ-করা ঘরটি “কিছু নেই” লেখা মার্জ-করা সারির ভিতরে পড়ত। এখন কোনো শিট ফাঁকা হলেও ইতিহাস ঠিকভাবে তৈরি হয় (‘Not Found’ শিটে “Every number was found.” লেখা থাকে)।
- **File History-র ইনপুট Excel: `File No` + `Applicant Name`।** শুধু দুটি কলাম দিলেই ইতিহাস চলে আসে। শিরোনাম-শব্দ (File No / Tracking No …, আর Applicant / Customer / Name / আবেদনকারী / নাম) দেখে কলাম চেনা হয়; ফাইল নম্বর পুরো (`CC-…`) বা শেষের কয়েকটি অঙ্ক — দুটোই চলে; নাম ঐচ্ছিক (না দিলে আগের মতোই)। ফাইল নম্বর *নাম দিয়ে* খোঁজা হয় না — নম্বর দিয়েই খোঁজা হয়, নাম মেলানোর জন্য।
- **Name Check:** নাম দেওয়া থাকলে Summary শিটে তিনটি নতুন কলাম — *Applicant Name (given)*, *Name Check*, *Applicant on the file*। **Matches** = একই ব্যক্তি (Md. / Mohammad, শব্দের ক্রম, একটি শব্দ কম, ছোট বানান-ভুল সহনীয়); **Matches Guarantor 1 / Co-Applicant** = নামটি ফাইলের অন্য concern-এর; **Different** = ফাইলের Applicant অন্য নাম (পাশের কলামে দেখানো)। ‘Not Found’ শিটেও দেওয়া নাম থাকে। নাম না দিলে শিটগুলো হুবহু আগের মতো।
- **নমুনা Excel:** ‘ফাইল হিস্টরি’ বাছলে ‘⬇ নমুনা Excel (File No + Applicant Name) সংরক্ষণ করুন’ বোতাম; রিপোজিটরিতেও আছে: `templates/File_History_Format.xlsx` (প্রথম শিটে দুই কলাম + ৫০০ প্রস্তুত সারি; File No কলাম Text ফরম্যাটে যাতে শুরুর শূন্য কখনো হারায় না; দ্বিতীয় শিটে কীভাবে ভরতে হবে)।
- **আগের কোনো অপশন বদলায়নি:** ট্র্যাকার, তারিখ-সীমা, Re-CPV, সাধারণ এক্সেল, ইমেইল, ছুটি, SLA নিয়ম, Incomplete নিয়ম — সবই Version 4-এর মতো (শুধু Done / Due-র Comment-নির্ভরতা বাদ)।
- **পরীক্ষা:** মোট **১৬২টি স্বয়ংক্রিয় টেস্ট** (Version 5-এর ৩৩টি নতুন: ক্র্যাশ, নাম-সহ ইনপুট, Name Check, নমুনা Excel, Comment-বনাম-Remarks “due check”, ড্যাশবোর্ড→ট্র্যাকার Excel পর্যন্ত end-to-end, এবং আসল ড্যাশবোর্ডে দেখা ফাইলের ধাঁচে ৩টি) এবং আসল অ্যাপ-উইন্ডোর GUI smoke test-এ এখন File History ধাপও আছে (Windows, macOS, Linux)।

---

নিয়মের পূর্ণ বিবরণ, পুরো ওয়ার্কফ্লো, কমান্ড লাইন ও ইতিহাস: রিপোজিটরির `README.md`।
