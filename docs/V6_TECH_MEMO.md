# Technical memo — the rules behind Verify Report Builder Version 6

**For:** the developers of the Verify dashboard · **From:** Barikoi operations (Prime Bank PLC desk) · **Version:** 6.0.0 · **Date:** 10 November 2026

Verify Report Builder is a desktop tool that reads the Verify dashboard (GET only) and produces what is sent to Prime Bank PLC:
the daily submission tracker, the monthly bill, and the file history. This memo writes down every rule the tool applies, from the
first one to the last, grouped by function, so the same logic can be built into the dashboard itself. Each section names the
function in this repository that is the reference implementation; the automated tests (`tests/`, 178 of them) are the executable
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
6. **LOI of an Out package verified In station** (the manual bill's rule): when every applicant house / office trip of the package is Out station but a document trip (LOI, salary certificate, pay slip …) is In station, that document is taken out of the package and is its own row at the In rate. The package stays an Out package.
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
4. A **package is Out if any of its trips is Out**; a single row is judged on its own trip.
5. Every "not sure" row is listed for a human to look at (tracker: flagged cell; bill: Check sheet). The dashboard's own Station field is not used for billing; a disagreement with it is shown as a note.

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
2. **Two mails a day**: Phase 1 (3:30 PM) = submitted before 3 PM; Phase 2 (7 PM) = the whole day, or only what was submitted after 3 PM.
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
   | 10 | Last Update Date | 20 | Before / After 3 PM |

   The Incomplete sheet has a 21st column, Pending Reason. Date cells are real dates so Excel filters work. In the PDF, File Type sits under File No and the two Last Update columns are one, to save width.

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

## 12. Version 6 against the manual September 2026 bill

The live dashboard was billed for September 2026 with Version 6 and compared row by row with the manual invoice and tracker.

| | Version 6 | Manual |
|---|---|---|
| Card rows / subtotal | 289 / 115,290 | 286 / 116,240 |
| Loan rows / subtotal | 561 / 204,920 | 563 / 205,470 |

347 of 492 files are identical; 722 of 849 manual rows have the same class and station. The differences, all by rule:

- **In / Out** (38 packages, 35 other rows): the tool uses the map, the manual bill was decided by hand.
- **Month** (about 40 rows): the manual sheet used its own receive date; the tool uses the dashboard's create date.
- **Later trips** (24 rows): a trip added 1–3 days after the file is its own row; the manual bill kept it inside the package.
- **Same-day LOI** (33 rows): the manual bill often billed it apart; the tool does so only for an Out package with an In-station LOI.
- **Re-created files** (6 packages): found in this comparison and fixed in 6.0.0 (rule 8.4). With the fix the figures are Card 287 / 114,090 and Loan 557 / 202,120 by calculation.
- **Penalty**: the tool charges 55 late submitted packages (35 of them one day late, at 20 %); the manual bill charged 15 and never charged one day.

## 13. Known limits

1. In / Out depends on approximate city outlines; border cases are flagged, not guessed silently.
2. Done / Due is rule-based. New wording is flagged Check and should be added as a rule.
3. Remarks that are replaced on the dashboard when a trip is finished later cannot be reproduced afterwards; a tracker made today shows today's state.
4. The appointment rule uses the latest-created appointment of the file.
