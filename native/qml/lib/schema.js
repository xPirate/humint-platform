.pragma library
// What each kind of record holds, as the console has it (frontend/app.js
// DETAIL_FIELDS and the option lists, which must match api/entities.py).

var ALIGNMENT_OPTIONS = ["", "Friendly", "Neutral", "Unknown", "Hostile"]
var ENVIRONMENT_OPTIONS = ["", "Permissive", "Semi-permissive", "Non-permissive", "Denied", "Unknown"]
var TRAVEL_MODE_OPTIONS = ["", "On foot", "Vehicle", "Bicycle", "Boat", "Aircraft", "Other"]
var COMMUNICATION_MEDIUM_OPTIONS = ["", "Cellphone", "Landline", "Text/SMS", "Satellite Phone", "Email",
    "HF Radio", "VHF Radio", "UHF Radio", "FM Radio", "GMRS", "FRS", "CB Radio",
    "In-Person", "Mail/Courier", "Other"]
var VEHICLE_STYLE_OPTIONS = ["", "Sedan", "Coupe", "Hatchback", "SUV", "Pickup truck", "Van", "Panel van",
    "Box truck", "Semi-tractor", "Bus", "Motorcycle", "ATV/UTV", "Trailer", "Boat", "Aircraft", "Other"]
var COMMUNICATION_MEDIUM_DETAIL_LABELS = {
    "Cellphone": "Phone number", "Landline": "Phone number", "Text/SMS": "Phone number",
    "Satellite Phone": "Phone number", "Email": "Email address",
    "HF Radio": "Frequency (MHz)", "VHF Radio": "Frequency (MHz)", "UHF Radio": "Frequency (MHz)",
    "FM Radio": "Frequency (MHz)", "GMRS": "Channel", "FRS": "Channel", "CB Radio": "Channel",
    "In-Person": "Location", "Mail/Courier": "Address", "Other": "Details" }
var GEOMETRY_TYPES = ["zone", "route"]
var CONTACTABLE_TYPES = ["person", "organization", "location"]
var CONTACT_KINDS = ["Phone", "Mobile", "Email", "Address", "Radio", "Messaging", "Social", "Website", "Other"]
var CONFIDENCE_SCALE = [["1", "Confirmed"], ["2", "Probably true"], ["3", "Possibly true"],
                        ["4", "Doubtful"], ["5", "Improbable"], ["6", "Cannot be judged"]]
var MONO_FIELDS = ["license_plate", "lat", "lng", "medium_detail", "maidenhead_grid", "date_of_birth"]

var ALIGNMENT_FIELD = { key: "alignment", label: "Alignment", type: "select", options: ALIGNMENT_OPTIONS,
    hint: "Your assessment. For a named group, create it as an Organization and link people to it." }

var DETAIL_FIELDS = {
    person: [
        { key: "aliases", label: "Aliases (comma-separated)", type: "text-list" },
        { key: "date_of_birth", label: "Date of birth", type: "date" },
        ALIGNMENT_FIELD,
        { key: "occupation", label: "Occupation", type: "text" },
        { key: "physical_description", label: "Physical description", type: "textarea" },
        { key: "life_status", label: "Status", type: "select", options: ["", "Living", "Deceased", "Unknown"] },
        { key: "disposition", label: "Disposition", type: "select",
          options: ["", "At liberty", "Captured", "Detained", "Evading", "Missing"] }
    ],
    organization: [
        { key: "org_type", label: "Org type", type: "text" },
        { key: "founded_date", label: "Founded date", type: "date" },
        { key: "website", label: "Website", type: "text" },
        ALIGNMENT_FIELD
    ],
    location: [
        { key: "address", label: "Address", type: "text" },
        { key: "environment", label: "Environment", type: "select", options: ENVIRONMENT_OPTIONS,
          hint: "How freely you could operate here. Denied means no access at all." },
        { key: "lat", label: "Latitude", type: "number", clearable: true },
        { key: "lng", label: "Longitude", type: "number", clearable: true }
    ],
    event: [
        { key: "event_type", label: "Event type", type: "text" },
        { key: "started_at", label: "Started at", type: "datetime" },
        { key: "ended_at", label: "Ended at", type: "datetime" },
        { key: "expires_at", label: "Relevant until", type: "date", clearable: true,
          hint: "When this stops being current, not when it ended. Blank for no expiry." }
    ],
    source: [
        { key: "source_type", label: "Source type", type: "text" },
        { key: "reliability_rating", label: "Reliability (Admiralty A–F)", type: "select", options: ["", "A", "B", "C", "D", "E", "F"] },
        { key: "handling_notes", label: "Handling notes", type: "textarea" },
        ALIGNMENT_FIELD
    ],
    communication: [
        { key: "medium", label: "Medium", type: "select", options: COMMUNICATION_MEDIUM_OPTIONS },
        { key: "medium_detail", label: "Detail", type: "text" },
        { key: "occurred_at", label: "Occurred at", type: "datetime" },
        { key: "participants_note", label: "Participants note", type: "textarea" }
    ],
    vehicle: [
        { key: "make", label: "Make", type: "text" },
        { key: "model", label: "Model", type: "text" },
        { key: "color", label: "Colour", type: "text" },
        { key: "license_plate", label: "Licence plate", type: "text", hint: "As your source wrote it." },
        { key: "plate_region", label: "Plate issued by", type: "text", hint: "State, province or country." },
        ALIGNMENT_FIELD,
        { key: "style", label: "Style", type: "select", options: VEHICLE_STYLE_OPTIONS },
        { key: "notes", label: "Notes", type: "textarea", hint: "Damage, markings, equipment, who drives it." }
    ],
    zone: [],
    route: [
        { key: "environment", label: "How workable", type: "select", options: ENVIRONMENT_OPTIONS,
          hint: "Sets the route's colour on the map. Blank means nobody has assessed it." },
        { key: "travel_mode", label: "Travelled by", type: "select", options: TRAVEL_MODE_OPTIONS }
    ],
    record: [
        { key: "record_kind", label: "Kind", type: "text", placeholder: "Letter, bank statement, registration…" },
        { key: "record_date", label: "Date on the document", type: "date", clearable: true },
        { key: "issued_by", label: "Issued by", type: "text" },
        { key: "body", label: "Full text", type: "textarea", rows: 14 }
    ]
}

// [label, value] rows to show for a record's details.
function detailRows(type, details) {
    details = details || {}
    var out = []
    var fields = DETAIL_FIELDS[type] || []
    for (var i = 0; i < fields.length; i++) {
        var f = fields[i], v = details[f.key]
        if (v === null || v === undefined || v === "") continue
        if (v && typeof v === "object" && v.length !== undefined) v = Array.prototype.join.call(v, ", ")
        var label = f.label.replace(" (comma-separated)", "")
        if (type === "communication" && f.key === "medium_detail") label = COMMUNICATION_MEDIUM_DETAIL_LABELS[details.medium] || f.label
        out.push({ label: label, value: String(v), mono: MONO_FIELDS.indexOf(f.key) >= 0, key: f.key })
    }
    if (type === "location" && details.maidenhead_grid)
        out.push({ label: "Maidenhead grid", value: details.maidenhead_grid, mono: true, key: "maidenhead_grid" })
    return out
}

// Person status and expiry, as the console's list badges.
function badges(e) {
    var b = []
    var d = e.details || e
    if (d.life_status && d.life_status !== "Living") b.push(d.life_status)
    if (d.disposition && d.disposition !== "At liberty") b.push(d.disposition)
    if (e.entity_type === "event" && e.is_expired) b.push("expired")
    if (e.retention_hold) b.push("held")
    else if (e.retention_due_at) b.push("due to archive")
    return b
}

function relWording(r) { return (r.reads_as || r.relationship_type || "").replace(/_/g, " ") }

function confidenceLabel(c) {
    for (var i = 0; i < CONFIDENCE_SCALE.length; i++) if (CONFIDENCE_SCALE[i][0] === String(c)) return CONFIDENCE_SCALE[i][1]
    return c || ""
}
