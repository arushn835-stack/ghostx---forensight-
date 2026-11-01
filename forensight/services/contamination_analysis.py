def analyze_handling_events(events):
    warnings = []

    def add_warning(rule, explanation, related_events=()):
        related_events = list(related_events)
        statuses = {event.review_status for event in related_events}
        if statuses == {"Resolved"}:
            review_status = "Resolved"
        elif statuses and statuses <= {"Reviewed", "Resolved"}:
            review_status = "Reviewed"
        else:
            review_status = "Needs review"
        warnings.append({
            "rule": rule,
            "explanation": explanation,
            "related_event_ids": [event.id for event in related_events],
            "review_status": review_status,
        })

    if not events:
        add_warning("TG-001", "No handling events are recorded for this evidence item.")
        return warnings

    if not any(event.action == "Collected" for event in events):
        add_warning("TG-002", "No collection event is recorded.", events)
    for event in events:
        if event.event_timestamp is None:
            add_warning("TG-003", "The recorded event is missing its event timestamp.", [event])
        if event.action == "Transferred" and not event.new_custodian.strip():
            add_warning("TG-004", "A transfer is recorded without a recipient/new custodian.", [event])
        if event.action in {"Collected", "Packaged"} and not event.packaging_information.strip():
            add_warning("TG-005", f"The {event.action.lower()} event has no packaging details recorded.", [event])
        if event.action == "Examined" and not event.equipment_information.strip():
            add_warning("TG-008", "An examination event has no equipment information recorded.", [event])

    dated_events = [event for event in events if event.event_timestamp]
    for earlier, later in zip(dated_events, dated_events[1:]):
        if later.event_timestamp < earlier.event_timestamp:
            add_warning("TG-006", "Recorded event timestamps are not in chronological order.", [earlier, later])
        if (earlier.new_custodian and later.previous_custodian
                and earlier.new_custodian.casefold() != later.previous_custodian.casefold()):
            add_warning("TG-007", "Adjacent recorded custodian fields do not match.", [earlier, later])
    return warnings