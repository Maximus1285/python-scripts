#!/usr/bin/env python3
"""Generate linked, synthetic airline dashboard data. Python 3.12.10; stdlib only."""

from __future__ import annotations

import argparse
import calendar
import csv
import json
import math
import random
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

UTC = timezone.utc
AIRPORTS = [
    ("JFK", "John F. Kennedy International", "New York", "America/New_York", 40.6413, -73.7781),
    ("MIA", "Miami International", "Miami", "America/New_York", 25.7959, -80.2870),
    ("LAX", "Los Angeles International", "Los Angeles", "America/Los_Angeles", 33.9416, -118.4085),
    ("SFO", "San Francisco International", "San Francisco", "America/Los_Angeles", 37.6213, -122.3790),
    ("ORD", "O'Hare International", "Chicago", "America/Chicago", 41.9742, -87.9073),
    ("ATL", "Hartsfield-Jackson Atlanta International", "Atlanta", "America/New_York", 33.6407, -84.4277),
    ("DFW", "Dallas Fort Worth International", "Dallas", "America/Chicago", 32.8998, -97.0403),
    ("DEN", "Denver International", "Denver", "America/Denver", 39.8561, -104.6737),
    ("SEA", "Seattle-Tacoma International", "Seattle", "America/Los_Angeles", 47.4502, -122.3088),
    ("LAS", "Harry Reid International", "Las Vegas", "America/Los_Angeles", 36.0840, -115.1537),
    ("BOS", "Logan International", "Boston", "America/New_York", 42.3656, -71.0096),
    ("DCA", "Ronald Reagan Washington National", "Washington", "America/New_York", 38.8512, -77.0402),
]
# Home, destination, realistic block minutes, seats, aircraft model, base one-way fare.
ROTATIONS = [
    ("JFK", "MIA", 185, 180, "Airbus A320", 210),
    ("LAX", "SFO", 90, 150, "Airbus A319", 110),
    ("ORD", "ATL", 125, 174, "Boeing 737-800", 155),
    ("DFW", "DEN", 130, 186, "Boeing 737-800", 150),
    ("SEA", "LAS", 155, 200, "Airbus A321", 170),
    ("BOS", "DCA", 105, 160, "Airbus A320", 140),
]
FIRST_NAMES = "Alex Jordan Taylor Morgan Casey Jamie Riley Avery Cameron Robin Sam Drew Quinn Blake Charlie Jesse Skyler Dakota Hayden Parker Sofia Emma Olivia Mia Isabella Amelia Chloe Zoe Maya Elena Lucas Noah Liam Ethan Mateo Daniel Leo Gabriel Adrian Oliver".split()
LAST_NAMES = "Smith Johnson Williams Brown Jones Garcia Miller Davis Rodriguez Martinez Hernandez Lopez Wilson Anderson Thomas Taylor Moore Jackson Martin Lee Perez Thompson White Harris Sanchez Clark Ramirez Lewis Robinson Walker Young Allen King Wright Scott Torres Nguyen Hill Flores Green Adams Nelson Baker Hall Rivera Campbell Mitchell Carter Roberts".split()


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def next_month(value: date) -> date:
    year, month = (value.year + 1, 1) if value.month == 12 else (value.year, value.month + 1)
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def money(value: float) -> float:
    return round(value + 1e-9, 2)


def booking_window_start(departure: datetime) -> datetime:
    """Respect both a 30-day limit and shorter calendar months."""
    earliest = departure - timedelta(days=30)
    while next_month(earliest.date()) < departure.date():
        earliest += timedelta(days=1)
    return earliest


def distance_km(a: tuple, b: tuple) -> int:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[4], a[5], b[4], b[5]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return round(6371 * 2 * math.asin(math.sqrt(h)))


def generate(as_of: datetime, history_days: int, future_days: int, seed: int,
             rotations: int = 6, change_rate: float = 0.04) -> tuple[dict, dict]:
    rng = random.Random(seed)
    start = as_of.date() - timedelta(days=history_days)
    end = as_of.date() + timedelta(days=future_days)
    tables = {name: [] for name in (
        "airports", "aircraft", "routes", "flights", "passengers", "bookings",
        "booking_passengers", "flight_changes", "maintenance", "flight_events", "daily_metrics")}
    airport_map = {a[0]: a for a in AIRPORTS}
    for a in AIRPORTS:
        tables["airports"].append(dict(zip(
            ("airport_code", "name", "city", "timezone", "latitude", "longitude"), a),
            country_code="US"))

    def event(flight: dict, kind: str, timestamp: datetime, description: str) -> None:
        if timestamp <= as_of:
            tables["flight_events"].append({
                "event_id": f"EV{len(tables['flight_events']) + 1:07d}",
                "flight_id": flight["flight_id"], "event_type": kind,
                "event_at_utc": iso(timestamp), "description": description})

    for i, (home, away, block, capacity, model, base_fare) in enumerate(ROTATIONS[:rotations]):
        aircraft_id = f"AC{i + 1:03d}"
        tables["aircraft"].append({
            "aircraft_id": aircraft_id, "registration": f"N{710 + i}SF", "model": model,
            "seat_capacity": capacity, "home_airport_code": home,
            "manufacture_year": rng.randint(2015, 2023), "status_as_of": "available",
            "location_airport_code": home})
        route_ids = []
        for origin, destination in ((home, away), (away, home)):
            route_id = f"{origin}-{destination}"
            route_ids.append(route_id)
            tables["routes"].append({
                "route_id": route_id, "origin_airport_code": origin,
                "destination_airport_code": destination,
                "distance_km": distance_km(airport_map[origin], airport_map[destination]),
                "scheduled_block_minutes": block, "base_fare_usd": base_fare})
        for day_offset in range((end - start).days + 1):
            day = start + timedelta(days=day_offset)
            local_departure = datetime.combine(day, time(7 + i % 3, 15 * (i % 4)), ZoneInfo(airport_map[home][3]))
            departure = local_departure.astimezone(UTC)
            # Both legs are canceled together, so an aircraft never teleports after a cancellation.
            known = departure - timedelta(hours=18) <= as_of
            canceled = known and rng.random() < 0.035
            cause = rng.choices(["weather", "maintenance", "crew"], [0.45, 0.35, 0.2])[0] if canceled else ""
            cancellation_at = min(departure - timedelta(hours=2), as_of) if canceled else None
            prior_arrival = None
            last_arrival = None
            last_operating_arrival = None
            for leg, (origin, destination) in enumerate(((home, away), (away, home))):
                scheduled_departure = departure + timedelta(minutes=leg * (block + 90))
                scheduled_arrival = scheduled_departure + timedelta(minutes=block)
                delay = 0
                delay_reason = ""
                if not canceled and scheduled_departure <= as_of + timedelta(hours=6):
                    if rng.random() < 0.24:
                        delay = rng.choices([rng.randint(5, 14), rng.randint(15, 60), rng.randint(61, 150)], [0.25, 0.6, 0.15])[0]
                        delay_reason = rng.choices(["weather", "air_traffic_control", "crew", "ground_handling"], [0.4, 0.3, 0.1, 0.2])[0]
                    if prior_arrival:
                        inherited = max(0, int((prior_arrival + timedelta(minutes=45) - scheduled_departure).total_seconds() / 60))
                        if inherited > delay:
                            delay, delay_reason = inherited, "late_inbound_aircraft"
                estimated_departure = scheduled_departure + timedelta(minutes=delay)
                estimated_arrival = estimated_departure + timedelta(minutes=block + (rng.randint(-8, 8) if delay else 0))
                actual_dep = estimated_departure if not canceled and estimated_departure <= as_of else None
                actual_arr = estimated_arrival if not canceled and estimated_arrival <= as_of else None
                if canceled:
                    status = "canceled"
                elif actual_arr:
                    status = "arrived"
                elif actual_dep:
                    status = "in_air"
                elif estimated_departure - timedelta(minutes=35) <= as_of:
                    status = "boarding"
                elif delay:
                    status = "delayed"
                else:
                    status = "scheduled"
                flight_id = f"FL{day:%Y%m%d}{i + 1:02d}{leg + 1}"
                flight = {
                    "flight_id": flight_id, "flight_number": f"SF{100 + i * 2 + leg}",
                    "airline_code": "SF", "airline_name": "Synthetic Skies", "route_id": route_ids[leg],
                    "aircraft_id": aircraft_id, "service_date": day.isoformat(),
                    "departure_local_date": scheduled_departure.astimezone(ZoneInfo(airport_map[origin][3])).date().isoformat(),
                    "origin_airport_code": origin, "destination_airport_code": destination,
                    "scheduled_departure_utc": iso(scheduled_departure), "scheduled_arrival_utc": iso(scheduled_arrival),
                    "estimated_departure_utc": None if canceled else iso(estimated_departure),
                    "estimated_arrival_utc": None if canceled else iso(estimated_arrival),
                    "actual_departure_utc": iso(actual_dep) if actual_dep else None,
                    "actual_arrival_utc": iso(actual_arr) if actual_arr else None,
                    "status": status, "departure_delay_minutes": None if canceled else delay,
                    "arrival_delay_minutes": max(0, int((actual_arr - scheduled_arrival).total_seconds() / 60)) if actual_arr else None,
                    "delay_reason": delay_reason or None, "cancellation_reason": cause or None,
                    "canceled_at_utc": iso(cancellation_at) if canceled else None,
                    "terminal": str(rng.randint(1, 4)), "gate": f"{rng.choice('ABC')}{rng.randint(1, 24)}",
                    "seat_capacity": capacity, "booked_passengers": 0, "confirmed_passengers": 0,
                    "boarded_passengers": 0, "available_seats": 0, "load_factor_pct": 0.0,
                    "is_bookable": False, "booking_cutoff_utc": iso(scheduled_departure - timedelta(hours=2)),
                    "current_fare_usd": money(base_fare * rng.uniform(0.85, 1.55)),
                    "gross_sales_usd": 0.0, "refunds_usd": 0.0, "net_sales_usd": 0.0,
                }
                tables["flights"].append(flight)
                if canceled:
                    event(flight, "canceled", cancellation_at, f"Flight canceled: {cause}")
                else:
                    if delay:
                        event(flight, "delay_announced", min(scheduled_departure - timedelta(hours=3), as_of), delay_reason)
                    if actual_dep:
                        event(flight, "departed", actual_dep, "Aircraft departed")
                    if actual_arr:
                        event(flight, "arrived", actual_arr, "Aircraft arrived")
                    prior_arrival = estimated_arrival
                    last_operating_arrival = estimated_arrival
                last_arrival = scheduled_arrival
            if canceled and cause == "maintenance":
                maintenance_start = departure - timedelta(hours=3)
                maintenance_end = last_arrival + timedelta(minutes=45)
                tables["maintenance"].append({
                    "maintenance_id": f"MX{len(tables['maintenance']) + 1:05d}",
                    "aircraft_id": aircraft_id, "airport_code": home, "maintenance_type": "unscheduled_repair",
                    "description": rng.choice(["Hydraulic system repair", "Avionics fault investigation", "Brake assembly replacement"]),
                    "start_utc": iso(maintenance_start), "end_utc": iso(maintenance_end),
                    "status": "completed" if maintenance_end <= as_of else "in_progress" if maintenance_start <= as_of else "scheduled",
                    "cost_usd": rng.randint(80, 300) * 100, "affected_flight_count": 2})
            elif day_offset % 7 == i % 7:
                maintenance_start = max(last_arrival, last_operating_arrival or last_arrival) + timedelta(hours=1)
                maintenance_end = maintenance_start + timedelta(hours=3)
                tables["maintenance"].append({
                    "maintenance_id": f"MX{len(tables['maintenance']) + 1:05d}",
                    "aircraft_id": aircraft_id, "airport_code": home, "maintenance_type": "scheduled_inspection",
                    "description": "Routine overnight line maintenance",
                    "start_utc": iso(maintenance_start), "end_utc": iso(maintenance_end),
                    "status": "completed" if maintenance_end <= as_of else "in_progress" if maintenance_start <= as_of else "scheduled",
                    "cost_usd": rng.randint(8, 30) * 100, "affected_flight_count": 0})

    flights = sorted(tables["flights"], key=lambda f: f["scheduled_departure_utc"])
    tables["flights"] = flights
    by_id = {f["flight_id"]: f for f in flights}
    booking_members = defaultdict(list)
    flight_bookings = defaultdict(list)
    for flight in flights:
        departure = dt(flight["scheduled_departure_utc"])
        days_ahead = max(0, (departure - as_of).total_seconds() / 86400)
        occupancy = rng.uniform(0.70, 0.96) - 0.007 * days_ahead
        if departure.weekday() in (4, 6):
            occupancy += 0.035
        target = max(60, min(flight["seat_capacity"], round(flight["seat_capacity"] * occupancy)))
        remaining = target
        while remaining:
            party = min(remaining, rng.choices([1, 2, 3, 4, 5], [0.50, 0.30, 0.10, 0.07, 0.03])[0])
            remaining -= party
            booking_id = f"BK{len(tables['bookings']) + 1:07d}"
            latest = min(as_of, departure - timedelta(hours=3))
            if flight["canceled_at_utc"]:
                latest = min(latest, dt(flight["canceled_at_utc"]) - timedelta(hours=1))
            # Every booking was made at most 30 days before its original flight.
            earliest = booking_window_start(departure)
            created = earliest + (latest - earliest) * rng.betavariate(1.7, 1.4)
            fare_type = rng.choices(["basic", "standard", "flexible"], [0.28, 0.55, 0.17])[0]
            unit_fare = money(flight["current_fare_usd"] * {"basic": 0.82, "standard": 1.0, "flexible": 1.35}[fare_type] * rng.uniform(0.8, 1.1))
            original_total = money(unit_fare * party)
            booking = {
                "booking_id": booking_id, "booking_reference": f"S{len(tables['bookings']) + 1:06X}",
                "original_flight_id": flight["flight_id"], "flight_id": flight["flight_id"],
                "booked_at_utc": iso(created), "updated_at_utc": iso(created),
                "party_size": party, "fare_type": fare_type, "currency": "USD",
                "booking_channel": rng.choices(["website", "mobile_app", "travel_agent", "call_center"], [0.42, 0.38, 0.15, 0.05])[0],
                "status": "confirmed", "original_amount_usd": original_total,
                "change_adjustments_usd": 0.0, "total_paid_usd": original_total,
                "refunded_amount_usd": 0.0, "net_amount_usd": original_total,
                "payment_status": "paid", "lead_passenger_id": None,
            }
            tables["bookings"].append(booking)
            flight_bookings[flight["flight_id"]].append(booking)
            for member in range(party):
                passenger_id = f"PX{len(tables['passengers']) + 1:07d}"
                # A child always travels with at least one adult in the same reservation.
                age = rng.randint(5, 15) if member > 0 and rng.random() < 0.22 else rng.randint(18, 82)
                birth_year = as_of.year - age
                birth_month = rng.randint(1, 12)
                birth_day = rng.randint(1, calendar.monthrange(birth_year, birth_month)[1])
                first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
                tables["passengers"].append({
                    "passenger_id": passenger_id, "first_name": first, "last_name": last,
                    "date_of_birth": date(birth_year, birth_month, birth_day).isoformat(),
                    "email": f"{first.lower()}.{last.lower()}.{passenger_id.lower()}@example.com",
                    "loyalty_tier": rng.choices(["none", "silver", "gold", "platinum"], [0.65, 0.20, 0.11, 0.04])[0],
                })
                ticket = {
                    "ticket_id": f"TK{len(tables['booking_passengers']) + 1:08d}",
                    "booking_id": booking_id, "passenger_id": passenger_id,
                    "flight_id": flight["flight_id"], "seat_number": None, "cabin": "economy",
                    "checked_bags": rng.choices([0, 1, 2], [0.45, 0.47, 0.08])[0],
                    "requires_assistance": rng.random() < 0.025,
                    "check_in_status": "not_open", "checked_in_at_utc": None,
                    "boarded_at_utc": None,
                }
                tables["booking_passengers"].append(ticket)
                booking_members[booking_id].append(ticket)
                if member == 0:
                    booking["lead_passenger_id"] = passenger_id
            flight["booked_passengers"] += party

    # Move existing reservations between same-route future flights; preserve group integrity.
    by_route = defaultdict(list)
    for flight in flights:
        if flight["status"] != "canceled" and dt(flight["booking_cutoff_utc"]) > as_of:
            by_route[flight["route_id"]].append(flight)
    for booking in tables["bookings"]:
        source = by_id[booking["flight_id"]]
        if (source["status"] == "canceled" or dt(source["booking_cutoff_utc"]) <= as_of
                or rng.random() >= change_rate or source["booked_passengers"] - booking["party_size"] < 60):
            continue
        candidates = [f for f in by_route[source["route_id"]]
                      if f is not source
                      and abs((dt(f["scheduled_departure_utc"]) - dt(source["scheduled_departure_utc"])).days) <= 7
                      and f["booked_passengers"] + booking["party_size"] <= f["seat_capacity"]]
        if not candidates:
            continue
        destination = rng.choice(candidates)
        change_at = dt(booking["booked_at_utc"]) + (as_of - dt(booking["booked_at_utc"])) * rng.uniform(0.2, 1.0)
        # The new departure must also fall within a month of the change transaction.
        earliest_change = booking_window_start(dt(destination["scheduled_departure_utc"]))
        change_at = max(change_at, earliest_change)
        if change_at > as_of:
            continue
        fee = 0 if booking["fare_type"] == "flexible" else (60 if booking["fare_type"] == "basic" else 25) * booking["party_size"]
        difference = money(booking["original_amount_usd"] * rng.uniform(-0.12, 0.25))
        adjustment = money(fee + difference)
        tables["flight_changes"].append({
            "change_id": f"CH{len(tables['flight_changes']) + 1:06d}", "booking_id": booking["booking_id"],
            "from_flight_id": source["flight_id"], "to_flight_id": destination["flight_id"],
            "changed_at_utc": iso(change_at), "passenger_count": booking["party_size"],
            "reason": rng.choice(["schedule_preference", "business_plans_changed", "personal_plans_changed"]),
            "change_fee_usd": fee, "fare_difference_usd": difference, "total_adjustment_usd": adjustment})
        event(source, "booking_changed_out", change_at, f"Reservation {booking['booking_id']} moved to {destination['flight_id']}")
        event(destination, "booking_changed_in", change_at, f"Reservation {booking['booking_id']} moved from {source['flight_id']}")
        booking.update(flight_id=destination["flight_id"], updated_at_utc=iso(change_at),
                       change_adjustments_usd=adjustment, total_paid_usd=money(booking["original_amount_usd"] + adjustment),
                       net_amount_usd=money(booking["original_amount_usd"] + adjustment))
        for ticket in booking_members[booking["booking_id"]]:
            ticket["flight_id"] = destination["flight_id"]
        flight_bookings[source["flight_id"]].remove(booking)
        flight_bookings[destination["flight_id"]].append(booking)
        source["booked_passengers"] -= booking["party_size"]
        destination["booked_passengers"] += booking["party_size"]

    for flight in flights:
        canceled = flight["status"] == "canceled"
        departure = dt(flight["estimated_departure_utc"]) if not canceled else None
        seat_index = 0
        for booking in flight_bookings[flight["flight_id"]]:
            if canceled:
                booking.update(status="canceled_by_airline", payment_status="refunded",
                               refunded_amount_usd=booking["total_paid_usd"], net_amount_usd=0.0,
                               updated_at_utc=flight["canceled_at_utc"])
            elif flight["actual_arrival_utc"]:
                booking["status"] = "completed"
            for ticket in booking_members[booking["booking_id"]]:
                ticket["seat_number"] = f"{seat_index // 6 + 1}{'ABCDEF'[seat_index % 6]}"
                seat_index += 1
                if canceled:
                    ticket["check_in_status"] = "canceled"
                elif departure - timedelta(hours=24) <= as_of:
                    check_in_at = departure - timedelta(minutes=rng.randint(60, 24 * 60))
                    if check_in_at <= as_of:
                        ticket["check_in_status"] = "checked_in"
                        ticket["checked_in_at_utc"] = iso(check_in_at)
                    boarding_at = departure - timedelta(minutes=rng.randint(10, 30))
                    if boarding_at <= as_of:
                        # Guarantee the recorded check-in predates boarding.
                        ticket["checked_in_at_utc"] = iso(min(check_in_at, boarding_at - timedelta(minutes=10)))
                        ticket["check_in_status"] = "boarded"
                        ticket["boarded_at_utc"] = iso(boarding_at)
                        flight["boarded_passengers"] += 1
                    elif not ticket["checked_in_at_utc"]:
                        ticket["check_in_status"] = "open"
            event(by_id[booking["original_flight_id"]], "booking_created", dt(booking["booked_at_utc"]), f"Reservation {booking['booking_id']}")
        flight["confirmed_passengers"] = 0 if canceled else flight["booked_passengers"]
        flight["available_seats"] = 0 if canceled else flight["seat_capacity"] - flight["confirmed_passengers"]
        flight["load_factor_pct"] = money(100 * flight["confirmed_passengers"] / flight["seat_capacity"])
        flight["is_bookable"] = (not canceled and as_of < dt(flight["booking_cutoff_utc"])
                                 and flight["available_seats"] > 0
                                 and dt(flight["scheduled_departure_utc"]).date() <= next_month(as_of.date()))
        flight["gross_sales_usd"] = money(sum(b["total_paid_usd"] for b in flight_bookings[flight["flight_id"]]))
        flight["refunds_usd"] = money(sum(b["refunded_amount_usd"] for b in flight_bookings[flight["flight_id"]]))
        flight["net_sales_usd"] = money(flight["gross_sales_usd"] - flight["refunds_usd"])

    # Current fleet location is derived from actual movements, with maintenance taking precedence.
    for aircraft in tables["aircraft"]:
        for flight in flights:
            if flight["aircraft_id"] != aircraft["aircraft_id"]:
                continue
            if flight["actual_arrival_utc"]:
                aircraft["location_airport_code"] = flight["destination_airport_code"]
            elif flight["status"] == "in_air":
                aircraft["status_as_of"] = "in_air"
                aircraft["location_airport_code"] = None
        if any(m["aircraft_id"] == aircraft["aircraft_id"] and m["status"] == "in_progress" for m in tables["maintenance"]):
            aircraft["status_as_of"] = "maintenance"

    # Every date is present, even if its operational counts are zero.
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        rows = [f for f in flights if f["departure_local_date"] == day.isoformat()]
        departed = [f for f in rows if f["actual_departure_utc"]]
        arrived = [f for f in rows if f["status"] == "arrived"]
        on_time = sum(f["arrival_delay_minutes"] < 15 for f in arrived)
        tables["daily_metrics"].append({
            "date": day.isoformat(), "week_start_date": (day - timedelta(days=day.weekday())).isoformat(),
            "iso_year": day.isocalendar().year, "iso_week": day.isocalendar().week,
            "month": day.strftime("%Y-%m"), "total_flights": len(rows),
            "departed_flights": len(departed), "arrived_flights": len(arrived),
            "canceled_flights": sum(f["status"] == "canceled" for f in rows),
            "delayed_flights": sum((f["departure_delay_minutes"] or 0) >= 15 for f in rows),
            "available_flights": sum(f["is_bookable"] for f in rows),
            "booked_passengers": sum(f["booked_passengers"] for f in rows),
            "confirmed_passengers": sum(f["confirmed_passengers"] for f in rows),
            "transported_passengers": sum(f["boarded_passengers"] for f in departed),
            "available_seats": sum(f["available_seats"] for f in rows if f["is_bookable"]),
            "active_seat_capacity": sum(f["seat_capacity"] for f in rows if f["status"] != "canceled"),
            "on_time_arrivals": on_time, "on_time_arrival_pct": money(100 * on_time / len(arrived)) if arrived else None,
            "gross_sales_usd": money(sum(f["gross_sales_usd"] for f in rows)),
            "refunds_usd": money(sum(f["refunds_usd"] for f in rows)),
            "net_sales_usd": money(sum(f["net_sales_usd"] for f in rows)),
            "maintenance_starts": sum(m["start_utc"][:10] == day.isoformat() for m in tables["maintenance"]),
            "maintenance_cost_usd": sum(m["cost_usd"] for m in tables["maintenance"] if m["start_utc"][:10] == day.isoformat()),
        })
    tables["flight_events"].sort(key=lambda e: (e["event_at_utc"], e["event_id"]))
    metadata = {
        "schema_version": "1.0.0", "generator": "generate_flights.py", "python_target": "3.12.10",
        "synthetic": True, "seed": seed, "as_of_utc": iso(as_of),
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "calendar_days": (end - start).days + 1,
        "booking_horizon_end_date": next_month(as_of.date()).isoformat(),
        "currency": "USD", "timestamp_timezone": "UTC",
        "table_row_counts": {name: len(rows) for name, rows in tables.items()},
        "definitions": {
            "booked_passengers": "Current manifest including reservations canceled by airline; 60 to aircraft capacity per flight.",
            "confirmed_passengers": "Active manifest; zero for canceled flights.",
            "delayed_flights": "Known departure delay >= 15 minutes, including arrived flights.",
            "on_time_arrival": "Actual arrival delay < 15 minutes; denominator is arrived flights only.",
            "net_sales_usd": "Ticket sales plus change adjustments minus refunds, attributed to current flight departure date; not accounting revenue recognition.",
            "available_seats": "Physical unsold seats; use is_bookable for tickets that can be sold at snapshot time.",
            "date_grouping": "Flight metrics use origin local departure date; maintenance metrics use UTC start date.",
        },
    }
    return metadata, tables


def validate(metadata: dict, tables: dict) -> None:
    """Validate relationships, inventory, money, timing and operational consistency."""
    def require(condition: bool, message: str) -> None:
        if not condition:
            raise ValueError(f"Dataset validation failed: {message}")

    snapshot = dt(metadata["as_of_utc"])
    flights = {f["flight_id"]: f for f in tables["flights"]}
    bookings = {b["booking_id"]: b for b in tables["bookings"]}
    passengers = {p["passenger_id"] for p in tables["passengers"]}
    aircraft = {a["aircraft_id"]: a for a in tables["aircraft"]}
    routes = {r["route_id"]: r for r in tables["routes"]}
    airports = {a["airport_code"] for a in tables["airports"]}
    require(1 <= metadata["calendar_days"] <= 60, "maximum 60 calendar days")
    require(date.fromisoformat(metadata["end_date"]) <= next_month(snapshot.date()), "future horizon exceeds one month")
    for table, key in (("flights", "flight_id"), ("bookings", "booking_id"), ("passengers", "passenger_id"),
                       ("booking_passengers", "ticket_id"), ("flight_events", "event_id"),
                       ("flight_changes", "change_id"), ("maintenance", "maintenance_id")):
        require(len({r[key] for r in tables[table]}) == len(tables[table]), f"duplicate {key}")
    ticket_counts = Counter()
    seats = set()
    for ticket in tables["booking_passengers"]:
        require(ticket["booking_id"] in bookings and ticket["passenger_id"] in passengers, "ticket relationship")
        require(ticket["flight_id"] == bookings[ticket["booking_id"]]["flight_id"], "ticket flight")
        ticket_counts[ticket["booking_id"]] += 1
        seat = (ticket["flight_id"], ticket["seat_number"])
        require(seat not in seats, "seat assigned twice")
        seats.add(seat)
        for field in ("checked_in_at_utc", "boarded_at_utc"):
            require(ticket[field] is None or dt(ticket[field]) <= snapshot, f"future {field}")
        if ticket["boarded_at_utc"]:
            require(dt(ticket["checked_in_at_utc"]) <= dt(ticket["boarded_at_utc"]), "boarding before check-in")
    manifests = Counter()
    gross = defaultdict(float)
    refunds = defaultdict(float)
    for booking in bookings.values():
        require(booking["flight_id"] in flights and booking["original_flight_id"] in flights, "booking flight")
        require(ticket_counts[booking["booking_id"]] == booking["party_size"], "booking party count")
        require(booking["lead_passenger_id"] in passengers, "lead passenger")
        booked_at = dt(booking["booked_at_utc"])
        original_dep = dt(flights[booking["original_flight_id"]]["scheduled_departure_utc"])
        require(booked_at <= dt(booking["updated_at_utc"]) <= snapshot, "booking snapshot timing")
        require(timedelta(0) < original_dep - booked_at <= timedelta(days=30, seconds=1), "booking lead time")
        require(original_dep.date() <= next_month(booked_at.date()), "booking calendar month horizon")
        require(abs(booking["total_paid_usd"] - booking["original_amount_usd"] - booking["change_adjustments_usd"]) < 0.011, "booking payment")
        require(abs(booking["net_amount_usd"] - booking["total_paid_usd"] + booking["refunded_amount_usd"]) < 0.011, "booking refund")
        manifests[booking["flight_id"]] += booking["party_size"]
        gross[booking["flight_id"]] += booking["total_paid_usd"]
        refunds[booking["flight_id"]] += booking["refunded_amount_usd"]
    for flight in flights.values():
        fid = flight["flight_id"]
        require(flight["aircraft_id"] in aircraft and flight["route_id"] in routes, "flight relationship")
        require(flight["origin_airport_code"] in airports and flight["destination_airport_code"] in airports, "flight airport")
        require(60 <= manifests[fid] == flight["booked_passengers"] <= flight["seat_capacity"] <= 200, "flight load")
        require(abs(gross[fid] - flight["gross_sales_usd"]) < 0.011 and abs(refunds[fid] - flight["refunds_usd"]) < 0.011, "flight financial totals")
        require(dt(flight["scheduled_departure_utc"]) < dt(flight["scheduled_arrival_utc"]), "flight duration")
        for field in ("actual_departure_utc", "actual_arrival_utc", "canceled_at_utc"):
            require(flight[field] is None or dt(flight[field]) <= snapshot, "future actual event")
        if flight["status"] == "canceled":
            require(flight["confirmed_passengers"] == flight["boarded_passengers"] == flight["available_seats"] == 0, "canceled inventory")
            require(flight["actual_departure_utc"] is None and flight["net_sales_usd"] == 0, "canceled flight activity")
        else:
            require(flight["available_seats"] + flight["confirmed_passengers"] == flight["seat_capacity"], "seat inventory")
    for change in tables["flight_changes"]:
        source, target = flights[change["from_flight_id"]], flights[change["to_flight_id"]]
        require(source["route_id"] == target["route_id"], "change route")
        require(change["booking_id"] in bookings, "change booking")
        changed_at = dt(change["changed_at_utc"])
        require(changed_at <= snapshot < dt(source["booking_cutoff_utc"]), "change timing")
        require(timedelta(0) < dt(target["scheduled_departure_utc"]) - changed_at <= timedelta(days=30, seconds=1), "changed flight horizon")
        require(dt(target["scheduled_departure_utc"]).date() <= next_month(changed_at.date()), "change calendar month horizon")
    for event in tables["flight_events"]:
        require(event["flight_id"] in flights and dt(event["event_at_utc"]) <= snapshot, "event relationship or time")
    for plane_id in aircraft:
        movements = sorted((f for f in flights.values() if f["aircraft_id"] == plane_id and f["status"] != "canceled"), key=lambda f: f["estimated_departure_utc"])
        for previous, following in zip(movements, movements[1:]):
            require(dt(following["estimated_departure_utc"]) - dt(previous["estimated_arrival_utc"]) >= timedelta(minutes=45), "aircraft turnaround")
            require(previous["destination_airport_code"] == following["origin_airport_code"], "aircraft location continuity")
        for maintenance in (m for m in tables["maintenance"] if m["aircraft_id"] == plane_id):
            require(dt(maintenance["start_utc"]) < dt(maintenance["end_utc"]), "maintenance duration")
            for flight in movements:
                require(dt(flight["estimated_arrival_utc"]) <= dt(maintenance["start_utc"])
                        or dt(flight["estimated_departure_utc"]) >= dt(maintenance["end_utc"]), "maintenance overlaps operating flight")
    require(sum(r["total_flights"] for r in tables["daily_metrics"]) == len(flights), "daily flight totals")
    require(sum(r["booked_passengers"] for r in tables["daily_metrics"]) == len(tables["booking_passengers"]), "daily passenger totals")


def write_data(output: Path, metadata: dict, tables: dict) -> None:
    output.mkdir(parents=True, exist_ok=True)
    csv_dir = output / "csv"
    csv_dir.mkdir(exist_ok=True)
    with (output / "dataset.json").open("w", encoding="utf-8") as handle:
        json.dump({"metadata": metadata, **tables}, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    for name, rows in tables.items():
        # Field order for optional empty tables is still documented by a header.
        empty_headers = {
            "flight_changes": "change_id booking_id from_flight_id to_flight_id changed_at_utc passenger_count reason change_fee_usd fare_difference_usd total_adjustment_usd".split(),
            "maintenance": "maintenance_id aircraft_id airport_code maintenance_type description start_utc end_utc status cost_usd affected_flight_count".split(),
        }
        headers = list(rows[0]) if rows else empty_headers.get(name, [])
        with (csv_dir / f"{name}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: (str(value).lower() if isinstance(value, bool) else value) for key, value in row.items()})
    with (output / "metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, allow_nan=False)
        handle.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--as-of", default=None, help="Snapshot ISO timestamp with timezone, e.g. 2026-11-12T12:00:00Z; defaults to now in UTC")
    parser.add_argument("--history-days", type=int, default=30, help="Days before snapshot UTC date")
    parser.add_argument("--future-days", type=int, default=28, help="Days after snapshot UTC date, at most one calendar month")
    parser.add_argument("--rotations", type=int, default=6, help="Aircraft operating one round trip per day (1 to 6)")
    parser.add_argument("--change-rate", type=float, default=0.04, help="Probability of changing an eligible future booking (0 to 1)")
    parser.add_argument("--seed", type=int, default=42, help="Repeatable random seed; also fix --as-of for exact reproduction")
    parser.add_argument("--output", type=Path, default=Path("flight_data"), help="Output directory; existing generated filenames are replaced")
    args = parser.parse_args()
    try:
        as_of = dt(args.as_of) if args.as_of else datetime.now(UTC)
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("--as-of must include a timezone offset or Z")
        as_of = as_of.astimezone(UTC).replace(microsecond=0)
        if args.history_days < 0 or args.future_days < 0 or args.history_days + args.future_days + 1 > 60:
            raise ValueError("history-days + future-days + 1 must be between 1 and 60")
        if as_of.date() + timedelta(days=args.future_days) > next_month(as_of.date()):
            raise ValueError("future-days must not extend beyond one calendar month from --as-of")
        if not 1 <= args.rotations <= 6 or not 0 <= args.change_rate <= 1:
            raise ValueError("rotations must be 1 to 6 and change-rate must be 0 to 1")
    except ValueError as exc:
        parser.error(str(exc))
    metadata, tables = generate(as_of, args.history_days, args.future_days, args.seed, args.rotations, args.change_rate)
    validate(metadata, tables)
    write_data(args.output, metadata, tables)
    print(f"Validated dataset: {metadata['start_date']} through {metadata['end_date']} ({metadata['calendar_days']} days)")
    for name, rows in tables.items():
        print(f"  {name}: {len(rows):,} rows")
    print(f"JSON and CSV saved to: {args.output.resolve()}")


if __name__ == "__main__":
    main()
