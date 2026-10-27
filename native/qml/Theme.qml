pragma Singleton
import QtQuick

// The console's four palettes (frontend/styles.css), so the machine's own
// screen and the browser look like one product. The signed-in person's
// choice (Settings → Appearance in the console) is applied once known.
QtObject {
    id: t
    property string palette: "terminal"
    property bool light: false
    // Every size in the app is multiplied by this (set from the window size).
    property real s: 1.0

    readonly property var palettes: ({
        terminal: {
            dark:  { bg: "#030805", panel: "#081a10", panel2: "#061309", border: "#173a24", borderStrong: "#357a4f",
                     text: "#d6ffe2", bright: "#baffcf", muted: "#5f9973", accent: "#39ff88", accentDim: "#23a05a",
                     onAccent: "#04170b", amber: "#ffb020", red: "#ff3b3b", teal: "#2dd4bf",
                     event: "#c94dff", source: "#2dd4ff", vehicle: "#ff9a3c", record: "#e2cf9c",
                     onDanger: "#1a0303", scrim: "#99000000" },
            light: { bg: "#f2f5f2", panel: "#ffffff", panel2: "#e9ede9", border: "#b6c2b9", borderStrong: "#6b8072",
                     text: "#111a14", bright: "#000000", muted: "#44564b", accent: "#0a5c2c", accentDim: "#0a5c2c",
                     onAccent: "#ffffff", amber: "#7a4d00", red: "#a01810", teal: "#0a5f57",
                     event: "#6b21a8", source: "#0e5a86", vehicle: "#8a4400", record: "#6e5418",
                     onDanger: "#ffffff", scrim: "#73111a14" },
            ui: "mono", radius: 5 },
        slate: {
            dark:  { bg: "#0f1419", panel: "#161c23", panel2: "#10151b", border: "#2a3441", borderStrong: "#5d6c7c",
                     text: "#dfe5ec", bright: "#ffffff", muted: "#96a2b1", accent: "#6ba4f8", accentDim: "#2f6fd0",
                     onAccent: "#ffffff", amber: "#f0a028", red: "#f2685f", teal: "#2dd4bf",
                     event: "#b49bfb", source: "#4cb8f0", vehicle: "#f0a868", record: "#e2cf9c",
                     onDanger: "#1a0303", scrim: "#9e04080c" },
            light: { bg: "#f6f8fa", panel: "#ffffff", panel2: "#eef1f5", border: "#d0d7de", borderStrong: "#7d8791",
                     text: "#1c2128", bright: "#000000", muted: "#57606a", accent: "#0b5cad", accentDim: "#0b5cad",
                     onAccent: "#ffffff", amber: "#8a5500", red: "#b3261e", teal: "#0f766e",
                     event: "#6d28d9", source: "#0369a1", vehicle: "#9a4a00", record: "#6e5418",
                     onDanger: "#ffffff", scrim: "#731b1f24" },
            ui: "sans", radius: 8 },
        graphite: {
            dark:  { bg: "#16181a", panel: "#1e2124", panel2: "#191c1f", border: "#34383d", borderStrong: "#656b71",
                     text: "#e4e6e8", bright: "#ffffff", muted: "#9aa0a6", accent: "#d9a066", accentDim: "#8f5c28",
                     onAccent: "#ffffff", amber: "#d8a13c", red: "#e88178", teal: "#5cb8b0",
                     event: "#b79ae0", source: "#6db6e0", vehicle: "#dda06a", record: "#e2cf9c",
                     onDanger: "#1a0303", scrim: "#a808090a" },
            light: { bg: "#f4f3f1", panel: "#ffffff", panel2: "#eceae6", border: "#c5c1bb", borderStrong: "#85807a",
                     text: "#1b1a18", bright: "#000000", muted: "#5a5650", accent: "#8a5a22", accentDim: "#8a5a22",
                     onAccent: "#ffffff", amber: "#7a5410", red: "#a3241a", teal: "#16615c",
                     event: "#5b3a9e", source: "#10527e", vehicle: "#8a5220", record: "#6e5418",
                     onDanger: "#ffffff", scrim: "#731c1a18" },
            ui: "grotesk", radius: 3 },
        archive: {
            dark:  { bg: "#17150f", panel: "#201d16", panel2: "#1a1812", border: "#3a352b", borderStrong: "#6f6857",
                     text: "#ece7db", bright: "#ffffff", muted: "#a49b8c", accent: "#e09292", accentDim: "#9a3f3f",
                     onAccent: "#ffffff", amber: "#d9a94e", red: "#e88179", teal: "#5cb0a6",
                     event: "#bfa0e2", source: "#7fb6d8", vehicle: "#d6a679", record: "#e2cf9c",
                     onDanger: "#1a0303", scrim: "#a30c0a07" },
            light: { bg: "#faf8f4", panel: "#ffffff", panel2: "#f2efe8", border: "#d5cec1", borderStrong: "#867e6d",
                     text: "#1a1714", bright: "#000000", muted: "#5d564c", accent: "#7a2e2e", accentDim: "#7a2e2e",
                     onAccent: "#ffffff", amber: "#7a5210", red: "#9b2222", teal: "#1f5f57",
                     event: "#5c3a86", source: "#1a4f7a", vehicle: "#7d5324", record: "#6e5418",
                     onDanger: "#ffffff", scrim: "#73282218" },
            ui: "sans", radius: 3 }
    })
    readonly property var p: (palettes[palette] || palettes.terminal)
    readonly property var c: p[light ? "light" : "dark"]

    readonly property color bg: c.bg
    readonly property color panel: c.panel
    readonly property color panel2: c.panel2
    readonly property color border: c.border
    readonly property color borderStrong: c.borderStrong
    readonly property color text: c.text
    readonly property color bright: c.bright
    readonly property color muted: c.muted
    readonly property color accent: c.accent
    readonly property color accentDim: c.accentDim
    readonly property color onAccent: c.onAccent
    readonly property color amber: c.amber
    readonly property color red: c.red
    readonly property color teal: c.teal
    readonly property color onDanger: c.onDanger
    readonly property color scrim: c.scrim
    // Record kinds, as the console colours them.
    function kindColor(kind) {
        return ({ person: c.accent, organization: c.teal, location: c.amber, event: c.event,
                  source: c.source, vehicle: c.vehicle, record: c.record })[kind] || c.muted
    }

    readonly property string mono: "IBM Plex Mono, DejaVu Sans Mono, monospace"
    readonly property string sans: "Inter, Noto Sans, DejaVu Sans, sans-serif"
    readonly property string serif: "Newsreader, Noto Serif, DejaVu Serif, serif"
    readonly property string ui: p.ui === "mono" ? "IBM Plex Mono"
                               : p.ui === "grotesk" ? "Schibsted Grotesk" : "Inter"
    readonly property string prose: palette === "archive" ? "Newsreader" : "Inter"
    readonly property bool caps: palette === "terminal"
    readonly property real radius: p.radius * s

    // Type scale
    readonly property real fs: 15 * s
    readonly property real fsSmall: 12.5 * s
    readonly property real fsLabel: 11.5 * s
    readonly property real fsTitle: 20 * s
    readonly property real fsHuge: 34 * s
    readonly property real gap: 12 * s
    readonly property real pad: 16 * s
    readonly property real touch: 44 * s      // smallest comfortable tap target
}
