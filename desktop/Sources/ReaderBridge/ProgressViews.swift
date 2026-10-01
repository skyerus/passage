import AppKit
import SwiftUI

struct ReadingProgressView: View {
    @EnvironmentObject var model: AppModel
    let status: BridgeStatus
    var pairing = false
    @State private var kindleMount = ""
    @State private var xteinkMount = ""
    @State private var deviceURL = ""
    @State private var useCard = false
    @State private var confirmedRoundTrip = false
    private var progress: BridgeStatus.LocalProgress? { status.localProgress }
    private var ready: Bool { progress?.healthy == true }

    var body: some View {
        Card(title: "Reading positions") {
            if progress?.enabled == true {
                HStack {
                    Label(ready ? "Syncing through this Mac" : "Position sync needs attention", systemImage: "bookmark")
                        .font(.headline)
                    Spacer()
                    if !pairing {
                        Menu { Button("Turn off position sync") { Task { await model.perform("stop_progress", activity: "Stopping position sync…", success: "Position sync is off. Your saved places are kept.") } } } label: { Image(systemName: "ellipsis") }
                            .menuStyle(.borderlessButton).fixedSize()
                    }
                }
                Text("Your Mac must be awake and on the same reachable network.")
                    .font(.callout).foregroundStyle(.secondary)
                if let error = progress?.error, !error.isEmpty { Text(error).font(.caption).foregroundStyle(.orange) }
                if !ready { startButton }
                if pairing { pairingSteps }
                else {
                    Text("\(progress?.bookCount ?? 0) books with a saved place")
                        .font(.callout).foregroundStyle(.secondary)
                    if let uploads = progress?.uploads, !uploads.isEmpty {
                        ForEach(uploads.indices, id: \.self) { index in
                            let upload = uploads[index]
                            Text("\(upload.device) · last upload \(Date(timeIntervalSince1970: upload.receivedAt).formatted(date: .abbreviated, time: .shortened))")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    Button(progress?.verified == true ? "Manage readers" : "Connect & test readers") { model.selection = .setup }
                        .buttonStyle(.borderedProminent)
                }
            } else {
                Label("Keep your place with Reader Bridge", systemImage: "bookmark").font(.headline)
                Text("Sync the same EPUB between KOReader and CrossPoint through your Mac. Starts at login and works while the Mac is awake.")
                    .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                startButton
                Text("You’ll connect each reader once. Existing settings and positions are kept for recovery.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .disabled(model.busy)
        .onAppear { populate() }
        .onChange(of: status.mounts.map(\.path)) { _ in populate() }
        .onChange(of: progress?.endpoint) { _ in confirmedRoundTrip = false }
    }

    private var startButton: some View {
        Button(progress?.enabled == true ? "Restart position sync" : "Use Reader Bridge for positions") {
            Task {
                await model.perform("start_progress", ["endpoint": progress?.endpoint.isEmpty == false ? progress!.endpoint : status.endpoint], activity: "Starting reading-position sync…", success: "Position sync is ready. Connect each reader in Setup.")
                if model.error == nil { model.selection = .setup }
            }
        }.buttonStyle(.borderedProminent).disabled(status.endpoint.isEmpty && (progress?.endpoint.isEmpty ?? true))
    }

    private var pairingSteps: some View {
        VStack(alignment: .leading, spacing: 16) {
            Divider()
            Label(progress?.kindlePaired == true ? "Kindle settings saved" : "1. Connect your Kindle", systemImage: progress?.kindlePaired == true ? "checkmark.circle" : "cable.connector")
                .font(.headline)
            Text("Close KOReader and connect by USB. Your existing sync positions are copied before the server changes.")
                .font(.callout).foregroundStyle(.secondary)
            HStack {
                TextField("Kindle USB folder", text: $kindleMount).textFieldStyle(.roundedBorder)
                Button("Choose…") { if let path = chooseFolder() { kindleMount = path } }
                Button(progress?.kindlePaired == true ? "Reconnect Kindle" : "Connect Kindle") {
                    Task { await model.perform("pair_progress_kindle", ["mount": kindleMount], activity: "Copying positions and connecting Kindle…", success: "Kindle settings saved. Eject it and reopen KOReader.") }
                }.disabled(!ready || kindleMount.isEmpty)
            }
            Divider()
            Label(progress?.xteinkPaired == true ? "Xteink settings saved" : "2. Connect your Xteink", systemImage: progress?.xteinkPaired == true ? "checkmark.circle" : "wifi")
                .font(.headline)
            Text("Open File Transfer on your X4 Pro, then enter its address.")
                .font(.callout).foregroundStyle(.secondary)
            HStack {
                if useCard {
                    TextField("Xteink SD card folder", text: $xteinkMount).textFieldStyle(.roundedBorder)
                    Button("Choose…") { if let path = chooseFolder() { xteinkMount = path } }
                } else {
                    TextField("http://192.168.1.42", text: $deviceURL).textFieldStyle(.roundedBorder).accessibilityLabel("Xteink File Transfer address")
                }
                Button(progress?.xteinkPaired == true ? "Reconnect Xteink" : "Connect Xteink") {
                    Task {
                        await model.perform("pair_progress_xteink", useCard ? ["mount": xteinkMount] : ["device_url": deviceURL], activity: "Connecting Xteink progress…", success: "Xteink settings saved. Restart the Xteink to apply them.")
                    }
                }.disabled(!ready || progress?.kindlePaired != true || (useCard ? xteinkMount.isEmpty : !SetupInput.validLANAddress(deviceURL)))
            }
            Toggle("Use its SD card instead", isOn: $useCard).font(.caption)
            if progress?.kindlePaired == true && progress?.xteinkPaired == true {
                Divider()
                Label(progress?.verified == true ? "Round trip confirmed by you" : "3. Check both directions", systemImage: progress?.verified == true ? "checkmark.circle" : "arrow.left.arrow.right")
                    .font(.headline)
                Text("Eject and reopen KOReader; restart Xteink. Open the same EPUB on both. On Xteink, Upload Local, then sync KOReader. Read onward in KOReader, close the book, then Apply Remote on Xteink.")
                    .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                Text("The passage should match in both directions. Xteink’s progress buttons stay manual; its Wi-Fi behavior is unchanged.")
                    .font(.caption).foregroundStyle(.secondary)
                if progress?.verified != true {
                    Toggle("The passage matched in both directions", isOn: $confirmedRoundTrip).font(.callout)
                    Button("Finish setup") {
                        Task {
                            await model.perform("verify_local_progress", ["verified": true], success: "Reading-position sync confirmed.")
                            if model.error == nil { model.selection = .highlights }
                        }
                    }.buttonStyle(.borderedProminent).disabled(!ready || !confirmedRoundTrip)
                }
            }
        }
    }
    private func populate() {
        kindleMount = SetupInput.suggestedMount(kind: "kindle", mounts: status.mounts, current: kindleMount)
        xteinkMount = SetupInput.suggestedMount(kind: "xteink", mounts: status.mounts, current: xteinkMount)
        if deviceURL.isEmpty { deviceURL = status.xteink.url }
    }
}
