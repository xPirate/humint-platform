import QtQuick
import QtQuick.Controls
import Humint
import ".."

// Join a Wi-Fi network — for internet before deployment (offline map areas,
// the system's updates). The networks in range, or a name typed (a hidden
// one), and its password. humint-boxd checks both and hands them to
// humint-ctl net client; the machine serves the console on that network
// until switched back to the hotspot.
FormDialog {
    id: wd
    title: "Join a Wi-Fi network"
    okText: "Join"
    property var networks: []
    property bool scanning: false
    property bool hasWifi: true
    property bool fromHotspot: false
    property bool secure: true

    function scan() {
        scanning = true
        Net.box("wifi_scan", {}).then(function(r) {
            scanning = false
            hasWifi = r.wifi
            fromHotspot = !!r.hotspot
            networks = r.networks || []
        }).catch(function(e) { scanning = false; error = e.message })
    }
    function pick(n) {
        ssid.text = n.ssid
        secure = n.secure
        psk.text = ""
        if (secure) psk.forceActiveFocus()
    }

    onOpened: { ssid.text = ""; psk.text = ""; showPsk.checked = false; secure = true; networks = []; scan() }
    onAccepted: {
        var name = ssid.text, pw = psk.text
        if (!name) { error = "Choose a network, or type its name"; return }
        if (pw && (pw.length < 8 || pw.length > 64)) { error = "A Wi-Fi password is 8 to 63 characters"; return }
        error = ""
        busy = true
        ui.busy("Joining “" + name + "”…")
        Net.box("wifi_join", { ssid: name, psk: pw }).then(function(r) {
            busy = false
            ui.busy("")
            if (r.rc === 0) {
                close()
                ui.toast("Joined “" + name + "”")
            } else if (r.rc === 3) {
                error = "Could not join: " + (r.fallback || "no answer") + ". The wrong password is the usual cause. "
                      + "For now it is on the wired network."
            } else {
                error = r.error || ("Could not join (" + r.rc + ")")
            }
        }).catch(function(e) { busy = false; ui.busy(""); error = e.message })
    }

    Txt { width: parent.width; kind: "muted"; wrapMode: Text.Wrap
          text: "For internet before deploying — to download map areas or the system's updates. "
              + "The hotspot stops while joined; switch back with Actions → Hotspot." }

    Txt { width: parent.width; visible: !wd.hasWifi; color: Theme.amber; wrapMode: Text.Wrap
          text: "This machine has no Wi-Fi. Plug in an Ethernet cable instead." }

    Column {
        width: parent.width; spacing: 6 * Theme.s
        visible: wd.hasWifi
        Row {
            width: parent.width; spacing: Theme.gap
            Txt { kind: "label"; text: "Networks in range"; anchors.verticalCenter: parent.verticalCenter }
            Btn { compact: true; text: wd.scanning ? "Looking…" : "Look again"; enabled: !wd.scanning
                  onClicked: wd.scan() }
        }
        Txt { width: parent.width; kind: "muted"; wrapMode: Text.Wrap
              visible: wd.scanning || wd.networks.length === 0
              text: wd.scanning
                    ? (Box.state && Box.state.net_mode === "hotspot"
                       ? "Looking — the hotspot pauses for a few seconds to listen, then comes back." : "Looking…")
                    : "None seen. Type the network's name below (a hidden one too)." }
        Repeater {
            model: wd.networks.slice(0, 10)
            Btn {
                width: parent.width
                text: modelData.ssid
                sub: (modelData.in_use ? "connected · " : "") + (modelData.secure ? "password · " : "open · ")
                     + (modelData.signal >= 70 ? "strong" : modelData.signal >= 40 ? "good" : "weak")
                kind: ssid.text === modelData.ssid ? "primary" : "normal"
                onClicked: wd.pick(modelData)
            }
        }
    }

    Labeled { label: "Network name"; visible: wd.hasWifi
              Field { id: ssid; width: parent.width; placeholderText: "the Wi-Fi's name, exactly"
                      onTextEdited: wd.secure = true } }
    Labeled { label: "Password"; visible: wd.hasWifi && wd.secure
              hint: "Leave empty for an open network."
              Field { id: psk; width: parent.width
                      echoMode: showPsk.checked ? TextInput.Normal : TextInput.Password
                      onAccepted: wd.accepted() } }
    Check { id: showPsk; visible: wd.hasWifi && wd.secure; text: "Show password" }
}
