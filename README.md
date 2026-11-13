# Flight Control / Booking Dashboard Data Generator

**Target:** Python 3.12.10. Uses only the Python standard library.

## Quick Start

From the directory containing `generate_flights.py`:

```sh
python3.12 generate_flights.py
```

This uses the current UTC time and writes to `./flight_data`:

| Path            | Contents                                                       |
| --------------- | -------------------------------------------------------------- |
| `dataset.json`  | All tables plus metadata in one JSON document                  |
| `metadata.json` | Snapshot, seed, date window, row counts, metric definitions    |
| `csv/`          | One CSV file for each of the 12 tables                         |

### Examples

Repeat the included sample exactly:

```sh
python3.12 generate_flights.py --as-of 2026-11-12T18:00:00Z --seed 42 --output flight_data
```

Smaller run:

```sh
python3.12 generate_flights.py --history-days 7 --future-days 7 --rotations 2 --output small_data
```

Exactly 60 calendar days, including the snapshot date:

```sh
python3.12 generate_flights.py --history-days 31 --future-days 28 --output two_months
```

Only historical days and today:

```sh
python3.12 generate_flights.py --history-days 59 --future-days 0 --output historical_data
```

### Options

| Option           | Description                                                    |
| ---------------- | -------------------------------------------------------------- |
| `--as-of`        | ISO timestamp with timezone, e.g. `2026-11-12T18:00:00Z`       |
| `--seed`         | Random seed (default `42`)                                     |
| `--history-days` | Days before the snapshot UTC date (default `30`)               |
| `--future-days`  | Days after that date (default `28`)                            |
| `--rotations`    | Aircraft count, 1 to 6; two flights per aircraft daily         |
| `--change-rate`  | Fraction of eligible reservations sampled for change, 0 to 1   |
| `--output`       | Output directory (default `./flight_data`)                     |

### Constraints

- `history-days + future-days + 1` must be `<= 60`.
- Future dates cannot exceed the corresponding date next calendar month (clamped at month end).
- The default is 59 dates, safe even across February.
- Departures on the last allowed date are included.
- Fix both `--as-of` and `--seed` for repeatable files.
- Existing generated filenames in the output directory are replaced.

### Timezone Data

On systems whose Python lacks IANA timezones, install the `tzdata` package:

```sh
python3.12 -m pip install tzdata
```

Most macOS/Linux installations already supply the timezone database.

## Tables and Relationships

### `airports`

`airport_code` primary key. Name, city, country, coordinates, IANA timezone.

### `aircraft`

`aircraft_id` primary key. Registration, model, seat capacity, home airport, manufacture year, current status and location. Location is null in flight.

### `routes`

`route_id` primary key. Origin/destination `airport_code`, great-circle distance, scheduled block time, reference fare.

### `flights`

`flight_id` primary key for **one** dated flight; `flight_number` repeats daily. Links `route_id` and `aircraft_id`. Includes local service dates, UTC scheduled, estimated and actual timestamps, status, gate, terminal, delays, cancellation reason, capacity, counts, availability, current price, sales and refunds.

### `passengers`

`passenger_id` primary key. Synthetic names, birth dates, reserved `example.com` email addresses and loyalty tier. Each generated traveler has one current flight reservation. Names can repeat; IDs and emails are unique.

### `bookings`

`booking_id` primary key. Unique reference, original and current `flight_id`, `lead_passenger_id`, party size, channel, fare type, timestamps and payment. Each booking is a one-way party of 1–5 people, including at least one adult.

### `booking_passengers`

`ticket_id` primary key. Joins `bookings` to `passengers`. Current flight and seat, cabin, baggage, assistance, check-in and boarding status/timestamps.

- Passenger counts come from these tickets or `SUM(bookings.party_size)`.
- `COUNT(bookings)` counts reservations, not people.

### `flight_changes`

`change_id` primary key. Links `booking_id`, `from_flight_id` and `to_flight_id`. Change time/reason, party count, fare difference, fee and total adjustment.

- Current booking/tickets point to the **new** flight; the old flight releases those seats.
- Changes stay on the same route, within seven days, and do not overbook a destination flight or reduce a source manifest below 60.
- Each selected reservation changes at most once in this dataset.

### `maintenance`

`maintenance_id` primary key, `aircraft_id` foreign key. Scheduled inspections and unplanned repairs, airport, interval, status, cost and affected flights.

- Completed/current/future maintenance is distinguished at snapshot time.
- Aircraft never operate during a maintenance interval.

### `flight_events`

`event_id` primary key, `flight_id` foreign key. Chronological booking, change, cancellation, delay, departure and arrival audit events.

- Booking creation stays attached to the original flight even when a booking later changes.
- No recorded audit event occurs after the snapshot.

### `daily_metrics`

One row per date, including `week_start_date` (Monday), ISO week/year and month. Counts, capacity, passengers, departure delays, punctuality, sales, refunds and maintenance. Ready for date/week/month chart aggregation.

### Conventions

- All foreign keys link to the similarly named IDs in the corresponding tables.
- All amounts are USD; generated fares are synthetic totals including taxes.
- CSV booleans are `true`/`false`; nulls are empty cells. JSON has native booleans and `null`.
- All timestamps are ISO 8601 UTC with `Z`. Dates are `YYYY-MM-DD`.

## Dashboard Use

### Available Flights

Filter `flights.is_bookable == true`. Then filter route, departure date and `available_seats >= requested party size`. Current price is `current_fare_usd`.

### Booking Preview

Show schedule, origin/destination timezone, price and remaining seats. Use `bookings` and `booking_passengers` to show groups, seats and payments.

### Change-Flight Preview

Start with `bookings.flight_id`, select another bookable same-route flight with enough seats, and show fare type, fees and the `flight_changes` examples.

| Fare type | Change fee   |
| --------- | ------------ |
| Basic     | $60/person   |
| Standard  | $25/person   |
| Flexible  | $0/person    |

### Operational Dashboard

**Passengers and status**

- Flight status values: `scheduled`, `delayed`, `boarding`, `in_air`, `arrived`, `canceled`.
- Booked passengers: current manifests, including airline-canceled reservations.
- Every flight manifest has 60–200 people, limited by its assigned aircraft.
- Active/confirmed passengers and boarded passengers are zero for canceled flights. Future flights have zero boarded passengers. Crew are excluded.
- Confirmed passengers are active booked tickets, regardless of check-in.
- A departed flight's passengers are all boarded in this simplified model.
- For historical actual traffic, count `transported_passengers`, not all bookings.

**Delays and operations**

- Departure delay threshold: `>= 15` minutes. Small delays can exist without meeting that threshold.
- Arrival on-time threshold: `< 15` minutes.
- Future delayed-flight counts contain only already announced delays.
- Aircraft round trips and minimum 45-minute turnarounds are enforced.
- Cancellation of a rotation cancels both legs to preserve aircraft location.

**Sales and refunds**

- Canceled tickets are fully refunded immediately in this model.
- Gross sales include net change adjustments; net sales subtract refunds.
- Negative fare differences credit the customer.
- The data models successful payments only.
- Sales in `daily_metrics` are attributed to **current flight departure dates**, not the booking date and not formal accounting revenue recognition.
- For sales by transaction date, use `bookings` plus `flight_changes`, and assign refund transactions to `canceled_at_utc` on the current flight.

**Aggregation**

- Flight metrics group by origin **local** departure date. Maintenance starts and costs group by UTC start date. Week/month boundaries follow those dates.
- For weekly/monthly punctuality, divide `SUM(on_time_arrivals)` by `SUM(arrived_flights)`; do not average the daily percentages. Return null when the denominator is zero.
- For load factor, divide confirmed passengers by `active_seat_capacity`; exclude canceled flights from the denominator.

## Model Limits

This generates a consistent snapshot for a dashboard or application demo. It does not implement a booking API, live inventory, authentication or payments. Reservations, flight changes and seat allocations are examples of state and history your application can display. Actual booking writes require a backend that atomically checks capacity and updates the linked records.

The fictional US airline uses six fixed daily round trips, economy cabins and synthetic fares.

- **Includes:** group travel, some children, baggage, loyalty, season-neutral weekday demand, reduced advance loads, disruptions, maintenance and voluntary changes.
- **Omits:** connecting itineraries, crew rosters, infants, no-shows, customer-initiated cancellations and automated reaccommodation.

Canceled flights retain their canceled passenger manifests for impact analysis. Canceled aircraft remain at home; paired legs cancel together. All travelers use invented identities and reserved `example.com` email addresses.

### Date Window

The **flight departure** window is limited to 60 dates. Intentionally, some records fall outside it; otherwise the first/last day's operational records would be incomplete:

- Booking/audit timestamps can precede the first departure date by up to 30 days.
- A flight or maintenance interval can finish after the last departure date.
- New bookings and changed departures are at most 30 days ahead of their transaction.
- Currently bookable departures are also within one calendar month of the snapshot date.
- No future actual departure, arrival or booking is emitted.

## Validation

Every generation validates foreign keys, unique IDs/seats, party counts, capacity limits, booking/change horizons, financial totals, aircraft continuity, turnaround and maintenance overlap before writing files.

Run the additional test suite from this directory:

```sh
python3.12 -m unittest discover -s . -p 'test_*.py' -v
```

Tests cover multiple random seeds, leap years, month/year boundaries, daylight saving transitions, single-day and 60-day windows, reproducibility, changes, overbooking rejection and exact JSON/CSV export agreement.
