import SwiftUI
import AppKit

struct ExistingSetupView: View {
    @EnvironmentObject var model: AppModel
    let status: BridgeStatus
    private var collectorOnline: Bool { SetupInput.existingCollectorOnline(status) }

    var body: some View {
        Card(title: status.usesExistingSetup ? "Your readers are set up" : "Connect your existing readers") {
            Label(model.error != nil ? "Unable to check connection" : collectorOnline ? "Ready to receive highlights" : "Highlight sync is paused", systemImage: model.error == nil && collectorOnline ? "checkmark.circle.fill" : "exclamationmark.triangle")
                .font(.callout).foregroundStyle(model.error == nil && collectorOnline ? teal : .orange)
            if status.usesExistingSetup {
                if !status.service.healthy { Text("Start your existing service, then refresh the connection.").font(.callout) }
                HStack {
                    Button("View highlights") { model.selection = .highlights }.buttonStyle(.borderedProminent)
                    Button("Refresh connection") { Task { await model.perform("status") } }.disabled(model.busy)
                }
            } else {
                Button("Use existing setup") { Task { await model.perform("connect_existing", activity: "Connecting to your bridge…", success: "Connected to your existing bridge.") } }
                    .buttonStyle(.borderedProminent).disabled(model.busy || !collectorOnline)
            }
        }
    }
}

struct SetupView: View {
    @EnvironmentObject var model: AppModel
    let status: BridgeStatus
    @State private var flow = SetupNavigation()
    @State private var endpoint = ""
    @State private var portText = "8084"
    @State private var lastSuggestedEndpoint = ""
    @State private var kindleMount = ""
    @State private var xteinkMount = ""
    @State private var deviceURL = ""
    @State private var method = "SD card"
    @State private var kindleReady = false
    @State private var modelConfirmed = false
    @State private var firmware = true
    @State private var installedFirmwareConfirmed = false
    @State private var showXteinkRepair = false
    @State private var connectionSettings = false
    @AppStorage("setup.firmwareConfirmedReference") private var firmwareConfirmedReference = ""

    private var selectedEndpoint: String { endpoint.isEmpty ? status.endpoint : endpoint }
    private var firmwareConfirmed: Bool { !firmwareConfirmedReference.isEmpty && firmwareConfirmedReference == SetupInput.firmwareConfirmationReference(status) }
    private var readiness: SetupReadiness { SetupReadiness(status: status, firmwareConfirmedByUser: firmwareConfirmed) }
    private var validEndpoint: Bool { SetupInput.validLANAddress(selectedEndpoint) }
    private var xteinkConnectionValid: Bool { method == "SD card" ? !xteinkMount.isEmpty : SetupInput.validLANAddress(deviceURL) }

    var body: some View {
        Group {
            if status.usesExistingSetup || status.offersExistingSetup {
                VStack(alignment: .leading, spacing: 20) {
                    ExistingSetupView(status: status)
                    if status.usesExistingSetup { ReadingProgressView(status: status, pairing: true) }
                }
            }
            else {
                VStack(alignment: .leading, spacing: 20) {
                    stepNavigation
                    currentStep
                    if flow.step != .bridge && flow.step != .complete {
                        Button { flow.back(readiness) } label: { Label("Back", systemImage: "chevron.left") }
                            .buttonStyle(.plain).font(.callout).foregroundStyle(.secondary).disabled(model.busy)
                    }
                }
            }
        }
        .onAppear { populateDefaults(); flow.reconcile(readiness) }
        .onChange(of: readiness) { flow.reconcile($0) }
        .onChange(of: status.endpoint) { value in
            if endpoint.isEmpty || endpoint == lastSuggestedEndpoint { endpoint = value }
            lastSuggestedEndpoint = value
        }
        .onChange(of: status.mounts.map(\.path)) { _ in selectDetectedMounts() }
        .onChange(of: method) { _ in resetDeviceConfirmations() }
        .onChange(of: xteinkMount) { _ in resetDeviceConfirmations() }
        .onChange(of: deviceURL) { _ in resetDeviceConfirmations() }
    }

    private var stepNavigation: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 0) {
                ForEach(SetupStep.visibleSteps) { step in
                    if step != .bridge { Rectangle().fill(teal.opacity(0.15)).frame(height: 1).padding(.horizontal, 10).accessibilityHidden(true) }
                    Button { flow.visit(step, readiness: readiness) } label: {
                        HStack(spacing: 7) {
                            ZStack {
                                Circle().fill(flow.step == step ? teal : teal.opacity(0.08)).frame(width: 24, height: 24)
                                if readiness.isComplete(step) { Image(systemName: "checkmark").font(.system(size: 10, weight: .bold)) }
                                else { Text("\(step.rawValue + 1)").font(.system(size: 11, weight: .semibold)) }
                            }.foregroundStyle(flow.step == step ? .white : teal)
                            Text(step.title).font(.callout.weight(flow.step == step ? .semibold : .regular))
                        }
                    }
                    .buttonStyle(.plain).foregroundStyle(flow.step == step ? ink : .secondary)
                    .disabled(model.busy || !readiness.canVisit(step))
                    .accessibilityLabel("\(step.title), step \(step.rawValue + 1) of 4\(readiness.isComplete(step) ? ", confirmed" : "")")
                    .accessibilityAddTraits(flow.step == step ? [.isSelected] : [])
                }
            }
        }
    }

    @ViewBuilder private var currentStep: some View {
        switch flow.step {
        case .bridge: bridgeStep
        case .kindle: kindleStep
        case .xteink: xteinkStep
        case .progress: progressStep
        case .complete: completedStep
        }
    }

    private var bridgeStep: some View {
        Card(title: "Highlight sync") {
            DeviceIllustration(guide: .bridge)
            Text("Connect both readers to the same Wi-Fi as your Mac.").foregroundStyle(.secondary)
            if model.error != nil {
                Text("The latest check failed. Refresh before continuing.").font(.callout).foregroundStyle(.secondary)
                action("Check again", "status", [:], "Checking your bridge…")
            } else if status.service.healthy {
                Label("Ready to receive highlights", systemImage: "checkmark.circle.fill").font(.callout).foregroundStyle(teal)
                Button("Continue to Kindle") { flow.advance(readiness) }.buttonStyle(.borderedProminent).disabled(model.busy)
            } else {
                action("Start highlight sync", "start_collector", ["port": Int(portText) ?? 8084], "Starting your bridge…", disabled: !SetupInput.validCollectorPort(portText), success: "Your bridge is online.")
            }
            connectionOptions
        }
    }

    private var kindleStep: some View {
        Card(title: status.kindle.paired ? "Kindle pairing saved" : "Connect your Kindle") {
            DeviceIllustration(guide: .kindleUSB)
            if status.kindle.paired {
                Text("Eject the Kindle, then open KOReader with Wi-Fi connected.").foregroundStyle(.secondary)
                Button("Continue to X4 Pro") { flow.advance(readiness) }.buttonStyle(.borderedProminent).disabled(model.busy)
                DisclosureGroup("Update pairing") {
                    VStack(alignment: .leading, spacing: 12) {
                        mountPicker("Kindle", kind: "kindle", selection: $kindleMount)
                        action("Update Kindle pairing", "pair_kindle", ["mount": kindleMount, "endpoint": selectedEndpoint], "Updating Kindle pairing…", disabled: !status.service.healthy || kindleMount.isEmpty || !validEndpoint, success: "Pairing saved. Eject the Kindle and reopen KOReader.")
                    }.padding(.top, 10)
                }.font(.callout)
            } else {
                Text("Close KOReader, then connect the Kindle by USB.").foregroundStyle(.secondary)
                Toggle("KOReader already opens on my jailbroken Kindle", isOn: $kindleReady).font(.callout)
                DisclosureGroup("Need KOReader first?") {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("Check your model and firmware, jailbreak your Kindle, then install KOReader.").font(.callout).foregroundStyle(.secondary)
                        HStack(spacing: 16) {
                            Link("Check model", destination: URL(string: "https://kindlemodding.org/kindle-models")!)
                            Link("Jailbreak guide", destination: URL(string: "https://kindlemodding.org/jailbreaking/")!)
                            Link("Install KOReader", destination: URL(string: "https://github.com/koreader/koreader/wiki/Installation-on-Kindle-devices")!)
                        }
                    }.padding(.top, 10)
                }.font(.callout)
                mountPicker("Kindle", kind: "kindle", selection: $kindleMount)
                action("Pair Kindle", "pair_kindle", ["mount": kindleMount, "endpoint": selectedEndpoint], "Installing the KOReader plugin…", disabled: !kindleReady || !status.service.healthy || kindleMount.isEmpty || !validEndpoint, success: "Plugin installed and pairing saved. Eject your Kindle, then open KOReader.")
            }
            if !validEndpoint || model.error != nil { connectionOptions }
        }
    }

    private var xteinkStep: some View {
        Card(title: readiness.firmwareNeedsConfirmation && !showXteinkRepair ? (status.xteink.firmwareStaged ? "Finish on your X4 Pro" : "Check your X4 Pro firmware") : status.xteink.paired && !showXteinkRepair ? "X4 Pro pairing saved" : "Connect your X4 Pro") {
            if readiness.firmwareNeedsConfirmation && !showXteinkRepair {
                if status.xteink.firmwareStaged {
                    DeviceIllustration(guide: .firmware)
                    Text("Eject the card or leave File Transfer, then install the update on your reader.").foregroundStyle(.secondary)
                    Text("Choose reader-bridge-x4-pro.bin in Settings → System → SD Card Firmware Update. Keep the reader powered on until it finishes.").font(.callout)
                } else {
                    DeviceIllustration(guide: .xteinkLAN)
                    Text("Shared highlights need Reader Bridge firmware. Open a book and check More → Sync Highlights.").foregroundStyle(.secondary)
                }
                Button(status.xteink.firmwareStaged ? "I installed it and see Sync Highlights" : "Reader Bridge firmware is already installed") {
                    firmwareConfirmedReference = SetupInput.firmwareConfirmationReference(status)
                    showXteinkRepair = false
                }.buttonStyle(.borderedProminent).disabled(model.busy)
                Button("I need the Reader Bridge firmware") { firmware = true; modelConfirmed = false; showXteinkRepair = true }.disabled(model.busy)
                firmwareHelp
            } else if status.xteink.paired && !showXteinkRepair {
                DeviceIllustration(guide: .xteinkLAN)
                Text("Leave File Transfer or eject the SD card. Open a book and save a clipping with Wi-Fi connected.").foregroundStyle(.secondary)
                HStack {
                    Button("View highlights") { model.selection = .highlights }.buttonStyle(.borderedProminent)
                    Button("Set up reading positions") { flow.advance(readiness) }.disabled(model.busy)
                }
                DisclosureGroup("Pair again or install firmware") {
                    Button("Show pairing options") { modelConfirmed = false; showXteinkRepair = true }.padding(.top, 8)
                }.font(.callout)
            } else {
                DeviceIllustration(guide: method == "SD card" ? .xteinkSD : .xteinkLAN)
                Text(method == "SD card" ? "Insert the X4 Pro SD card into your Mac." : "Open File Transfer on the X4 Pro. Use the address it shows.").foregroundStyle(.secondary)
                Picker("Connection", selection: $method) {
                    Text("SD card").tag("SD card")
                    Text("Wi-Fi transfer").tag("LAN upload")
                }.pickerStyle(.segmented).frame(maxWidth: 320)
                if method == "SD card" { mountPicker("X4 Pro SD card", kind: "xteink", selection: $xteinkMount) }
                else {
                    TextField("http://192.168.1.42", text: $deviceURL).textFieldStyle(.roundedBorder).accessibilityLabel("X4 Pro File Transfer address")
                    if !deviceURL.isEmpty && !SetupInput.validLANAddress(deviceURL) { Text("Use the reader’s http:// LAN address, without a path.").font(.caption).foregroundStyle(.orange) }
                }
                Toggle("I checked: this device is an Xteink X4 Pro", isOn: $modelConfirmed).font(.callout)
                Toggle("Build and stage Reader Bridge firmware", isOn: $firmware).font(.callout)
                if !firmware { Toggle("Reader Bridge firmware is already installed", isOn: $installedFirmwareConfirmed).font(.callout) }
                if firmware { Text("Requires internet and several minutes. You’ll install the update on your reader.").font(.caption).foregroundStyle(.secondary) }
                action(firmware ? "Build firmware & pair" : "Pair X4 Pro", "pair_xteink", xteinkParameters, firmware ? "Building and staging firmware… This can take several minutes." : "Pairing your X4 Pro…", disabled: !SetupInput.canPairXteink(collectorOnline: status.service.healthy, endpoint: selectedEndpoint, connectionValid: xteinkConnectionValid, modelConfirmed: modelConfirmed, stageFirmware: firmware, installedFirmwareConfirmed: installedFirmwareConfirmed), success: firmware ? "Firmware staged. Complete the update on your X4 Pro." : "Pairing saved. Leave File Transfer or eject the card.", resetFirmwareConfirmation: firmware)
                firmwareHelp
                if !validEndpoint || model.error != nil { connectionOptions }
            }
        }
    }

    private var progressStep: some View {
        VStack(alignment: .leading, spacing: 12) {
            ReadingProgressView(status: status, pairing: true)
            if !readiness.progressConfigured { Button("Later") { model.selection = .highlights }.font(.callout) }
        }
    }

    private var completedStep: some View {
        Card(title: "Setup complete") {
            DeviceIllustration(guide: .bridge)
            Button("View highlights") { model.selection = .highlights }.buttonStyle(.borderedProminent)
        }
    }

    private var firmwareHelp: some View {
        DisclosureGroup("Firmware help") {
            VStack(alignment: .leading, spacing: 8) {
                Text("CrossPoint must already start on an X4 Pro. Preserve its SD card and hidden .crosspoint folder. Building needs Git and downloaded build tools; staging does not flash the reader.").font(.callout).foregroundStyle(.secondary)
                Link("CrossPoint installation", destination: URL(string: "https://crosspointreader.com/")!)
                Link("Reader Bridge firmware instructions", destination: URL(string: "https://github.com/skyerus/reader-bridge/blob/main/docs/SETUP.md#xteink")!)
            }.padding(.top, 8)
        }.font(.callout)
    }

    private var connectionOptions: some View {
        DisclosureGroup("Connection settings", isExpanded: $connectionSettings) {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("Port").font(.callout)
                    TextField("8084", text: $portText).frame(width: 90).textFieldStyle(.roundedBorder).disabled(status.service.healthy).accessibilityLabel("Highlight sync port")
                }
                if !SetupInput.validCollectorPort(portText) { Text("Choose a port from 1024 to 65535.").font(.caption).foregroundStyle(.orange) }
                TextField("Mac LAN address", text: $endpoint).textFieldStyle(.roundedBorder).accessibilityLabel("Mac collector LAN address")
                if !status.addresses.isEmpty { Menu("Choose a Mac address") { ForEach(status.addresses, id: \.self) { address in Button(address) { endpoint = address } } } }
                Text(validEndpoint ? "Use the Mac’s private IP if .local fails." : "Use http:// with a private IP or a .local name, without a path.").font(.caption).foregroundStyle(validEndpoint ? Color.secondary : Color.orange)
                if status.service.healthy {
                    Button("Stop bridge") { Task { await model.perform("stop_collector", activity: "Stopping your bridge…", success: "Bridge stopped. Readers will retain queued highlights.") } }.disabled(model.busy)
                }
            }.padding(.top, 10)
        }.font(.callout)
    }

    private var xteinkParameters: [String: Any] {
        var parameters: [String: Any] = ["endpoint": selectedEndpoint, "firmware": firmware, "model_confirmed": modelConfirmed]
        parameters[method == "SD card" ? "mount" : "device_url"] = method == "SD card" ? xteinkMount : deviceURL
        return parameters
    }

    private func action(_ title: String, _ command: String, _ parameters: [String: Any], _ activity: String, disabled: Bool = false, success: String? = nil, resetFirmwareConfirmation: Bool = false) -> some View {
        Button(title) {
            if resetFirmwareConfirmation { firmwareConfirmedReference = "" }
            Task {
                await model.perform(command, parameters, activity: activity, success: success)
                if command == "pair_xteink", model.error == nil {
                    showXteinkRepair = false
                    if !resetFirmwareConfirmation, installedFirmwareConfirmed, let newStatus = model.status {
                        firmwareConfirmedReference = SetupInput.firmwareConfirmationReference(newStatus)
                    }
                }
            }
        }.buttonStyle(.borderedProminent).disabled(model.busy || disabled)
    }

    private func mountPicker(_ label: String, kind: String, selection: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            let detected = status.mounts.filter { $0.kind == kind }
            if let selected = detected.first(where: { $0.path == selection.wrappedValue }) {
                Label(selected.name, systemImage: kind == "kindle" ? "externaldrive.connected.to.line.below" : "sdcard").font(.callout.weight(.medium))
            } else if selection.wrappedValue.isEmpty {
                Label(detected.count > 1 ? "Choose the correct \(label)" : "Waiting for \(label)…", systemImage: "externaldrive").font(.callout).foregroundStyle(.secondary)
            } else {
                Label(URL(fileURLWithPath: selection.wrappedValue).lastPathComponent, systemImage: "folder").font(.callout.weight(.medium))
            }
            HStack {
                if !detected.isEmpty { Menu("Choose detected device") { ForEach(detected) { mount in Button(mount.name) { selection.wrappedValue = mount.path } } } }
                Button("Choose folder…") { if let path = chooseFolder() { selection.wrappedValue = path } }
                Button("Check again") { Task { await model.perform("status") } }.disabled(model.busy)
            }
            DisclosureGroup("Folder details") {
                TextField(label, text: selection).textFieldStyle(.roundedBorder).accessibilityLabel("\(label) mounted folder").padding(.top, 8)
            }.font(.caption)
        }
    }

    private func populateDefaults() {
        portText = String(status.service.port > 0 ? status.service.port : 8084)
        if endpoint.isEmpty { endpoint = status.endpoint }
        lastSuggestedEndpoint = status.endpoint
        if deviceURL.isEmpty { deviceURL = status.xteink.url }
        selectDetectedMounts()
    }

    private func selectDetectedMounts() {
        kindleMount = SetupInput.suggestedMount(kind: "kindle", mounts: status.mounts, current: kindleMount)
        xteinkMount = SetupInput.suggestedMount(kind: "xteink", mounts: status.mounts, current: xteinkMount)
    }

    private func resetDeviceConfirmations() {
        modelConfirmed = false
        installedFirmwareConfirmed = false
    }
}
