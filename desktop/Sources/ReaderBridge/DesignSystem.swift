import SwiftUI
import AppKit

// Semantic colors follow the user's appearance, including increased contrast.
let ink = Color.primary
let teal = Color(nsColor: NSColor(name: "BridgeAccent") { appearance in
    appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
        ? NSColor(red: 0.40, green: 0.76, blue: 0.70, alpha: 1)
        : NSColor(red: 0.12, green: 0.40, blue: 0.36, alpha: 1)
})
let paper = Color(nsColor: .windowBackgroundColor)

enum BridgePalette {
    static let accent = teal
    static let canvas = paper
    static let surface = Color(nsColor: .textBackgroundColor)
    static let secondarySurface = Color(nsColor: .controlBackgroundColor)
    static let separator = Color(nsColor: .separatorColor)
}

struct BridgeCanvas: View {
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    var body: some View {
        ZStack {
            BridgePalette.canvas
            if !reduceTransparency {
                RadialGradient(colors: [teal.opacity(colorScheme == .dark ? 0.11 : 0.065), .clear], center: .topTrailing, startRadius: 0, endRadius: 660)
                RadialGradient(colors: [Color.orange.opacity(colorScheme == .dark ? 0.025 : 0.035), .clear], center: .bottomLeading, startRadius: 0, endRadius: 480)
            }
        }.ignoresSafeArea().accessibilityHidden(true)
    }
}

private struct BridgeGlassModifier: ViewModifier {
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let cornerRadius: CGFloat
    let interactive: Bool
    @ViewBuilder func body(content: Content) -> some View {
        if reduceTransparency {
            content.background(BridgePalette.secondarySurface, in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous).strokeBorder(BridgePalette.separator))
        } else {
            platformGlass(content)
        }
    }
    @ViewBuilder private func platformGlass(_ content: Content) -> some View {
        // Older SDKs still compile the macOS 13 material fallback.
        #if compiler(>=6.2)
        if #available(macOS 26.0, *) {
            content.glassEffect(.regular.interactive(interactive && !reduceMotion), in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
        } else {
            fallback(content)
        }
        #else
        fallback(content)
        #endif
    }
    private func fallback(_ content: Content) -> some View {
        content.background(.regularMaterial, in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous).strokeBorder(BridgePalette.separator))
    }

}

extension View {
    func bridgeGlass(cornerRadius: CGFloat = 16, interactive: Bool = false) -> some View {
        modifier(BridgeGlassModifier(cornerRadius: cornerRadius, interactive: interactive))
    }
    func bridgeSurface(cornerRadius: CGFloat = 20) -> some View {
        modifier(BridgeSurfaceModifier(cornerRadius: cornerRadius))
    }
}

private struct BridgeSurfaceModifier: ViewModifier {
    @Environment(\.colorSchemeContrast) private var contrast
    let cornerRadius: CGFloat
    func body(content: Content) -> some View {
        content.background(BridgePalette.surface, in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                .strokeBorder(contrast == .increased ? Color.secondary : BridgePalette.separator))
    }
}

struct Card<Content: View>: View {
    let title: String
    @ViewBuilder var content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(title).font(.system(size: 18, weight: .semibold)).foregroundStyle(.primary)
            content
        }
        .padding(22)
        .frame(maxWidth: .infinity, alignment: .leading)
        .bridgeSurface()
    }
}

struct BridgeStatusBadge: View {
    let title: String
    let healthy: Bool
    var body: some View {
        HStack(spacing: 7) {
            Image(systemName: healthy ? "checkmark.circle.fill" : "circle.dashed")
                .foregroundStyle(healthy ? teal : Color.secondary)
            Text(title).foregroundStyle(.secondary)
        }
        .font(.system(size: 12, weight: .medium))
        .accessibilityElement(children: .combine)
    }
}

struct BridgeEmptyState: View {
    let symbol: String
    let title: String
    let detail: String
    var body: some View {
        VStack(spacing: 15) {
            Image(systemName: symbol).font(.system(size: 31, weight: .light)).foregroundStyle(teal)
                .frame(width: 72, height: 72).background(teal.opacity(0.07), in: RoundedRectangle(cornerRadius: 23))
                .accessibilityHidden(true)
            Text(title).font(.system(size: 22, weight: .medium, design: .serif)).multilineTextAlignment(.center)
            Text(detail).font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
                .lineSpacing(3).frame(maxWidth: 350)
        }.padding(30).frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct BridgeSettingRow<Content: View>: View {
    let title: String
    let detail: String
    @ViewBuilder var content: Content
    var body: some View {
        HStack(alignment: .center, spacing: 24) {
            VStack(alignment: .leading, spacing: 5) {
                Text(title).font(.system(size: 14, weight: .medium))
                Text(detail).font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 12)
            content
        }.padding(.vertical, 3)
    }
}

extension Notification.Name {
    static let bridgeFindHighlights = Notification.Name("ReaderBridge.findHighlights")
}
