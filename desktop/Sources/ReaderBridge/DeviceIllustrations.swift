import SwiftUI

/// Schematic guides, not screenshots or claims about a connected device.
struct DeviceIllustration: View {
    enum Guide {
        case bridge, kindleUSB, xteinkSD, xteinkLAN, firmware
        case sameBook, xteinkAccount, kindleAccount, sendToKindle, returnToXteink
    }
    let guide: Guide
    var readers: SetupDeviceChoice = .both
    var crosspointName = "CrossPoint reader"
    var firmwareFilename = "Passage firmware"

    var body: some View {
        content.frame(maxWidth: .infinity).padding(.vertical, 6)
        .padding(18).background(teal.opacity(0.045)).clipShape(RoundedRectangle(cornerRadius: 16))
        .accessibilityElement(children: .ignore).accessibilityLabel(accessibilityDescription)
    }

    @ViewBuilder private var content: some View {
        switch guide {
        case .bridge:
            HStack(spacing: 18) {
                if readers.includesKindle {
                    device("Kindle", symbol: "book.closed", detail: "KOReader")
                    Image(systemName: "wifi").foregroundStyle(teal)
                }
                device("Your Mac", symbol: "desktopcomputer", detail: "Passage")
                if readers.includesCrossPoint {
                    Image(systemName: "wifi").foregroundStyle(teal)
                    device(crosspointName, symbol: "book.closed", detail: "CrossPoint")
                }
            }
        case .kindleUSB:
            HStack(spacing: 26) {
                device("Your Mac", symbol: "desktopcomputer", detail: "Passage")
                VStack(spacing: 8) { Image(systemName: "cable.connector").font(.system(size: 28)); Text("USB").font(.caption) }.foregroundStyle(teal)
                device("Kindle", symbol: "book.closed", detail: "USB storage")
            }
        case .xteinkSD:
            HStack(spacing: 20) {
                device(crosspointName, symbol: "book.closed", detail: "CrossPoint")
                Image(systemName: "arrow.right").foregroundStyle(teal)
                device("SD card", symbol: "sdcard", detail: "Card reader")
                Image(systemName: "arrow.right").foregroundStyle(teal)
                device("Your Mac", symbol: "desktopcomputer", detail: "Mounted card")
            }
        case .xteinkLAN:
            HStack(spacing: 26) {
                device(crosspointName, symbol: "book.closed", detail: "File Transfer")
                Image(systemName: "wifi").font(.system(size: 26)).foregroundStyle(teal)
                device("Your Mac", symbol: "desktopcomputer", detail: "Same Wi-Fi")
            }
        case .firmware:
            menuGuide(device: crosspointName, rows: ["Leave File Transfer or eject card", "Install the update on your reader", "Reopen CrossPoint"], final: firmwareFilename)
        case .sameBook:
            HStack(spacing: 22) {
                device("Kindle", symbol: "book.closed", detail: "Same file")
                VStack(spacing: 7) { Image(systemName: "doc").font(.system(size: 28)); Text("EPUB").font(.caption.weight(.medium)) }.foregroundStyle(teal)
                device(crosspointName, symbol: "book.closed", detail: "Same file")
            }
        case .xteinkAccount:
            menuGuide(device: crosspointName, rows: ["Settings", "System", "KOReader Sync"], final: "Ask every time")
        case .kindleAccount:
            menuGuide(device: "KOReader", rows: ["Progress sync", "Document matching: Binary"], final: "Auto sync: on")
        case .sendToKindle:
            HStack(spacing: 22) {
                device(crosspointName, symbol: "book.closed", detail: "Upload Local")
                Image(systemName: "arrow.right").font(.title2).foregroundStyle(teal)
                device("Kindle", symbol: "book.closed", detail: "Sync & compare")
            }
        case .returnToXteink:
            HStack(spacing: 22) {
                device("Kindle", symbol: "book.closed", detail: "Read & close")
                Image(systemName: "arrow.right").font(.title2).foregroundStyle(teal)
                device(crosspointName, symbol: "book.closed", detail: "Apply Remote")
            }
        }
    }

    private func device(_ title: String, symbol: String, detail: String) -> some View {
        VStack(spacing: 9) {
            Image(systemName: symbol).font(.system(size: 34, weight: .light)).foregroundStyle(teal).frame(height: 44)
            Text(title).font(.callout.weight(.medium))
            Text(detail).font(.caption2).foregroundStyle(.secondary)
        }.frame(minWidth: 78)
    }

    private func menuGuide(device name: String, rows: [String], final: String) -> some View {
        HStack(spacing: 30) {
            device(name, symbol: "book.closed", detail: "On your reader")
            VStack(alignment: .leading, spacing: 8) {
                ForEach(Array(rows.enumerated()), id: \.offset) { index, row in
                    HStack(spacing: 8) {
                        Text("\(index + 1)").font(.caption2.weight(.semibold)).foregroundStyle(teal).frame(width: 18, height: 18).background(teal.opacity(0.1)).clipShape(Circle())
                        Text(row).font(.callout)
                    }
                }
                Text(final).font(.caption.weight(.medium)).foregroundStyle(teal).padding(.top, 3)
            }
        }
    }

    private var accessibilityDescription: String {
        switch guide {
        case .bridge: return "Illustration: your selected readers and Mac connected over the same Wi-Fi."
        case .kindleUSB: return "Illustration: Kindle in USB storage mode connected to the Mac by a USB cable."
        case .xteinkSD: return "Illustration: move the \(crosspointName) SD card to a card reader connected to the Mac."
        case .xteinkLAN: return "Illustration: \(crosspointName) in File Transfer mode on the same Wi-Fi as the Mac."
        case .firmware: return "Illustration: leave File Transfer or eject the card, install \(firmwareFilename) on \(crosspointName), then reopen CrossPoint."
        case .sameBook: return "Illustration: the exact same EPUB file on Kindle and \(crosspointName)."
        case .xteinkAccount: return "Illustration: \(crosspointName) Settings, System, KOReader Sync, with Ask every time selected."
        case .kindleAccount: return "Illustration: KOReader Progress sync, Binary document matching, Auto sync on."
        case .sendToKindle: return "Illustration: Upload Local on \(crosspointName), then sync and compare the passage on Kindle."
        case .returnToXteink: return "Illustration: read and close the book on Kindle, then Apply Remote on \(crosspointName)."
        }
    }
}
