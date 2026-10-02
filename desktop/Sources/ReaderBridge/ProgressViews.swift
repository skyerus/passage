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
    private var progress: BridgeStatus.LocalProgress? { status.localProgress }
    private var ready: Bool { progress?.healthy == true && progress?.error.isEmpty == true }

    var body: some View {
        Card(title: "Reading positions") {
            if progress?.enabled == true {
                HStack {
                    Label(ready ? "Position sync on" : "Position sync needs attention", systemImage: "bookmark")
                        .font(.headline)
                    Spacer()
                    if !pairing {
                        Menu { Button("Turn off position sync") { Task { await model.perform("stop_progress", activity: "Stopping position sync…", success: "Position sync is off. Your saved places are kept.") } } } label: { Image(systemName: "ellipsis") }
                            .menuStyle(.borderlessButton).fixedSize()
                    }
                }
                if let error = progress?.error, !error.isEmpty { Text(error).font(.caption).foregroundStyle(.orange) }
                if !ready { startButton }
                if pairing { pairingSteps }
                else {
                    Text("\(progress?.bookCount ?? 0) saved positions")
                        .font(.callout).foregroundStyle(.secondary)
                    uploadActivity
                    Button(progress?.isConfigured == true ? "Manage readers" : "Connect readers") { model.selection = .setup }
                        .buttonStyle(.borderedProminent)
                }
            } else {
                Text("Continue reading on either reader. Use the same EPUB file on both.")
                    .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                startButton
            }
        }
        .disabled(model.busy)
        .onAppear { populate() }
        .onChange(of: status.mounts.map(\.path)) { _ in populate() }
    }

    private var startButton: some View {
        Button(progress?.enabled == true ? "Restart position sync" : "Turn on position sync") {
            Task {
                await model.perform("start_progress", ["endpoint": progress?.endpoint.isEmpty == false ? progress!.endpoint : status.endpoint], activity: "Starting reading-position sync…", success: "Connect your readers below.")
                if model.error == nil { model.selection = .setup }
            }
        }.buttonStyle(.borderedProminent).disabled(status.endpoint.isEmpty && (progress?.endpoint.isEmpty ?? true))
    }

    @ViewBuilder private var pairingSteps: some View {
        if progress?.isConfigured == true {
            Label("Readers paired", systemImage: "checkmark.circle").font(.callout).foregroundStyle(teal)
            uploadActivity
            DisclosureGroup("Reconnect readers") { readerConnections.padding(.top, 12) }.font(.callout)
            if !status.usesExistingSetup {
                Button("View highlights") { model.selection = .highlights }.buttonStyle(.borderedProminent)
            }
        } else {
            readerConnections
        }
    }

    @ViewBuilder private var uploadActivity: some View {
        if let uploads = progress?.uploads, !uploads.isEmpty {
            ForEach(uploads.indices, id: \.self) { index in
                let upload = uploads[index]
                Text("\(upload.device) · received \(Date(timeIntervalSince1970: upload.receivedAt).formatted(date: .abbreviated, time: .shortened))")
                    .font(.caption).foregroundStyle(.secondary)
            }
        } else if progress?.isConfigured == true {
            Text("Waiting for reader activity").font(.caption).foregroundStyle(.secondary)
        }
    }

    private var readerConnections: some View {
        VStack(alignment: .leading, spacing: 16) {
            Divider()
            Label(progress?.kindlePaired == true ? "Kindle settings saved" : "1. Connect your Kindle", systemImage: progress?.kindlePaired == true ? "checkmark.circle" : "cable.connector")
                .font(.headline)
            Text("Close KOReader and connect by USB.")
                .font(.callout).foregroundStyle(.secondary)
            HStack {
                TextField("Kindle USB folder", text: $kindleMount).textFieldStyle(.roundedBorder)
                Button("Choose…") { if let path = chooseFolder() { kindleMount = path } }
                Button(progress?.kindlePaired == true ? "Reconnect Kindle" : "Connect Kindle") {
                    Task { await model.perform("pair_progress_kindle", ["mount": kindleMount], activity: "Copying positions and connecting Kindle…", success: "Kindle settings saved. Eject it and reopen KOReader.") }
                }.disabled(progress?.healthy != true || kindleMount.isEmpty)
            }
            Divider()
            Label(progress?.xteinkPaired == true ? "Xteink settings saved" : "2. Connect your Xteink", systemImage: progress?.xteinkPaired == true ? "checkmark.circle" : "wifi")
                .font(.headline)
            Text(useCard ? "Insert the X4 Pro SD card into your Mac." : "Open File Transfer on your X4 Pro, then enter its address.")
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
        }
    }
    private func populate() {
        kindleMount = SetupInput.suggestedMount(kind: "kindle", mounts: status.mounts, current: kindleMount)
        xteinkMount = SetupInput.suggestedMount(kind: "xteink", mounts: status.mounts, current: xteinkMount)
        if deviceURL.isEmpty { deviceURL = status.xteink.url }
    }
}
