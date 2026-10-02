import SwiftUI
import AppKit

struct BrandMark: View {
    var body: some View {
        GeometryReader { geometry in
            // Crop the master icon's clear space for the compact sidebar lockup.
            let rect = BrandMarkGeometry.canvas(in: geometry.size)
            ZStack {
                Path(BrandMarkGeometry.fitted(BrandMarkGeometry.page, in: rect)).fill(teal)
                Path(BrandMarkGeometry.fitted(BrandMarkGeometry.otherPage, in: rect)).fill(teal)
                Path(BrandMarkGeometry.fitted(BrandMarkGeometry.bookmark, in: rect))
                    .fill(Color(nsColor: NSColor(name: "BridgeBookmark") { appearance in
                        appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
                            ? NSColor(red: 0.90, green: 0.72, blue: 0.43, alpha: 1)
                            : NSColor(red: 0.58, green: 0.36, blue: 0.12, alpha: 1)
                    }))
            }
        }
        .aspectRatio(BrandMarkGeometry.bounds.width / BrandMarkGeometry.bounds.height, contentMode: .fit)
        .accessibilityHidden(true)
    }
}

enum BrandMenuIcon {
    static let ready = make(ready: true)
    static let offline = make(ready: false)

    private static func make(ready: Bool) -> NSImage {
        let image = NSImage(size: NSSize(width: 22, height: 18), flipped: true) { _ in
            let context = NSGraphicsContext.current!.cgContext
            var rect = BrandMarkGeometry.canvas(in: CGSize(width: 20, height: 14))
            rect.origin.x += 1
            rect.origin.y += 2
            context.setFillColor(NSColor.black.cgColor)
            context.setStrokeColor(NSColor.black.cgColor)
            context.setLineWidth(1)
            for page in [BrandMarkGeometry.page, BrandMarkGeometry.otherPage] {
                context.addPath(BrandMarkGeometry.fitted(page, in: rect))
                if ready { context.fillPath() } else { context.strokePath() }
            }
            context.addPath(BrandMarkGeometry.fitted(BrandMarkGeometry.bookmark, in: rect))
            context.fillPath()
            return true
        }
        image.isTemplate = true
        return image
    }
}
