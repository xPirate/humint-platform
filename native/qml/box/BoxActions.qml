import QtQuick
import QtQuick.Layouts
import Humint
import ".."

// The Pi panel's menu: the destructive ones behind a confirmation (the wipe
// behind two).
Item {
  id: acts
  readonly property var st: Box.state || ({})
  readonly property bool hot: st.net_mode === "hotspot"
  component Act: Btn {
      Layout.fillWidth: true
      Layout.preferredHeight: 92 * Theme.s
  }
  GridLayout {
    width: acts.width
    columns: width > 900 * Theme.s ? 4 : 3
    columnSpacing: Theme.gap; rowSpacing: Theme.gap

    Act { text: "Lock case file"; sub: "stop the console, close the store"; kind: "danger"
          onClicked: ui.confirm("Lock the case file?", "The console stops for everyone and the PIN is needed to open it again.",
                                function() { box.ctl("Locking", "lock", []) }) }
    Act { text: "Restart console"; sub: "API and worker"
          onClicked: box.ctl("Restarting console", "restart", []) }
    Act { text: hot ? "Wired network" : "Hotspot"; sub: hot ? "switch to Ethernet" : "be the access point"
          onClicked: ui.confirm("Switch network?",
                                hot ? "Devices on the field Wi-Fi will lose the console." : "This machine becomes the Wi-Fi access point again.",
                                function() { box.ctl("Switching network", "net", [hot ? "wired" : "hotspot"]) }, false) }
    Act { text: "Update from USB"; sub: "a signed update bundle"
          onClicked: ui.confirm("Update from the USB stick?",
                                "The console restarts on the new version; if it does not come back, it is put back as it was.",
                                function() { box.ctl("Updating", "update", ["usb"], "Updated") }, false) }
    Act { text: "Duress PIN"; sub: st.duress_set ? "set · change it" : "erases if typed at unlock"
          onClicked: {
              // humint-ctl asks for it on this screen (the set-PIN screen takes over).
              Net.box("ctl", { action: "duress", args: ["set", "--panel"] }).then(function(r) {
                  ui.toast(({ 0: "Duress PIN set", 1: "Duress PIN not changed",
                              3: "That's the real PIN — choose another",
                              4: "Too short — at least 4 characters" })[r.rc] || "Duress PIN: failed (" + r.rc + ")", r.rc > 1)
              })
          } }
    Act { text: "Clear duress PIN"; sub: "turn it off"; visible: !!st.duress_set
          onClicked: ui.confirm("Clear the duress PIN?", "", function() { box.ctl("Clearing duress PIN", "duress", ["clear"]) }, false) }
    Act { text: "New login"; sub: "password for SSH, keyboard"
          onClicked: ui.confirm("New login password?", "The old one stops working. The new one is shown here once.",
                                function() { box.ctl("New login password", "login-password", []) }, false) }
    Act { text: "Restart machine"; sub: "asks for the PIN again"; kind: "danger"
          onClicked: ui.confirm("Restart the machine?", "The case file locks; the PIN opens it again.",
                                function() { ui.busy("Restarting…"); Net.box("ctl", { action: "reboot", args: [] }) }) }
    Act { text: "Shut down"; sub: "safe to unplug after"; kind: "danger"
          onClicked: ui.confirm("Shut down?", "Wait for the screen to go dark before unplugging.",
                                function() { ui.busy("Shutting down…"); Net.box("ctl", { action: "shutdown", args: [] }) }) }
    Act { text: "Wipe case file"; sub: "erase everything, for good"; kind: "danger"
          onClicked: ui.confirm("Wipe the case file?",
                                "Every record, report and file on this machine is destroyed. It restarts into setup.",
                                function() {
                                    ui.confirm("This cannot be undone.", "Copies on USB sticks or other devices are not touched.",
                                               function() { box.ctl("Wiping", "wipe", ["--yes"]) }, true, "Wipe")
                                }) }
  }
}
