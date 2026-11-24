# Technical memo — the rules behind Verify Report Builder Version 10

**For:** the developers of the Verify dashboard · **From:** Barikoi operations (Prime Bank PLC desk) · **Version:** 10.0.0 · **Date:** 15 November 2026

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

## v10.0.6 changes (Naim, 17-11-2026, after comparing with the dashboard's own tracker file)

1. **Re-CPV / Extra column**: a trip the dashboard flags as Re-CPV (`is_for_recpv`) is written "Re-CPV" even when the Re-CPV tracker
   has no entry for it (`billing.history_for`). Before, the bill row said Re-CPV while this column said Extra.
2. **Report Summary of a line that stands for several bill rows** (`billing.refresh_summary`): the trips of ALL the folded rows are read
   together (two Re-CPVs submitted together -> "Done-App Office, Sign, LOI"; a pending file -> every open trip is Due). A later trip that
   finishes the same item still wins (`summary._merge`). Before, the other rows were summarised apart and matched by label, so "BS1" of
   one row could close "BS1" of another.
3. **Appointment History** and **Last Update Details** show every trip of the file (v18.0.2: Appointment History of a Re-CPV / Extra row shows only that row's trips - `report_text.shown_appointments`) (`BillRow.file_appointments`, `last_update_for(..., flat)`),
   as the dashboard's file does. The SLA rule itself is unchanged (it already used the whole file). Appointment type reads "Visit Place".
4. **Remark keywords**: "LOI Signed Dhaka Head Office" -> Signed from head office; "LOI not signed in front of me ... signed by <name>"
   -> LOI done, note "Not signed in front of me" (Done only); "LOI not signed because LOI sign will be head office" -> one reason.
5. **LOI for the head office** (`summary._head_office_loi`): never in Done, only in Due - "LOI (New trip created for head office
   verification)" when a document trip names the head office (comment / address) or a LOI trip was made 30+ minutes after that remark;
   else "LOI (Will be verified from head office)". Guarantor "Information ok." stays Done with nothing due (Naim: it includes the sign).
6. Not changed (Naim's answer): the tracker still reads files of the last 90 days only (an older Partially Submitted file is not listed).

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

**v16 trip-wise page ("Design A")** — `history_trips.py` (data), `history_tripwise.py` (Excel sheet + A4 landscape PDF).
The first sheet "File History" and the PDF `File_History_<date>.pdf` show one block per searched file, one line per trip.
Nothing new is decided there; every value comes from the existing rules:
1. Receive date, Package In / Out, SLA days, TAT, Extra TAT, SLA breach: the file's **Package** bill row (`billing.build_rows` + `compute_tat`, section 4 and 6).
2. Extra trip count and dates: the file's other bill rows (Single "Extra Trip n", Re-CPV, Extra Document ...), not the split documents (`history_trips.file_block`).
3. Report summary line (Done-... | Due-...): `summary.analyze` over every trip of the file, `submitted` = file status Submitted (section 3).
4. Per trip (`history_trips._results_by_trip`, items matched by `Item.src` = trip id):
   - **Due** + reason = an open / problem item of that trip (the bracket note; an appointment comes first);
   - **Done** + **Negative** = the trip's item (or an item read out of its remark, e.g. a LOI in an office remark) is Done but has a problem note — the same item is repeated in Due by the Report Summary rule;
   - **–** + dashboard status = a Canceled / Inactive / Withdrawn trip the summary leaves out.
5. Trip names are the Report Summary's (App House, PG1 Office, LOI, BS1, Chamber ...); "Trip added" = created date + the bill row it belongs to; "Trip update" = the newest activity-log event of the trip.
6. Fonts: PDF Fira Sans (OFL, embedded, `assets/fonts`), Excel Calibri. Colours from `theme.py` (no red, no yellow).

**v16 list from a photo / PDF** — `list_reader.py`.
1. "Excel / CSV / ছবি / PDF বাছুন" takes several files at once. Excel / CSV as before (`parse_ids_file`).
2. Photo: the computer's own OCR **with word positions** (Windows OCR via PowerShell `_WIN_OCR_BOXES`; Mac Vision `assets/bin/mac_ocr --boxes`; tesseract when installed). `rows_from_boxes`:
   - file-number-like words (4-8 digits, full numbers such as `PL-2026…`, `CPV-0229-AL`; never phones `01xxxxxxxxx` or dates);
   - the file-number column = the x-position most of them share (house numbers in addresses fall out);
   - one row per number (a `CPV-…` and a `(610885)` stacked in one cell = one row); a "TAT 7+" marker with no number next to it = a row whose number the OCR missed ("?");
   - the row reaches half way to the next row; name = the words right of the number column up to the first comma; the row's date; other file-number-like values in the row (e.g. `PEC-20261007071238531`) become extra numbers.
3. PDF with text: `rows_from_text` (a row ends at the phone number). Scanned PDF: the pictures inside are read as photos.
4. Overlapping photos: the same number only once; a "?" row whose name is already in the list is dropped.
5. The result is written into the text box as editable lines `numbers | name | date` — the user checks it before running. `parse_ids_text` reads these lines back (`a / b` = several numbers of one row, `?` = no number → kind "name").

**v16 search order** — `file_history.find_files` (Naim 23-11-2026: the bank's list had other / wrong numbers):
1. The number as written. With a name and several files ending in it: only the files where applicant / co-applicant / guarantor name matches (`names_match`) are kept — if at least one does.
2. Not found / no file with that name: the other numbers of the same row.
3. Still nothing: the applicant name, but only together with either a number one digit off (5+ digits; then `names_match`) or a start date between 45 days before and 15 days after the row's date (no date in the row and no number: the last 120 days; then `names_match` AND the stricter `strict_names_match`: every distinctive word — not Md / Mia / Begum …, not an initial — has a twin both ways, one extra word only when 2+ words match). Live check 23-11-2026: "Md Sumen Miah" is not taken as "MD SHOPUN MIAH" (17-10-2026), nor "MOHAMMAD SUMON" / "MD SUMON" (one word missing), nor "MD. SUMON MIA" (2025).
   Another number of the row with a different prefix (PEC-2026… for CC-2026…, 14+ digits) matches by its digits.
4. The report note says how the file was found ("Found by CPV-0229-AL …", "Found by applicant name + a number one digit off …").
5. Names come from the live list (`NameLookup`, one month per request, this run only) — the file index on disk still holds numbers and dates only.

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
6. **Bank received**: the user uploads the client's signed list (Excel, CSV, PDF with text, or a photo – read with Windows' or macOS' own
   OCR). A BS counts as received when its Trip ID, its File No (or the File No's digits) or the applicant's full name is in the
   list; when a file has two BS and only the name is found, the bank's name must be on the same line (`match_signed_list`).
   The program then lists the BS that were sent but are not in the list.
7. **Pending BS** (`pending_bs`), no cap: not yet collected on an open trip, or collected but not yet in the office / courier.
   Checked at **12:00 PM and 6:15 PM** (the latest missed check runs when the program opens).

### 14.3 Verifier reminders on WhatsApp
Reference: `reminders.py`, `helper_server.py`, `assets/whatsapp_helper/`, `pages.RemindersPage`.

1. **Who**: every verifier with an open trip (Created / Allocated / Started / Hold) in an ON GOING or HOLD file, both clients,
   plus verifiers who still have to hand in a collected BS. No cap.
2. **When**: 10:00 AM, 1:00 PM and 4:00 PM – every on-going / hold trip, appointments of today first (the BS reminder is not in the 10 AM round); A trip whose appointment is on a later day is
   skipped until that day; with an appointment today it is reminded until finished. Office days only, until 6:15 PM; if the PC
   was off, the latest missed round is prepared when the program opens.
   **v10.0.3**: the Reminders page is three steps (messages ready -> "Start sending" -> replies). "Start sending"
   (`Shell.start_sending`) raises a 3-minute token on the local helper server; the first WhatsApp Web tab with the helper
   claims it (`POST /claim`, one tab only) and opens the first chat. Send is still pressed by the user. The page shows
   "connected" only while the helper really asks the server (`HelperServer.extension_connected`, last contact < 45 s).
   The helper's files are copied to `~/.verify_report_builder/whatsapp_helper` (`helper_folder()`), the fixed folder for
   Chrome's "Load unpacked". Own-message detection in the chat list follows WhatsApp Web of Nov 2026
   (`svg title` = `wds-ic-read` ... inside `last-msg-status`). Voice clips: Edge "bn-BD-PradeepNeural", made once in CI.
   BS: the month list has every month; the bank is also read from the trip's address when the name field is empty.
   **v10.0.5** (after the first real round on WhatsApp Web): the message starts with the verifier's name and has one
   line per trip - `File | Trip ID | trip type | Applicant` (`reminders.message`); a "reply" that is our own reminder
   (WhatsApp's last-message preview) is never stored (`is_own_text`); "sent" is seen from the last message of the chat
   (`[data-testid="conv-msg-..."]`, `lastMsgId` in content.js) - before, it was never seen, so a chat could open twice;
   the helper box sits bottom-left because WhatsApp's Send buttons are bottom-right. v10.0.4: the verifier list is read
   from the live reply `{"taskers": [...]}`.
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

## 15. Version 12 (18 November 2026)

**Reminder rounds** (`reminders.ROUNDS`, `build_queue`): 8:00 AM today's active appointments only; 10:00 AM, 1:00 PM and 5:30 PM every
trip of an On Going / Hold file that is not finished; 3:00 PM appointments still open (with a thank-you line for trips finished today).
Office days only (not Friday / Saturday), catch-up of the latest missed round until 6:15 PM (`due_round`). Files whose File No
contains "test" are never reminded. Bank statements to hand in ride along only at 1:00 PM and 5:30 PM (`BS_ROUNDS`): collected and not
in the office / with a courier / received by the bank; an Online BS is skipped once it is marked handed in at the bank.

**Message** (`message`): dashboard words — `Trip ID · type · status`, File No / Applicant, Appointment, Hold reason / Comment, what to do
(`TODO`, by `task_kind`: chamber → Chamber report form, rental → Rental report form, LOI, PG sign …), SLA line (`report_due`: an
appointment → next working day 5:59 PM, else the file SLA). Hold trips first, with the request to update the Hold reason or finish with
remarks. At most 8 trips are written (`MAX_TRIPS`), the count in the heading is the full count.

**Answers** (`tap_links`, `parse_code`, `record_reply`): each message has one code `VB-MMDD-round-n`; the links are
`https://wa.me/<own number>?text=<short English words> #<code>-T1..T3 | B1..B3`. T1 going, T2 done, T3 problem, B1 will hand in today,
B2 handed in, B3 problem. The code ties the answer to the trips of that message (`find_item`). B2 opens a photo ask (`FOLLOW_PHOTO`),
a problem opens a note ask (`FOLLOW_NOTE`); the next plain text from that number is the note. Asks are in `reminders.json → asks`.
No own number in Settings → plain "1 = … 2 = … 3 = …" lines instead of links.

**Follow-ups and slip photos** (`helper_server`: `GET /asks`, `POST /ask_sent`, `POST /media`; `content.js`: `openNextAsk`,
`continueAsk`, `grabPhotos`): the helper opens each follow-up chat with the text typed — the person presses Send. A picture that
arrives after a photo ask (chat list shows "Photo") is announced in the panel; when the chat is open the helper reads the full-size
image (blob URL) and posts it. The program saves one copy per BS trip of that answer in
`<reports folder>/BS Slips/<YYYY-MM-DD>/<Trip ID> - <verifier>/slip HHMMSS.jpg` and marks the BS `bank_submitted`
(`bs_tracker.set_bank_submitted`). More slips are taken for 6 hours after the first one; the same message is never saved twice.
The helper never presses Send (`.click()` does not occur in content.js).

**Voice** (`voice.py`, `voice_text`): one clip per message, Microsoft Edge read-aloud voice `bn-BD-PradeepNeural`, rate −12 %, made on
the PC when the round is prepared (internet needed), kept 3 days in `~/.verify_report_builder/voices`. Trip IDs digit by digit, names
in Bangla letters (`translit`), "S, L, A" and "এল, ও, আই" letter by letter. If a clip cannot be made the message goes without it.

**BS page** (`pages.BSPage`, `bs_tracker.still_with_verifier`, `by_verifier`): "who still holds a BS" = collected (from the remark),
trip not cancelled / withdrawn, and not in the office, with a courier, received by the bank or handed in at the bank; grouped by verifier
(most first), oldest withdrawal first, with the bank and the day the trip was finished (= withdrawn).

**End-to-end check** (`devtools/e2e_v12/run.py`): the real helper extension on a mock WhatsApp page against the real HelperServer —
round sent (text + voice), tap-link answers, follow-ups, slip photo saved, note saved.

## 16. Version 13 (19 November 2026)

Four tracker rules added after comparing the VRB tracker with the dashboard's own tracker of 19-11-2026 Phase 2; nothing else changed.

1. **Replaced bank statement** (`summary._replaced_banks`, used in `summary.analyze`): a BANK trip that is Canceled / Inactive /
   Withdrawn (status 6/7/8) is dropped from the Report Summary - not Due, no BS number - when a LATER BANK trip of the same person
   (same role label) is Finished (status 5). If the later BS is not finished yet, the old problem stays Due (v6 rule).
2. **Concerns Name = every trip of the file** (`billing.build_rows` -> `BillRow.file_concern_lines`; used by `prime_excel` and
   `prime_pdf`). The monthly bill keeps `concern_lines` (the bill row's own trips).
3. **KPI "FILES" = unique File No** (`prime_excel._report_sheet`, `n_files`).
4. **Re-opened file** (`collect_prime.collect_prime` after `dashboard_check`): a Complete row whose file is no longer Submitted on
   the dashboard gets `reopen_note` ("Re-opened since - now On Going on the dashboard"), shown in Report Status in orange (Excel + PDF).

TAT formula kept as `NETWORKDAYS.INTL` (no `_xlfn.` prefix): it is part of the ISO OOXML function set; LibreOffice shows #NAME? for
`_xlfn.NETWORKDAYS.INTL` (checked), while the plain name works in Excel and LibreOffice.

### Logic markers in the source (v13, 19-11-2026)
Search the code for `★ DONE/DUE LOGIC` (the Report Summary engine: summary.py, billing.refresh_summary / concern_info, report_text.summary_lines)
and `◆ DASHBOARD-MATCH LOGIC` (other rules the dashboard tracker must copy: selection, folding, Pending Reason, SLA / TAT, Area, columns).
summary.py starts with a reading-order index. Comments only - no behaviour changed.

## 17. Version 15 (20 November 2026) - Mushak-6.3 with the monthly bill

No billing rule changed. Added:

1. **`mushak.py`** - `write_mushak_pdf(bill, path)`: one A4 page per bill, the fixed form `assets/mushak63_template.pdf`
   (Bangla text and lines; source `devtools/mushak/template.html`, rendered once with Chromium so the Bangla is shaped) plus a
   reportlab overlay merged with pypdf. Values (`mushak_values`): column (6) = `Bill.after_penalty`, (9) = `VAT_PCT`%,
   (10) = `Bill.vat`, (11) = `Bill.grand_total`; the same three in the total row with "/-". Buyer constants `BUYER_NAME`,
   `BUYER_BIN`, `BUYER_ADDRESS`; issue date = `bill.bill_date` ("Nov 20, 2026"); line "CPV service <Card|Loan> (for the month of <Month> <Year>)".
   Left blank on purpose: challan number, issue time, responsible person's name / designation, signature, seal.
2. **`bill_out.write_month_bill(..., mushak=True)`** also writes `Prime_Bank_PLC_<Card|Loan>_Mushak6.3_<Month>_<Year>.pdf`;
   `pdf_from_excel` remakes the Mushak from the edited workbook, so its amounts follow the Penalty sheet's Apply choices.
3. **`bill_out.bill_attachments(out_dir)`**: files in `<output folder>/Bill Attachments` (certificates) are listed with the bill
   outputs in the window (`gui._work_bill`). Nothing of them is stored in the program.
5. **Re-created copy under another prefix** (`monthly_bill.file_key`, used in `build_month_bill`): a Canceled package whose
   number, without its letter prefix, belongs to a living package (PL-20261115112802097 Canceled -> HL-20261115112802097 created
   again, live 20-11-2026) is left out like any Canceled copy; the excluded reason names the new number. Only numbers with the long
   date-time digits (14+) are folded, so PL-0274 style numbers are compared as they are.
6. Tests: `tests/test_v15.py`; the expected bill file lists in `test_v6`, `test_cli` and `gui_smoke` now include the two Mushak PDFs.

## 18. Version 18 (24 November 2026) - verifier directory, WhatsApp check, new dashboard

No report or billing rule changed. Added:

1. **Verifiers only** - `client.verifier_phones` keeps a /api/v2/verifiers entry only when `user_role` is 4 (or absent) and
   `status` is 1. Every directory action checks the id is in this list (`helper_server.directory_update`, `save_photo`,
   `verifier_dir.parse_import`): nobody else can be added.
2. **`verifier_dir.py`** - `number_of` (number Naim set in settings `phone_overrides`, else the dashboard number - the same list
   the reminder rounds use); `wa_status` -> none | bad | no | ok | unchecked from the reminders state (`no_whatsapp`, new
   `wa_ok` {8801...: date}); `to_check` (valid numbers never checked, "ok" ones after `RECHECK_DAYS` = 30; "no" ones are not
   checked again); `read_rows` / `parse_import` / `apply_import` (Excel .xlsx or CSV; match by ID, else by an exact name that
   only one verifier has); `save_photo` (any Pillow format, HEIC with pillow-heif; 320 x 320 JPEG in
   `~/.verify_report_builder/verifier_photos/<id>.jpg`), `match_photo_files`, `export_csv`, `directory`.
3. **WhatsApp check** - helper `content.js` (v18.0.0): `maybeStartCheck` polls GET `/wa_check`; with a token it claims it
   (`/wa_check_claim`), then for each number opens `web.whatsapp.com/send?phone=<n>` with no text and posts `/wa_check`
   {phone, ok}: ok = the message box appears, not ok = WhatsApp's invalid-number dialog; 6 s between numbers. The token comes from
   the button (`request_check(auto=False)`) or once a day after the dashboard is read (`shell._daily_wa_check`, auto=True): an
   automatic check starts only after 90 s without a click / key in the WhatsApp tab and stops on the next one.
4. **Helper server** - new routes `/wa_check`, `/wa_check_claim`, `/directory` (GET list; POST {id, num | noWa}),
   `/directory_check`, `/photo/<id>`, `/photo`. Same rules as before: 127.0.0.1 only, extension origins only; the new dashboard
   sends `X-VRB-Dashboard: 1` so it is not counted as the WhatsApp helper being connected.
5. **New dashboard extension** - `assets/new_dashboard` (copied to `~/.verify_report_builder/new_dashboard` by
   `new_dashboard_folder`): on verify.bmapsbd.com/vrb-dashboard it reads the dashboard API with the user's own session (GET only:
   status-counts, org/summery, sla-breaches, verifiers, first-last-task, re-cpv/tracker, trips/completed, manager/applications and
   details) and shows every dashboard page plus the new ones; `bg.js` talks to the helper server for the directory every 20 s.
6. Tests: `tests/test_v18.py` (verifiers only, status and re-check rules, CSV + Excel import, photos in 4 formats, export,
   every helper route incl. refusing a web page's origin).



## 19. v18.0.2 / v18.0.3 - English-only tracker, Re-CPV appointment history

1. **English only in the tracker (v18.0.3)** - `report_text.english_only`, used by `prime_pdf._safe` and by
   `prime_excel._put` / `_rich` / the Pending Reason cell: banks do not take Bangla in the report. A Bangla run followed by its
   English in brackets keeps the English ("... (Bank Asia Tower)" -> "Bank Asia Tower"); other Bangla runs are dropped and the
   punctuation tidied; a label left empty ("Address:") or a Bangla-only line becomes "(written in Bangla on the dashboard)".
   (v18.0.2 had embedded a Bangla font instead - removed in v18.0.3.)
2. **Appointment History** - `report_text.shown_appointments`: Package / Single rows - every trip of the file (v10.0.6);
   ReCpv / Extra rows - the row's own trips + its folded rows + the file's other ReCpv / Extra rows (v18.0.4) made on or after this row's Receive date (v18.0.5), never the
   package's trips. `english_only` also drops a comma left before " | " (v18.0.4). Found by comparing with the system report of
   24-11-2026 (PL-20261104113123122 showed the package trip's 11/11 appointment on its 22/11 Re-CPV row).

## 20. v18.1.0 - new look for the new dashboard (extension 18.1.0)
- Assets in `src/report_builder/assets/new_dashboard/` (app.js, logic.js, manifest 18.1.0); built from the v6 design build. No tracker, bill or helper rule changed.
- `logic.js`: new first tab `home` (state `tab:'home'`, `done:[]`). `out.todo` lists today's jobs from the existing alerts (SLA at risk, On Going / Hold without update 3+ days, Finished / Partial waiting for submit, ...), sorted by priority; each has a button that opens the right page with the list filter set; a tick toggles `S.done`. `hello` / `todayTxt` / ring show progress.
- `app.js`: Home section before Overview, a short hint under every menu item, barikoi.com look (white, green #16a34a, blue CTA #2563eb, Inter). Filter bar and alerts are hidden on Home only.
- Still GET only; the fallback / error message and re-attach observer from 18.0.1 are kept.
