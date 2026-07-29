# Deterministic QA Current Behavior Report

Sanity run result against the current repo extraction services: **11 passed / 16 total QA pairs**.

This report is not the expected-answer source of truth. The expected-answer source is the JSON under `../qa_pairs/`. This report records what the current implementation does today, so known gaps are visible before formal test automation is added.

| QA ID | Field | Status | Expected | Actual | Flags | Failure category / reason |
|---|---|---|---|---|---|---|
| `EV-FUELQTY-001-Q001` | `facility_name` | passed | 'Anheuser-Busch Baldwinsville Brewery' | raw='Anheuser-Busch Baldwinsville Brewery'; normalized='Anheuser-Busch Baldwinsville Brewery'; unit=None |  |  |
| `EV-FUELQTY-001-Q002` | `fuel_type` | passed | 'Natural Gas' | raw='Natural Gas'; normalized='Natural Gas'; unit=None |  |  |
| `EV-FUELQTY-001-Q003` | `activity_quantity` | passed | 32400 MMBtu | raw='32,400 MMBtu'; normalized=32400; unit='MMBtu' |  |  |
| `EV-FUELQTY-001-Q004` | `activity_unit` | passed | 'MMBtu' MMBtu | raw='MMBtu'; normalized='MMBtu'; unit='MMBtu' |  |  |
| `EV-FUELQTY-001-Q005` | `service_period_start` | passed | '2023-01-01' | raw='01/01/2023'; normalized='2023-01-01'; unit=None |  |  |
| `EV-FUELQTY-001-Q006` | `service_period_end` | failed | '2023-01-31' | raw='32,400 MMBtu'; normalized='32,400 MMBtu'; unit=None |  | extraction_algorithm_gap: substring anchor collision (`To` matches `Total Usage`); expected value '2023-01-31'; got '32,400 MMBtu' |
| `EV-FUELQTY-001-Q007` | `supplier_name` | passed | 'National Fuel Gas Company' | raw='National Fuel Gas Company'; normalized='National Fuel Gas Company'; unit=None |  |  |
| `EV-FUELQTY-001-Q008` | `account_number` | passed | 'ACC-2023-BWV-001' | raw='ACC-2023-BWV-001'; normalized='ACC-2023-BWV-001'; unit=None |  |  |
| `EV-FUELQTY-002-Q001` | `activity_quantity` | failed | 32400 MMBtu | raw='32,400'; normalized=32400; unit=None | unit_missing | extraction_algorithm_gap: nearby unit inference not implemented; expected unit 'MMBtu'; got None |
| `EV-FUELQTY-003-Q001` | `activity_quantity` | passed | 32400 | raw='32,400'; normalized=32400; unit=None | unit_missing |  |
| `EV-FUELQTY-004-Q001` | `activity_quantity` | failed | None | raw='2023'; normalized=2023; unit=None | unit_missing | extraction_algorithm_gap: negative/no-activity guard not implemented; expected no found value; got raw_value='2023' |
| `EV-MOBFUEL-001-Q001` | `fuel_type` | passed | 'Diesel (No. 2 Distillate)' | raw='Diesel (No. 2 Distillate)'; normalized='Diesel (No. 2 Distillate)'; unit=None |  |  |
| `EV-MOBFUEL-001-Q002` | `activity_quantity` | passed | 2800 gallons | raw='2,800 gallons'; normalized=2800; unit='gallons' | unit_conversion_not_implemented |  |
| `EV-MOBFUEL-001-Q003` | `activity_unit` | passed | 'gallons' gallons | raw='gallons'; normalized='gallons'; unit='gallons' |  |  |
| `EV-MOBFUEL-002-Q001` | `activity_quantity` | failed | 900 gallons | raw='2023'; normalized=2023; unit=None | unit_missing | extraction_algorithm_gap: multi-record row binding not implemented; expected value 900; got 2023; expected unit 'gallons'; got None |
| `EV-MOBFUEL-002-Q002` | `activity_quantity` | failed | 850 gallons | raw='2023'; normalized=2023; unit=None | unit_missing | extraction_algorithm_gap: multi-record row binding not implemented; expected value 850; got 2023; expected unit 'gallons'; got None |
