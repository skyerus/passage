import SwiftUI
import AppKit

struct ExistingSetupView: View {
    @EnvironmentObject var model: AppModel
    let status: BridgeStatus
    private var collectorOnline: Bool { SetupInput.existingCollectorOnline(status) }

    var body: some View {
        Card(title: status.usesExistingSetup ? "Existing archive connected" : "Connect your existing archive") {
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
    @State private var firmware = true
    @State private var installedFirmwareConfirmed = false
    @State private var showXteinkRepair = false
    @State private var connectionSettings = false
    @AppStorage("setup.devices") private var savedDeviceChoice = ""
    @AppStorage("setup.crosspointModel") private var savedCrossPointModel = ""
    @AppStorage("setup.positions") private var savedPositionChoice = ""
    @AppStorage("setup.kindleModelChecked") private var kindleModelChecked = false
    @AppStorage("setup.kindleJailbroken") private var kindleJailbroken = false
    @AppStorage("setup.kindleReady") private var kindleReady = false
    @AppStorage("setup.crosspointModelConfirmed") private var confirmedCrossPointModel = ""
    @AppStorage("setup.crosspointReadyModel") private var readyCrossPointModel = ""
    @AppStorage("setup.firmwareConfirmedReference") private var firmwareConfirmedReference = ""

    private var deviceChoice: SetupDeviceChoice? { SetupDeviceChoice.resolved(saved: savedDeviceChoice, status: status) }
    private var positionChoice: SetupPositionChoice { SetupPositionChoice(rawValue: savedPositionChoice) ?? .undecided }
    private var selectedEndpoint: String { endpoint.isEmpty ? status.endpoint : endpoint }
    private var selectedDevice: BridgeStatus.SupportedDevice? { status.crossPointDevices.first { $0.id == selectedModel } }
    private var selectedModel: String { SetupInput.selectedCrossPointModel(saved: savedCrossPointModel, status: status) }
    private var deviceName: String { selectedDevice?.name ?? "CrossPoint reader" }
    private var modelConfirmed: Bool { !selectedModel.isEmpty && confirmedCrossPointModel == selectedModel }
    private var crossPointReady: Bool { !selectedModel.isEmpty && readyCrossPointModel == selectedModel }
    private var prepareFirmware: Bool { SetupInput.shouldPrepareFirmware(requested: firmware, device: selectedDevice) }
    private var firmwareConfirmed: Bool { !firmwareConfirmedReference.isEmpty && firmwareConfirmedReference == SetupInput.firmwareConfirmationReference(status) }
    private var readiness: SetupReadiness { SetupReadiness(status: status, firmwareConfirmedByUser: firmwareConfirmed, deviceChoice: deviceChoice, positionChoice: positionChoice, crosspointModel: selectedModel) }
    private var validEndpoint: Bool { SetupInput.validLANAddress(selectedEndpoint) }
    private var xteinkConnectionValid: Bool { method == "SD card" ? !xteinkMount.isEmpty : SetupInput.validLANAddress(deviceURL) }
    private var continueTitle: String {
        guard let next = readiness.nextStep(after: flow.step) else { return "Continue" }
        return next == .complete ? "Finish setup" : "Continue to \(next.title)"
    }

    var body: some View {
        Group {
            if status.offersExistingSetup {
                ExistingSetupView(status: status)
            } else {
                VStack(alignment: .leading, spacing: 20) {
                    stepNavigation
                    currentStep
                    if flow.step != .readers && flow.step != .complete {
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
        .onChange(of: selectedModel) { _ in
            installedFirmwareConfirmed = false
            showXteinkRepair = false
            firmware = selectedDevice?.capabilities.highlights == true && selectedDevice?.firmwareAvailable == true
        }
        .onChange(of: selectedDevice?.firmwareAvailable) { available in
            if available != true { firmware = false }
        }
        .onChange(of: method) { _ in installedFirmwareConfirmed = false }
        .onChange(of: xteinkMount) { _ in installedFirmwareConfirmed = false }
        .onChange(of: deviceURL) { _ in installedFirmwareConfirmed = false }
    }

    private var stepNavigation: some View {
        HStack(spacing: 0) {
            ForEach(Array(readiness.visibleSteps.enumerated()), id: \.element.id) { index, step in
                if index > 0 { Rectangle().fill(teal.opacity(0.15)).frame(height: 1).padding(.horizontal, 10).accessibilityHidden(true) }
                Button { flow.visit(step, readiness: readiness) } label: {
                    HStack(spacing: 7) {
                        ZStack {
                            Circle().fill(flow.step == step ? teal : teal.opacity(0.08)).frame(width: 24, height: 24)
                            if readiness.isComplete(step) { Image(systemName: "checkmark").font(.system(size: 10, weight: .bold)) }
                            else { Text("\(index + 1)").font(.system(size: 11, weight: .semibold)) }
                        }.foregroundStyle(flow.step == step ? .white : teal)
                        Text(step.title).font(.callout.weight(flow.step == step ? .semibold : .regular))
                    }
                }
                .buttonStyle(.plain).foregroundStyle(flow.step == step ? ink : .secondary)
                .disabled(model.busy || !readiness.canVisit(step))
                .accessibilityLabel("\(step.title), step \(index + 1) of \(readiness.visibleSteps.count)\(readiness.isComplete(step) ? ", confirmed" : "")")
                .accessibilityAddTraits(flow.step == step ? [.isSelected] : [])
            }
        }
    }

    @ViewBuilder private var currentStep: some View {
        switch flow.step {
        case .readers: readersStep
        case .bridge: bridgeStep
        case .kindle: kindleStep
        case .xteink: xteinkStep
        case .progress: progressStep
        case .complete: completedStep
        }
    }

    private var readersStep: some View {
        Card(title: "What will you read on?") {
            Text("Connect one reader or both. You can add another later.").foregroundStyle(.secondary)
            VStack(spacing: 10) {
                ForEach(SetupDeviceChoice.allCases) { choice in
                    Button { savedDeviceChoice = choice.rawValue } label: {
                        HStack(spacing: 14) {
                            Image(systemName: choice == .both ? "books.vertical" : "book.closed").font(.system(size: 22, weight: .light)).frame(width: 32)
                            VStack(alignment: .leading, spacing: 4) {
                                Text(choice.title).font(.callout.weight(.semibold))
                                Text(choice.detail).font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Image(systemName: deviceChoice == choice ? "checkmark.circle.fill" : "circle").foregroundStyle(deviceChoice == choice ? teal : .secondary)
                        }.padding(15).contentShape(Rectangle())
                            .background(deviceChoice == choice ? teal.opacity(0.07) : BridgePalette.secondarySurface, in: RoundedRectangle(cornerRadius: 12))
                            .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(deviceChoice == choice ? teal.opacity(0.45) : BridgePalette.separator))
                    }.buttonStyle(.plain).disabled(model.busy)
                        .accessibilityAddTraits(deviceChoice == choice ? [.isSelected] : [])
                }
            }
            Button("Continue") { flow.advance(readiness) }.buttonStyle(.borderedProminent).disabled(model.busy || deviceChoice == nil)
        }
    }

    private var bridgeStep: some View {
        Card(title: "Connect to your Mac") {
            DeviceIllustration(guide: .bridge, readers: deviceChoice ?? .both, crosspointName: deviceName)
            Text("Keep your Mac awake and your selected readers on the same Wi-Fi.").foregroundStyle(.secondary)
            if model.error != nil {
                Text("The latest check failed. Refresh before continuing.").font(.callout).foregroundStyle(.secondary)
                action("Check again", "status", [:], "Checking your bridge…")
            } else if status.service.healthy {
                Label("Ready to receive highlights", systemImage: "checkmark.circle.fill").font(.callout).foregroundStyle(teal)
                continueButton
            } else if status.usesExistingSetup {
                Text("Start your existing Reading Highlights service, then refresh.").font(.callout).foregroundStyle(.secondary)
                action("Refresh connection", "status", [:], "Checking sync…")
            } else {
                action("Start Passage sync", "start_collector", ["port": Int(portText) ?? 8084], "Starting sync…", disabled: !SetupInput.validCollectorPort(portText))
            }
            connectionOptions
        }
    }

    private var kindleStep: some View {
        Card(title: status.kindle.paired ? "Kindle pairing saved" : "Connect your Kindle") {
            if status.kindle.paired {
                DeviceIllustration(guide: .kindleUSB)
                Text("Eject the Kindle, then open KOReader with Wi-Fi connected.").foregroundStyle(.secondary)
                continueButton
                DisclosureGroup("Reconnect Kindle") {
                    VStack(alignment: .leading, spacing: 12) {
                        mountPicker("Kindle", kind: "kindle", selection: $kindleMount)
                        action("Update Kindle pairing", "pair_kindle", ["mount": kindleMount, "endpoint": selectedEndpoint], "Updating Kindle pairing…", disabled: !status.service.healthy || kindleMount.isEmpty || !validEndpoint, success: "Pairing saved. Eject the Kindle and reopen KOReader.")
                    }.padding(.top, 10)
                }.font(.callout)
            } else {
                Text("Passage uses KOReader on a jailbroken Kindle.").foregroundStyle(.secondary)
                if !kindleReady {
                    prerequisite("1. Check your model and firmware", detail: "Find them in Settings → Device options → Device info. Use the live guide to check eligibility.", checked: $kindleModelChecked, link: "Check eligibility", url: "https://kindlemodding.org/jailbreak-wizard.html")
                    prerequisite("2. Complete the jailbreak", detail: "Follow the method the guide selects, including its post-jailbreak steps. If no method is supported, pause here.", checked: $kindleJailbroken, link: "Jailbreak guide", url: "https://kindlemodding.org/jailbreaking/")
                    prerequisite("3. Open an EPUB in KOReader", detail: "Use the installation path for your jailbreak. Open a DRM-free EPUB to check it works.", checked: $kindleReady, link: "Install KOReader", url: "https://github.com/koreader/koreader/wiki/Installation-on-Kindle-devices")
                    Text("Already set up? Check the final step when KOReader opens your EPUB.").font(.caption).foregroundStyle(.secondary)
                } else {
                    Label("KOReader is ready", systemImage: "checkmark.circle.fill").font(.callout).foregroundStyle(teal)
                    DeviceIllustration(guide: .kindleUSB)
                    Text("Close KOReader, then connect the Kindle by USB.").foregroundStyle(.secondary)
                    mountPicker("Kindle", kind: "kindle", selection: $kindleMount)
                    action("Connect Kindle", "pair_kindle", ["mount": kindleMount, "endpoint": selectedEndpoint], "Installing the KOReader plugin…", disabled: !status.service.healthy || kindleMount.isEmpty || !validEndpoint, success: "Plugin installed. Eject your Kindle, then open KOReader.")
                    Button("Show preparation steps") { kindleReady = false }.font(.callout)
                }
            }
            if !validEndpoint || model.error != nil { connectionOptions }
        }
    }

    private var xteinkStep: some View {
        VStack(alignment: .leading, spacing: 16) {
            Card(title: "Your CrossPoint reader") {
                Picker("Model", selection: Binding(get: { selectedModel }, set: { savedCrossPointModel = $0 })) {
                    ForEach(status.crossPointDevices) { device in Text(device.name).tag(device.id) }
                }.frame(maxWidth: 370)
                if let device = selectedDevice {
                    Text(device.capabilities.highlights ? "Highlights and reading positions" : device.capabilities.progress ? "Reading positions" : "Setup guidance only")
                        .font(.caption).foregroundStyle(.secondary)
                    if !device.pairingSupported {
                        Text(device.supportNote ?? "Passage pairing is not available for this model yet.").font(.callout).foregroundStyle(.secondary)
                    }
                } else { Text("Choose a supported model before continuing.").font(.callout).foregroundStyle(.orange) }
            }
            if readiness.firmwareNeedsConfirmation && !showXteinkRepair { firmwareConfirmationStep }
            else if readiness.xteinkPaired && !showXteinkRepair { crossPointConnectedStep }
            else { crossPointPairingStep }
        }
    }

    private var firmwareConfirmationStep: some View {
        Card(title: status.xteink.firmwareStaged ? "Finish on your reader" : "Check your Passage firmware") {
            if status.xteink.firmwareStaged {
                DeviceIllustration(guide: .firmware, crosspointName: deviceName, firmwareFilename: selectedDevice?.firmwareFilename ?? "Passage firmware")
                Text("Eject the card or leave File Transfer, then install the update on your reader.").foregroundStyle(.secondary)
                Text(selectedDevice?.firmwareUpdateInstructions ?? "Follow the firmware update instructions for your exact reader model.").font(.callout)
            } else {
                Text("Open a book and check More → Sync Highlights.").foregroundStyle(.secondary)
            }
            Button("I installed it and see Sync Highlights") {
                firmwareConfirmedReference = SetupInput.firmwareConfirmationReference(status)
                showXteinkRepair = false
            }.buttonStyle(.borderedProminent).disabled(model.busy)
            Button("Show firmware options") { showXteinkRepair = true }.disabled(model.busy)
            firmwareHelp
        }
    }

    private var crossPointConnectedStep: some View {
        Card(title: "\(deviceName) pairing saved") {
            DeviceIllustration(guide: .xteinkLAN, crosspointName: deviceName)
            Text(selectedDevice?.capabilities.highlights == true ? "Leave File Transfer or eject the SD card. Save a clipping in a book with Wi-Fi connected." : "Leave File Transfer or eject the SD card, then reopen your book.").foregroundStyle(.secondary)
            continueButton
            DisclosureGroup("Reconnect or update firmware") {
                Button("Show pairing options") { showXteinkRepair = true }.padding(.top, 8)
            }.font(.callout)
        }
    }

    private var crossPointPairingStep: some View {
        Card(title: crossPointReady ? "Connect \(deviceName)" : "Prepare \(deviceName)") {
            if !crossPointReady {
                prerequisite("1. Confirm your reader model", detail: "Check the name on your device. Select the same model in the installer.", checked: Binding(get: { modelConfirmed }, set: { confirmedCrossPointModel = $0 ? selectedModel : "" }))
                VStack(alignment: .leading, spacing: 6) {
                    Text("2. Install official CrossPoint").font(.callout.weight(.semibold))
                    Text("Back up your SD card, including its hidden .crosspoint folder. Connect by USB-C and follow the official installer for this model.").font(.callout).foregroundStyle(.secondary)
                    Link("Open CrossPoint installer", destination: SetupInput.installationURL(selectedDevice?.setupUrl))
                }
                prerequisite("3. Open an EPUB in CrossPoint", detail: "Confirm CrossPoint starts and reads your book before connecting Passage.", checked: Binding(get: { crossPointReady }, set: { readyCrossPointModel = $0 ? selectedModel : "" }))
                Text("Already running CrossPoint? Confirm the first and final steps.").font(.caption).foregroundStyle(.secondary)
            } else {
                DeviceIllustration(guide: method == "SD card" ? .xteinkSD : .xteinkLAN, crosspointName: deviceName)
                Text(method == "SD card" ? "Insert your reader’s SD card into your Mac." : "Open File Transfer on your reader and use the address it shows.").foregroundStyle(.secondary)
                Picker("Connection", selection: $method) {
                    Text("SD card").tag("SD card")
                    Text("Wi-Fi transfer").tag("LAN upload")
                }.pickerStyle(.segmented).frame(maxWidth: 320)
                if method == "SD card" { mountPicker("reader SD card", kind: "xteink", selection: $xteinkMount) }
                else {
                    TextField("http://192.168.1.42", text: $deviceURL).textFieldStyle(.roundedBorder).accessibilityLabel("CrossPoint File Transfer address")
                    if !deviceURL.isEmpty && !SetupInput.validLANAddress(deviceURL) { Text("Use the reader’s http:// LAN address, without a path.").font(.caption).foregroundStyle(.orange) }
                }
                Toggle("I checked: this is \(deviceName)", isOn: Binding(get: { modelConfirmed }, set: { confirmedCrossPointModel = $0 ? selectedModel : "" })).font(.callout)
                if selectedDevice?.capabilities.highlights == true {
                    if selectedDevice?.firmwareAvailable == true {
                        Toggle("Prepare Passage firmware", isOn: $firmware).font(.callout)
                        if prepareFirmware { Text("You’ll install the prepared update on your reader.").font(.caption).foregroundStyle(.secondary) }
                    } else {
                        Text(selectedDevice?.supportNote ?? "Passage firmware is not available for this model yet.").font(.callout).foregroundStyle(.secondary)
                    }
                    if !prepareFirmware { Toggle("Passage firmware is already installed", isOn: $installedFirmwareConfirmed).font(.callout) }
                }
                action(prepareFirmware ? "Prepare firmware and connect" : "Connect reader", "pair_xteink", xteinkParameters, prepareFirmware ? "Preparing Passage firmware…" : "Connecting your reader…", disabled: !canPairCrossPoint, success: prepareFirmware ? "Firmware prepared. Complete the update on your reader." : "Pairing saved. Leave File Transfer or eject the card.", resetFirmwareConfirmation: prepareFirmware)
                Button("Show preparation steps") { readyCrossPointModel = "" }.font(.callout)
                firmwareHelp
                if !validEndpoint || model.error != nil { connectionOptions }
            }
        }
    }

    private var canPairCrossPoint: Bool {
        SetupInput.canPairXteink(collectorOnline: status.service.healthy, endpoint: selectedEndpoint, connectionValid: xteinkConnectionValid, modelConfirmed: modelConfirmed && crossPointReady, stageFirmware: prepareFirmware, installedFirmwareConfirmed: installedFirmwareConfirmed, highlightsSupported: selectedDevice?.capabilities.highlights == true, pairingSupported: selectedDevice?.pairingSupported == true, firmwareAvailable: selectedDevice?.firmwareAvailable == true)
    }

    private var progressStep: some View {
        VStack(alignment: .leading, spacing: 12) {
            ReadingProgressView(status: status, pairing: true, deviceChoice: deviceChoice ?? .both, crosspointModel: selectedModel)
            HStack {
                if readiness.progressConfigured {
                    Button("Finish setup") { savedPositionChoice = SetupPositionChoice.enabled.rawValue; flow.advance(readiness) }.buttonStyle(.borderedProminent).disabled(model.busy)
                } else {
                    Button("Finish setup for now") {
                        savedPositionChoice = SetupPositionChoice.later.rawValue
                        flow.advance(readiness)
                    }.buttonStyle(.borderedProminent).disabled(model.busy)
                }
            }
            Text("Optional. You can change this in Settings at any time.").font(.caption).foregroundStyle(.secondary)
        }
    }

    private var completedStep: some View {
        Card(title: "Reader setup saved") {
            Label(deviceChoice == .both ? "Both readers paired" : "\(deviceChoice?.title ?? "Reader") paired", systemImage: "checkmark.circle.fill").foregroundStyle(teal)
            Text("New highlights appear in Highlights. Save a highlight with Wi-Fi connected while your Mac is awake.")
                .font(.callout).foregroundStyle(.secondary)
            HStack {
                Button("View highlights") { model.selection = .highlights }.buttonStyle(.borderedProminent)
                Button(deviceChoice == .both ? "Manage readers" : "Add another reader") { flow.visit(.readers, readiness: readiness) }.disabled(model.busy)
            }
            if !readiness.progressConfigured && readiness.progressAvailable {
                Button("Set up reading positions") { savedPositionChoice = ""; flow.visit(.progress, readiness: readiness) }.font(.callout).disabled(model.busy)
            }
        }
    }

    private var continueButton: some View {
        Button(continueTitle) { flow.advance(readiness) }.buttonStyle(.borderedProminent).disabled(model.busy)
    }

    private func prerequisite(_ title: String, detail: String, checked: Binding<Bool>, link: String? = nil, url: String? = nil) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Toggle(title, isOn: checked).font(.callout.weight(.semibold))
            Text(detail).font(.callout).foregroundStyle(.secondary)
            if let link, let url, let destination = URL(string: url) { Link(link, destination: destination).font(.callout) }
        }.disabled(model.busy)
    }

    private var firmwareHelp: some View {
        DisclosureGroup("Firmware details") {
            VStack(alignment: .leading, spacing: 8) {
                Text("Preserve your SD card and hidden .crosspoint folder. Preparing an update does not install it: finish on the reader, then confirm Sync Highlights appears.").font(.callout).foregroundStyle(.secondary)
                Link("CrossPoint installation", destination: SetupInput.installationURL(selectedDevice?.setupUrl))
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
                if status.service.healthy && !status.usesExistingSetup {
                    Button("Stop sync") { Task { await model.perform("stop_collector", activity: "Stopping your bridge…", success: "Sync stopped. Readers will retain queued highlights.") } }.disabled(model.busy)
                }
            }.padding(.top, 10)
        }.font(.callout)
    }

    private var xteinkParameters: [String: Any] {
        var parameters: [String: Any] = ["endpoint": selectedEndpoint, "firmware": prepareFirmware, "model_confirmed": modelConfirmed, "model": selectedModel]
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
        if savedDeviceChoice.isEmpty, let existing = deviceChoice { savedDeviceChoice = existing.rawValue }
        if savedCrossPointModel.isEmpty, let existing = status.xteink.model { savedCrossPointModel = existing }
        firmware = selectedDevice?.capabilities.highlights == true && selectedDevice?.firmwareAvailable == true
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
}
