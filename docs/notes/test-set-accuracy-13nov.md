# Staging GHG test set: recognition and extraction accuracy (13 Nov)

Scored against `STG_answer_key.csv` (22 files), AI off, OCR off (Textract is unavailable locally, so the 3 image/scan files halt as `ocr_required` both before and after; on staging they were read).

Recognised (a document type is set): locally before 13/22, after 18/22. On staging (OCR on, so the photo and scan were read) that is 15/22 before and 20/22 after; the meter photo and the client note remain unrecognised.

Scored fields (what the rule extractors target): supplier, account number, period start, period end, activity quantity (per record for multi-record files; therms compared after the MMBtu conversion). Each cell is matched / missed / wrong. Answer-key fields the extractors do not target (statement date, total amount, meter reads, demand, on/off-peak, notes) are counted as `not scored`. This is an automated approximation, not a reviewer's judgement: transaction/service dates count towards period start.

| File | Expected type | Type before | Type after | Before (match/miss/wrong) | After (match/miss/wrong) | Not scored |
|---|---|---|---|---|---|---|
| STG_Riverside_Electric_2025-03.pdf | Electricity bill | CT-S2-ELEC | CT-S2-ELEC | 4/0/0 | 4/0/0 | 9 |
| STG_Harbor_Electric_2025-12.pdf | Electricity bill | CT-S2-ELEC | CT-S2-ELEC | 1/3/0 | 4/0/0 | 9 |
| STG_Riverside_Electric_2025-07_scan.pdf | Electricity bill (scanned) | none | none | 0/4/0 | 0/4/0 | 11 |
| STG_Harbor_Electric_2025-05.docx | Electricity bill (Word) | CT-S2-ELEC | CT-S2-ELEC | 4/0/0 | 4/0/0 | 7 |
| STG_Riverside_Gas_2025-01.pdf | Natural gas bill | none | CT-S1-FUELQTY | 0/6/0 | 5/1/0 | 7 |
| STG_Harbor_Gas_2025-02_photo.jpg | Natural gas bill (photo) | none | none | 0/5/0 | 0/5/0 | 4 |
| STG_Riverside_Gas_2025-Q2.xlsx | Natural gas portal export | none | CT-S1-FUELQTY | 0/11/0 | 11/0/0 | 6 |
| STG_Riverside_Propane_2025.pdf | Propane delivery invoice | CT-S1-FUELQTY | CT-S1-FUELQTY | 2/2/0 | 2/2/0 | 8 |
| STG_Harbor_FuelOil_2025-11.pdf | Heating oil delivery ticket | CT-S1-FUELQTY | CT-S1-FUELQTY | 2/1/0 | 2/1/0 | 7 |
| STG_Riverside_Generator_Diesel_2025.csv | Generator run log (CSV) | CT-GHG-FACSRCLIST | CT-S1-FUELQTY | 24/0/0 | 24/0/0 | 5 |
| STG_Riverside_Generator_Diesel_2024-2025.xls | Generator run log (legacy XLS) | CT-GHG-FACSRCLIST | CT-S1-FUELQTY | 10/0/0 | 10/0/0 | 5 |
| STG_Harbor_FleetCard_2025-Q3.pdf | Fleet fuel card statement | CT-S1-MOBFUEL | CT-S1-MOBFUEL | 18/10/22 | 18/10/22 | 19 |
| STG_Harbor_Mileage_2025.xlsx | Vehicle mileage log | none | CT-S1-MOBFUEL | 0/48/0 | 48/0/0 | 71 |
| STG_Harbor_Refrigerant_Service_2025.pdf | Refrigerant service log | CT-S1-REFRSVC | CT-S1-REFRSVC | 1/1/0 | 1/1/0 | 35 |
| STG_Riverside_Refrigerant_Invoice_2025-09.pdf | Refrigerant purchase invoice | none | CT-S1-REFRSVC | 0/2/0 | 2/0/0 | 7 |
| STG_Riverside_Steam_2025-01.pdf | District steam bill | CT-S2-THERMAL | CT-S2-THERMAL | 5/1/0 | 5/1/0 | 6 |
| STG_Harbor_Electric_2025-04_email.eml | Electricity bill (email body) | CT-S2-ELEC | CT-S2-ELEC | 3/1/1 | 3/1/1 | 8 |
| STG_Riverside_Meter_Photo_2025-06.png | Meter photo | none | none | 0/0/0 | 0/0/0 | 5 |
| STG_Notes_From_Client.txt | Client note (unstructured) | none | none | 0/14/0 | 0/14/0 | 3 |
| STG_Riverside_Utility_Bundle_2025.pdf | Electricity bill (bundle) | CT-S2-ELEC | CT-S2-ELEC | 4/22/0 | 4/22/0 | 88 |
| STG_Mystery_Document.pdf | Natural gas bill (untitled layout) | none | CT-S1-FUELQTY | 0/6/0 | 0/6/1 | 8 |
| STG_Company_GHG_Inventory_2025.xlsx | Company-prepared GHG inventory (not source evidence) | CT-GHG-WORKBOOK | CT-GHG-WORKBOOK | 0/0/0 | 0/0/0 | 19 |

## Per-field detail (after)

- STG_Riverside_Electric_2025-03.pdf: before: supplier 1/0/0, account 1/0/0, start 1/0/0, end 1/0/0; after: supplier 1/0/0, account 1/0/0, start 1/0/0, end 1/0/0
- STG_Harbor_Electric_2025-12.pdf: before: supplier 1/0/0, account 0/1/0, start 0/1/0, end 0/1/0; after: supplier 1/0/0, account 1/0/0, start 1/0/0, end 1/0/0
- STG_Riverside_Electric_2025-07_scan.pdf: before: supplier 0/1/0, account 0/1/0, start 0/1/0, end 0/1/0; after: supplier 0/1/0, account 0/1/0, start 0/1/0, end 0/1/0
- STG_Harbor_Electric_2025-05.docx: before: supplier 1/0/0, account 1/0/0, start 1/0/0, end 1/0/0; after: supplier 1/0/0, account 1/0/0, start 1/0/0, end 1/0/0
- STG_Riverside_Gas_2025-01.pdf: before: supplier 0/1/0, account 0/1/0, start 0/1/0, end 0/1/0, qty 0/2/0; after: supplier 1/0/0, account 1/0/0, start 1/0/0, end 1/0/0, qty 1/1/0
- STG_Harbor_Gas_2025-02_photo.jpg: before: supplier 0/1/0, account 0/1/0, start 0/1/0, end 0/1/0, qty 0/1/0; after: supplier 0/1/0, account 0/1/0, start 0/1/0, end 0/1/0, qty 0/1/0
- STG_Riverside_Gas_2025-Q2.xlsx: before: supplier 0/1/0, account 0/1/0, start 0/3/0, end 0/3/0, qty 0/3/0; after: supplier 1/0/0, account 1/0/0, start 3/0/0, end 3/0/0, qty 3/0/0
- STG_Riverside_Propane_2025.pdf: before: supplier 0/1/0, account 0/1/0, qty 2/0/0; after: supplier 0/1/0, account 0/1/0, qty 2/0/0
- STG_Harbor_FuelOil_2025-11.pdf: before: supplier 1/0/0, account 0/1/0, qty 1/0/0; after: supplier 1/0/0, account 0/1/0, qty 1/0/0
- STG_Riverside_Generator_Diesel_2025.csv: before: qty 24/0/0; after: qty 24/0/0
- STG_Riverside_Generator_Diesel_2024-2025.xls: before: qty 10/0/0; after: qty 10/0/0
- STG_Harbor_FleetCard_2025-Q3.pdf: before: supplier 0/1/0, account 0/1/4, start 0/1/18, end 0/1/0, qty 18/6/0; after: supplier 0/1/0, account 0/1/4, start 0/1/18, end 0/1/0, qty 18/6/0
- STG_Harbor_Mileage_2025.xlsx: before: qty 0/48/0; after: qty 48/0/0
- STG_Harbor_Refrigerant_Service_2025.pdf: before: supplier 1/0/0, account 0/1/0; after: supplier 1/0/0, account 0/1/0
- STG_Riverside_Refrigerant_Invoice_2025-09.pdf: before: supplier 0/1/0, qty 0/1/0; after: supplier 1/0/0, qty 1/0/0
- STG_Riverside_Steam_2025-01.pdf: before: supplier 1/0/0, account 1/0/0, start 1/0/0, end 1/0/0, qty 1/1/0; after: supplier 1/0/0, account 1/0/0, start 1/0/0, end 1/0/0, qty 1/1/0
- STG_Harbor_Electric_2025-04_email.eml: before: supplier 0/1/1, account 1/0/0, start 1/0/0, end 1/0/0; after: supplier 0/1/1, account 1/0/0, start 1/0/0, end 1/0/0
- STG_Riverside_Meter_Photo_2025-06.png: before: nothing scored; after: nothing scored (not recognised or no scored fields)
- STG_Notes_From_Client.txt: before: supplier 0/1/0, account 0/1/0, qty 0/12/0; after: supplier 0/1/0, account 0/1/0, qty 0/12/0
- STG_Riverside_Utility_Bundle_2025.pdf: before: supplier 1/0/0, account 1/0/0, start 1/11/0, end 1/11/0; after: supplier 1/0/0, account 1/0/0, start 1/11/0, end 1/11/0
- STG_Mystery_Document.pdf: before: supplier 0/1/0, account 0/1/0, start 0/1/0, end 0/1/0, qty 0/2/0; after: supplier 0/1/0, account 0/1/1, start 0/1/0, end 0/1/0, qty 0/2/0
- STG_Company_GHG_Inventory_2025.xlsx: before: nothing scored; after: nothing scored (not recognised or no scored fields)
