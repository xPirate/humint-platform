import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// Outside events: the sources, how often they are asked, and what is kept
// (api/outside_events.py; the pulling is worker/outside_events.py). Nothing is
// fetched until a source is on here and a zone is marked on the map.
Rectangle {
    id: page
    color: Theme.bg
    property var s: null
    property bool saving: false
    property var codes: []          // chosen CAMEO roots

    function load() {
        Net.get("/api/admin/outside-events/settings").then(function(r) { page.apply(r) })
            .catch(function(e) { ui.toast(e.message, true) })
    }
    function apply(r) {
        page.s = r
        gOn.checked = r.gdelt_enabled
        gInterval.text = String(r.gdelt_interval_minutes); gSpacing.text = String(r.gdelt_request_spacing_seconds)
        gBackfill.text = String(r.gdelt_backfill_hours); gMin.text = String(r.gdelt_min_sources)
        gCity.checked = r.gdelt_city_only
        page.codes = r.gdelt_root_codes || []
        aOn.checked = r.acled_enabled
        aUser.text = r.acled_username || ""; aPass.text = ""
        aInterval.text = String(r.acled_interval_minutes); aSpacing.text = String(r.acled_request_spacing_seconds)
        aBackfill.text = String(r.acled_backfill_days)
        keep.text = String(r.retention_days)
    }
    Component.onCompleted: load()

    function save(extra) {
        var body = {
            gdelt_enabled: gOn.checked, gdelt_interval_minutes: parseInt(gInterval.text, 10),
            gdelt_request_spacing_seconds: parseFloat(gSpacing.text), gdelt_backfill_hours: parseInt(gBackfill.text, 10),
            gdelt_min_sources: parseInt(gMin.text, 10), gdelt_city_only: gCity.checked, gdelt_root_codes: page.codes,
            acled_enabled: aOn.checked, acled_username: aUser.text.trim(),
            acled_interval_minutes: parseInt(aInterval.text, 10), acled_request_spacing_seconds: parseFloat(aSpacing.text),
            acled_backfill_days: parseInt(aBackfill.text, 10), retention_days: parseInt(keep.text, 10)
        }
        if (aPass.text) body.acled_password = aPass.text
        for (var k in (extra || {})) body[k] = extra[k]
        page.saving = true
        Net.put("/api/admin/outside-events/settings", body).then(function(r) {
            page.saving = false; page.apply(r); ui.toast("Saved")
        }).catch(function(e) { page.saving = false; ui.toast(e.message, true) })
    }
    function lim(k) { return page.s && page.s.limits ? page.s.limits[k] : { min: 0, max: 0 } }
    function when(iso) { return iso ? Fmt.relativeTime(iso) : "never" }

    Flickable {
        anchors.fill: parent; anchors.margins: Theme.pad
        contentHeight: col.implicitHeight; clip: true
        ColumnLayout {
            id: col
            width: parent.width
            spacing: Theme.gap
            PageHeader {
                Layout.fillWidth: true; title: "Outside events"
                subtitle: "Open-source events inside the zones marked as areas of responsibility, pulled whenever this server has internet."
                Btn { compact: true; text: "Pull now"; enabled: !!page.s && (page.s.gdelt_enabled || page.s.acled_enabled)
                      onClicked: Net.post("/api/admin/outside-events/pull-now", {}).then(function(r) {
                          page.apply(r); ui.toast("Asked for at once — the spacing between requests still applies")
                      }).catch(function(e) { ui.toast(e.message, true) }) }
            }
            Card {
                Layout.fillWidth: true; title: "Areas"
                implicitHeight: areas.implicitHeight + 2 * padding + Theme.gap + 20 * Theme.s
                Column {
                    id: areas
                    width: parent.width; spacing: 4 * Theme.s
                    Txt { width: parent.width; visible: !!page.s && page.s.zones.length === 0; kind: "muted"
                          text: "None yet. On the map, draw or edit a zone and tick “Pull outside events for this area”." }
                    Repeater {
                        model: page.s ? page.s.zones : []
                        Txt { width: areas.width; text: modelData.name + (modelData.expired ? " (expired: not pulled)" : "") }
                    }
                }
            }

            // ---- GDELT ----
            Card {
                Layout.fillWidth: true; title: "GDELT"
                implicitHeight: gCol.implicitHeight + 2 * padding + Theme.gap + 20 * Theme.s
                ColumnLayout {
                    id: gCol
                    width: parent.width; spacing: 8 * Theme.s
                    Txt { Layout.fillWidth: true; kind: "muted"
                          text: "The world's news coded into events, published every 15 minutes. Free, no account. Its terms: any use, citing GDELT and linking to gdeltproject.org (the Outside events page does)." }
                    Check { id: gOn; text: "Pull events from GDELT" }
                    RowLayout {
                        Layout.fillWidth: true; spacing: Theme.gap
                        Labeled { Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop; label: "Check every (minutes)"
                                  hint: "At least " + page.lim("gdelt_interval_minutes").min + ": GDELT publishes every 15 minutes."
                                  Field { id: gInterval; width: parent.width; inputMethodHints: Qt.ImhDigitsOnly } }
                        Labeled { Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop; label: "Between requests (seconds)"
                                  hint: "At least " + page.lim("gdelt_request_spacing_seconds").min + ": GDELT's limit."
                                  Field { id: gSpacing; width: parent.width; inputMethodHints: Qt.ImhFormattedNumbersOnly } }
                        Labeled { Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop; label: "Fill in after time offline (hours)"
                                  hint: "Up to " + page.lim("gdelt_backfill_hours").max + "; a day is 96 small files."
                                  Field { id: gBackfill; width: parent.width; inputMethodHints: Qt.ImhDigitsOnly } }
                    }
                    Btn { compact: true; text: "Fastest GDELT allows (15 min, 5 s)"
                          onClicked: { gInterval.text = "15"; gSpacing.text = "5" } }
                    Txt { kind: "label"; text: "Event types kept" }
                    Flow {
                        Layout.fillWidth: true; spacing: 6 * Theme.s
                        Repeater {
                            model: page.s ? page.s.root_code_choices : []
                            Btn { compact: true; minWidth: 0
                                  text: modelData.code + " " + modelData.label
                                  kind: page.codes.indexOf(modelData.code) >= 0 ? "primary" : "normal"
                                  onClicked: {
                                      var c = page.codes.slice(), i = c.indexOf(modelData.code)
                                      if (i >= 0) c.splice(i, 1); else c.push(modelData.code)
                                      page.codes = c
                                  } }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true; spacing: Theme.gap
                        Labeled { Layout.preferredWidth: 260 * Theme.s; label: "Reported by at least (sources)"
                                  hint: "Higher cuts noise, and misses the first reports."
                                  Field { id: gMin; width: parent.width; inputMethodHints: Qt.ImhDigitsOnly } }
                        Check { id: gCity; text: "Only events placed at a city or finer"
                                Layout.alignment: Qt.AlignVCenter }
                    }
                    Txt { Layout.fillWidth: true; kind: "muted"; visible: !!page.s
                          text: page.s ? "Last checked " + page.when(page.s.gdelt_last_poll_at)
                                         + (page.s.gdelt_last_file ? " · read up to the file of " + page.s.gdelt_last_file.replace(/(\d{4})(\d\d)(\d\d)(\d\d)(\d\d)\d\d/, "$1-$2-$3 $4:$5 UTC") : "")
                                         + " · " + ((page.s.counts.gdelt || {}).total || 0) + " kept" : "" }
                    Txt { Layout.fillWidth: true; visible: !!page.s && !!page.s.gdelt_last_error; color: Theme.amber
                          text: page.s && page.s.gdelt_last_error ? "Last attempt: " + page.s.gdelt_last_error : "" }
                }
            }

            // ---- ACLED ----
            Card {
                Layout.fillWidth: true; title: "ACLED"
                implicitHeight: aCol.implicitHeight + 2 * padding + Theme.gap + 20 * Theme.s
                ColumnLayout {
                    id: aCol
                    width: parent.width; spacing: 8 * Theme.s
                    Txt { Layout.fillWidth: true; kind: "muted"
                          text: "Hand-coded political violence and protest. Needs a myACLED account whose access level includes the API (Research and up; a personal email gets Open, which has none). Its licence decides what may be kept — turning it on confirms yours allows it. ACLED updates weekly." }
                    Check { id: aOn; text: "Pull events from ACLED" }
                    RowLayout {
                        Layout.fillWidth: true; spacing: Theme.gap
                        Labeled { Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop; label: "myACLED email"
                                  Field { id: aUser; width: parent.width } }
                        Labeled { Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop; label: "Password"
                                  hint: page.s && page.s.acled_password_set ? "Set. Type a new one to change it." : "Kept on this server; never shown again."
                                  Field { id: aPass; width: parent.width; echoMode: TextInput.Password } }
                    }
                    RowLayout {
                        Layout.fillWidth: true; spacing: Theme.gap
                        Labeled { Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop; label: "Check every (minutes)"; hint: "At least " + page.lim("acled_interval_minutes").min + "."
                                  Field { id: aInterval; width: parent.width; inputMethodHints: Qt.ImhDigitsOnly } }
                        Labeled { Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop; label: "Between requests (seconds)"; hint: "At least " + page.lim("acled_request_spacing_seconds").min + "."
                                  Field { id: aSpacing; width: parent.width; inputMethodHints: Qt.ImhFormattedNumbersOnly } }
                        Labeled { Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop; label: "First pull reaches back (days)"
                                  Field { id: aBackfill; width: parent.width; inputMethodHints: Qt.ImhDigitsOnly } }
                    }
                    Txt { Layout.fillWidth: true; kind: "muted"; visible: !!page.s
                          text: page.s ? "Last checked " + page.when(page.s.acled_last_poll_at) + " · " + ((page.s.counts.acled || {}).total || 0) + " kept" : "" }
                    Txt { Layout.fillWidth: true; visible: !!page.s && !!page.s.acled_last_error; color: Theme.amber
                          text: page.s && page.s.acled_last_error ? "Last attempt: " + page.s.acled_last_error : "" }
                }
            }

            Card {
                Layout.fillWidth: true; title: "Keeping them"
                implicitHeight: kCol.implicitHeight + 2 * padding + Theme.gap + 20 * Theme.s
                ColumnLayout {
                    id: kCol
                    width: parent.width
                    Labeled { Layout.preferredWidth: 300 * Theme.s; label: "Delete unread and dismissed after (days)"
                              hint: "Ones sent to Documents stay: the document is the record."
                              Field { id: keep; width: parent.width; inputMethodHints: Qt.ImhDigitsOnly } }
                }
            }
            RowLayout {
                spacing: Theme.gap
                Btn { kind: "primary"; text: page.saving ? "Saving…" : "Save"; enabled: !page.saving && !!page.s; onClicked: page.save() }
                Btn { text: "Fastest the terms allow"; enabled: !page.saving && !!page.s
                      onClicked: page.save({ fastest: true }) }
            }
            Item { Layout.preferredHeight: Theme.pad }
        }
    }
}
