import SwiftUI
import AppKit

struct ExistingSetupView: View {
    @EnvironmentObject var model: AppModel
    let status: BridgeStatus
    var body: some View {
        Card(title: status.usesExistingSetup ? "Connected to your existing bridge" : "Your existing bridge is ready") {
            if status.usesExistingSetup {
                Text("Your reader settings remain in place. This app shows the highlights collected by your existing Reading Highlights service.")
                Label(status.service.healthy ? "Collector online" : "Collector offline · check the existing service, then refresh", systemImage: status.service.healthy ? "checkmark.circle.fill" : "exclamationmark.triangle")
                Text("Uploads from your Kindle and X4 Pro continue using their saved connection. Reading-progress sync stays configured on the readers.").font(.callout).foregroundStyle(.secondary)
                HStack {
                    Button("View highlights") { model.selection = .highlights }.buttonStyle(.borderedProminent)
                    Button("Refresh connection") { Task { await model.perform("status") } }.disabled(model.busy)
                }
            } else {
                Text("A verified Reading Highlights service is already running on this Mac. Connect to it to see your archive and keep using your readers’ saved settings.")
                Button("Use existing setup") { Task { await model.perform("connect_existing", activity: "Connecting to your existing bridge…", success: "Connected. Your readers can keep syncing with their existing settings.") } }.buttonStyle(.borderedProminent).disabled(model.busy)
            }
            if let existing = status.existingSetup {
                Text("Collector port: \(existing.port)").font(.caption).foregroundStyle(.secondary)
                if !existing.archive.isEmpty { Text("GitHub backup: \(existing.archive)").font(.caption).textSelection(.enabled) }
            }
        }
    }
}
struct SetupView: View {
    @EnvironmentObject var model: AppModel
    let status: BridgeStatus
    @State private var endpoint = ""
    @State private var portText = "8084"
    @State private var lastSuggestedEndpoint = ""
    @State private var kindleMount = ""
    @State private var xteinkMount = ""
    @State private var deviceURL = ""
    @State private var method = "SD card"
    @State private var confirmed = false
    @State private var firmware = false
    var selectedEndpoint: String { endpoint.isEmpty ? status.endpoint : endpoint }
    var validPort: Bool { Int(portText).map { (1024...65535).contains($0) } ?? false }
    var body: some View {
        Group {
        if status.usesExistingSetup || status.offersExistingSetup {
            ExistingSetupView(status: status)
        } else {
        Text(status.setupStep == 5 ? "All four steps confirmed." : "Step \(status.setupStep) of 4 · your progress is saved on this Mac.").foregroundStyle(.secondary)
        Card(title: "1. Start your local bridge") {
            Text("Your readers and Mac must share a reachable network. The bridge is unavailable while your Mac sleeps.").foregroundStyle(.secondary)
            HStack { Label(status.service.healthy ? "Collector online" : "Collector offline", systemImage: status.service.healthy ? "checkmark.circle.fill" : "circle"); Spacer(); action(status.service.healthy ? "Stop collector" : "Start collector", status.service.healthy ? "stop_collector" : "start_collector", ["port": Int(portText) ?? 8084], "Updating collector…", disabled: !status.service.healthy && !validPort, success: status.service.healthy ? "Collector stopped." : "Collector started. Connect your Kindle by USB to continue.") }
            HStack { Text("Collector port"); TextField("8084", text: $portText).frame(width: 100).textFieldStyle(.roundedBorder).disabled(status.service.healthy); Text("1024–65535").font(.caption).foregroundStyle(.secondary) }
            if !validPort { Text("Choose a port from 1024 to 65535.").font(.caption).foregroundStyle(.orange) }
            TextField("Reader endpoint", text: $endpoint).textFieldStyle(.roundedBorder)
            if !status.addresses.isEmpty { Menu("Choose a Mac address") { ForEach(status.addresses, id: \.self) { address in Button(address) { endpoint = address } } } }
            Text("Use a stable LAN address that both readers can reach. An override is used when pairing below.").font(.caption).foregroundStyle(.secondary)
        }
        Card(title: "2. Pair your Kindle") {
            Text("First jailbreak a supported Kindle and install KOReader. Reader Bridge cannot do those steps for you.")
            HStack { Link("Check Kindle model", destination: URL(string: "https://kindlemodding.org/kindle-models")!); Link("Jailbreak guide", destination: URL(string: "https://kindlemodding.org/jailbreaking/")!); Link("Install KOReader", destination: URL(string: "https://github.com/koreader/koreader/wiki/Installation-on-Kindle-devices")!) }
            if !status.service.healthy { Text("Start the collector above before pairing.").font(.caption).foregroundStyle(.orange) }
            mountPicker("Kindle USB folder", kind: "kindle", selection: $kindleMount)
            action(status.kindle.paired ? "Update Kindle pairing" : "Install & pair KOReader plugin", "pair_kindle", ["mount": kindleMount, "endpoint": selectedEndpoint], "Pairing Kindle…", disabled: !status.service.healthy || kindleMount.isEmpty || selectedEndpoint.isEmpty, success: "Kindle paired. Eject USB, then open KOReader to sync your highlights.")
            if status.kindle.paired { Label("Kindle pairing saved", systemImage: "checkmark.circle").foregroundStyle(teal) }
            Text("The plugin is enabled by installation. Eject USB and open KOReader. To test, choose Tools → More tools → Shared highlights → Sync highlights.").font(.caption).foregroundStyle(.secondary)
        }
        Card(title: "3. Pair your Xteink X4 Pro") {
            if !status.service.healthy { Text("Start the collector above before pairing.").font(.caption).foregroundStyle(.orange) }
            Picker("Connection", selection: $method) { Text("SD card").tag("SD card"); Text("LAN upload").tag("LAN upload") }.pickerStyle(.segmented)
            if method == "SD card" { mountPicker("X4 Pro SD card", kind: "xteink", selection: $xteinkMount) } else { TextField("Device URL, e.g. http://192.168.1.42", text: $deviceURL).textFieldStyle(.roundedBorder); Text("Enable the reader’s file-transfer web server before pairing.").font(.caption).foregroundStyle(.secondary) }
            Toggle("I checked: this device is an Xteink X4 Pro", isOn: $confirmed)
            Toggle("Build and stage compatible firmware (optional)", isOn: $firmware)
            Text("Shared highlights require the Reader Bridge CrossPoint build. Skip staging only if that build is already installed.").font(.caption).foregroundStyle(.secondary)
            if firmware { Text("Building can take several minutes and requires the firmware build tools. Keep the app open. Staging does not flash your reader: you must install the firmware manually from its SD card.").font(.callout).foregroundStyle(.secondary) }
            action("Pair X4 Pro", "pair_xteink", xteinkParameters, firmware ? "Building and staging firmware, then pairing… This may take several minutes." : "Pairing X4 Pro…", disabled: !status.service.healthy || !confirmed || selectedEndpoint.isEmpty || (method == "SD card" ? xteinkMount.isEmpty : deviceURL.isEmpty), success: firmware ? "Firmware staged and pairing saved. Safely eject the SD card and install the firmware manually on X4 Pro." : "X4 Pro pairing saved. Reload the reader, then follow the reading-position setup below.")
            if status.xteink.firmwareStaged { Label("Firmware staged · manual SD installation still required", systemImage: "sdcard").font(.callout) }
            if status.xteink.paired { Label("X4 Pro pairing saved", systemImage: "checkmark.circle").foregroundStyle(teal) }
        }
        Card(title: "4. Confirm a reading-position roundtrip") {
            Text("Use the exact same EPUB file (identical bytes) on both readers. In both readers’ progress-sync settings, set https://sync.crosspointreader.com and sign in with the same account.")
            Text("In KOReader, select Binary document matching and enable Auto sync. On Xteink, choose Ask every time. Sync a position from KOReader; on Xteink, choose Apply Remote. Move forward on Xteink, choose Upload Local, then sync in KOReader to check the return trip.")
            Text("These Xteink commands are manual. Matching editions and book identifiers matter; pairing alone does not prove position sync.").font(.callout).foregroundStyle(.secondary)
            Link("Read pairing and sync instructions", destination: URL(string: "https://github.com/skyerus/reader-bridge/blob/main/docs/SETUP.md#6-connect-reading-progress")!)
            action(status.progressVerified ? "Reset confirmation" : "I tested both directions successfully", "verify_progress", ["verified": !status.progressVerified], "Saving confirmation…", disabled: !status.progressVerified && (!status.kindle.paired || !status.xteink.paired))
            if status.progressVerified { Label("Roundtrip confirmed by you", systemImage: "checkmark.circle.fill").foregroundStyle(teal) }
        }
        }
        }
        .onAppear { portText = String(status.service.port > 0 ? status.service.port : 8084); if endpoint.isEmpty { endpoint = status.endpoint }; lastSuggestedEndpoint = status.endpoint; if kindleMount.isEmpty { kindleMount = status.mounts.first(where: { $0.kind == "kindle" })?.path ?? status.kindle.mount }; if xteinkMount.isEmpty { xteinkMount = status.mounts.first(where: { $0.kind == "xteink" })?.path ?? "" }; if deviceURL.isEmpty { deviceURL = status.xteink.url } }
        .onChange(of: status.endpoint) { endpointValue in if endpoint.isEmpty || endpoint == lastSuggestedEndpoint { endpoint = endpointValue }; lastSuggestedEndpoint = endpointValue }
    }
    var xteinkParameters: [String: Any] { var params: [String: Any] = ["endpoint": selectedEndpoint, "firmware": firmware, "model_confirmed": confirmed]; params[method == "SD card" ? "mount" : "device_url"] = method == "SD card" ? xteinkMount : deviceURL; return params }
    func action(_ title: String, _ command: String, _ params: [String: Any], _ activity: String, disabled: Bool = false, success: String? = nil) -> some View { Button(title) { Task { await model.perform(command, params, activity: activity, success: success) } }.buttonStyle(.bordered).disabled(model.busy || disabled) }
    func mountPicker(_ label: String, kind: String, selection: Binding<String>) -> some View { VStack(alignment: .leading, spacing: 8) { HStack { TextField(label, text: selection).textFieldStyle(.roundedBorder); Button("Choose…") { if let path = chooseFolder() { selection.wrappedValue = path } } }; if status.mounts.contains(where: { $0.kind == kind }) { Menu("Detected volumes") { ForEach(status.mounts.filter { $0.kind == kind }) { mount in Button(mount.name) { selection.wrappedValue = mount.path } } } } } }
}
