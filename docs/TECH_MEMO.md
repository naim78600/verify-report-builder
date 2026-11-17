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
3. **Appointment History** and **Last Update Details** show every trip of the file (`BillRow.file_appointments`, `last_update_for(..., flat)`),
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
