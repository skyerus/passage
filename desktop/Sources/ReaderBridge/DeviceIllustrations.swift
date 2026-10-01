import SwiftUI

/// Schematic guides, not screenshots or claims about a connected device.
struct DeviceIllustration: View {
    enum Guide {
        case bridge, kindleUSB, xteinkSD, xteinkLAN, firmware
        case sameBook, xteinkAccount, kindleAccount, sendToKindle, returnToXteink
    }
    let guide: Guide

    var body: some View {
        VStack(spacing: 12) {
            HStack {
                Spacer()
                Text("ILLUSTRATION").font(.system(size: 9, weight: .semibold)).tracking(1.3).foregroundStyle(.secondary)
            }
            content.frame(maxWidth: .infinity).padding(.vertical, 6)
        }
        .padding(18).background(teal.opacity(0.045)).clipShape(RoundedRectangle(cornerRadius: 16))
        .accessibilityElement(children: .ignore).accessibilityLabel(accessibilityDescription)
    }

    @ViewBuilder private var content: some View {
        switch guide {
        case .bridge:
            HStack(spacing: 18) {
                device("Kindle", symbol: "book.closed", detail: "KOReader")
                Image(systemName: "wifi").foregroundStyle(teal)
                device("Your Mac", symbol: "desktopcomputer", detail: "Reader Bridge")
                Image(systemName: "wifi").foregroundStyle(teal)
                device("X4 Pro", symbol: "book.closed", detail: "CrossPoint")
            }
        case .kindleUSB:
            HStack(spacing: 26) {
                device("Your Mac", symbol: "desktopcomputer", detail: "Reader Bridge")
                VStack(spacing: 8) { Image(systemName: "cable.connector").font(.system(size: 28)); Text("USB").font(.caption) }.foregroundStyle(teal)
                device("Kindle", symbol: "book.closed", detail: "USB storage")
            }
        case .xteinkSD:
            HStack(spacing: 20) {
                device("X4 Pro", symbol: "book.closed", detail: "CrossPoint")
                Image(systemName: "arrow.right").foregroundStyle(teal)
                device("SD card", symbol: "sdcard", detail: "Card reader")
                Image(systemName: "arrow.right").foregroundStyle(teal)
                device("Your Mac", symbol: "desktopcomputer", detail: "Mounted card")
            }
        case .xteinkLAN:
            HStack(spacing: 26) {
                device("X4 Pro", symbol: "book.closed", detail: "File Transfer")
                Image(systemName: "wifi").font(.system(size: 26)).foregroundStyle(teal)
                device("Your Mac", symbol: "desktopcomputer", detail: "Same Wi-Fi")
            }
        case .firmware:
            menuGuide(device: "X4 Pro", rows: ["Settings", "System", "SD Card Firmware Update"], final: "reader-bridge-x4-pro.bin")
        case .sameBook:
            HStack(spacing: 22) {
                device("Kindle", symbol: "book.closed", detail: "Same file")
                VStack(spacing: 7) { Image(systemName: "doc").font(.system(size: 28)); Text("EPUB").font(.caption.weight(.medium)); Text("Identical bytes").font(.caption2) }.foregroundStyle(teal)
                device("X4 Pro", symbol: "book.closed", detail: "Same file")
            }
        case .xteinkAccount:
            menuGuide(device: "X4 Pro", rows: ["Settings", "System", "KOReader Sync"], final: "Ask every time")
        case .kindleAccount:
            menuGuide(device: "KOReader", rows: ["Progress sync", "Document matching: Binary"], final: "Auto sync: on")
        case .sendToKindle:
            HStack(spacing: 22) {
                device("X4 Pro", symbol: "book.closed", detail: "Upload Local")
                Image(systemName: "arrow.right").font(.title2).foregroundStyle(teal)
                device("Kindle", symbol: "book.closed", detail: "Sync & compare")
            }
        case .returnToXteink:
            HStack(spacing: 22) {
                device("Kindle", symbol: "book.closed", detail: "Read & close")
                Image(systemName: "arrow.right").font(.title2).foregroundStyle(teal)
                device("X4 Pro", symbol: "book.closed", detail: "Apply Remote")
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
        case .bridge: return "Illustration: Kindle, Mac and X4 Pro connected over the same Wi-Fi."
        case .kindleUSB: return "Illustration: Kindle in USB storage mode connected to the Mac by a USB cable."
        case .xteinkSD: return "Illustration: move the X4 Pro SD card to a card reader connected to the Mac."
        case .xteinkLAN: return "Illustration: X4 Pro in File Transfer mode on the same Wi-Fi as the Mac."
        case .firmware: return "Illustration: on X4 Pro, open Settings, System, SD Card Firmware Update and choose reader-bridge-x4-pro.bin."
        case .sameBook: return "Illustration: the exact same EPUB file on Kindle and X4 Pro."
        case .xteinkAccount: return "Illustration: X4 Pro Settings, System, KOReader Sync, with Ask every time selected."
        case .kindleAccount: return "Illustration: KOReader Progress sync, Binary document matching, Auto sync on."
        case .sendToKindle: return "Illustration: Upload Local on X4 Pro, then sync and compare the passage on Kindle."
        case .returnToXteink: return "Illustration: read and close the book on Kindle, then Apply Remote on X4 Pro."
        }
    }
}
